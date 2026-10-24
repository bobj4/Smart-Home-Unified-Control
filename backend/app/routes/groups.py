"""Device groups for a home: everyone uses them; operators and admins make,
edit and delete them."""

import json
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict, Field, StrictBool
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.audit import record_event
from app.authorization import require_role
from app.db_config import get_db
from app.dependencies import client_ip, current_user, require_csrf
from app.groups import (
    GROUP_COMMANDS,
    check_devices,
    ensure_room,
    group_out,
    list_groups,
    members,
    room_names,
    set_device_group,
)
from app.models import Device, DeviceGroup, Home, Role, Room, User
from app.routes.devices import (
    CommandRejected,
    DeviceCommand,
    _device_out,
    apply_command,
)

router = APIRouter(prefix="/api/v1/homes/{home_id}/groups", tags=["groups"])
home_router = APIRouter(prefix="/api/v1/homes/{home_id}", tags=["groups"])


class GroupIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=100)
    room: str | None = Field(default=None, max_length=50)
    device_ids: list[str] = Field(default_factory=list, max_length=200)


class GroupChange(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str | None = Field(default=None, min_length=1, max_length=100)
    room: str | None = Field(default=None, max_length=50)  # "" = no room
    device_ids: list[str] | None = Field(default=None, max_length=200)


class RoomIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=50)


class DeviceGroupChoice(BaseModel):
    model_config = ConfigDict(extra="forbid")
    group_id: str | None = None


class Display(BaseModel):
    model_config = ConfigDict(extra="forbid")
    show_grouped_devices: StrictBool


def _group(db: Session, home_id: str, group_id: str) -> DeviceGroup:
    group = db.get(DeviceGroup, group_id)
    if group is None or group.home_id != home_id or group.deleted:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found")
    return group


def _devices(db: Session, home_id: str, ids: list[str]) -> list[str]:
    try:
        return check_devices(db, home_id, ids)
    except ValueError as error:
        raise HTTPException(422, str(error)) from None


def _audit(
    db: Session, request: Request, user: User, home_id: str, event: str, **details: Any
) -> None:
    record_event(
        db,
        event,
        user_id=user.id,
        home_id=home_id,
        ip_address=client_ip(request),
        details=details,
    )


@router.get("")
def get_groups(
    home_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)
) -> list[dict[str, Any]]:
    require_role(db, user.id, home_id)
    return [group_out(db, g) for g in list_groups(db, home_id)]


@router.post("", status_code=201, dependencies=[Depends(require_csrf)])
def create_group(
    home_id: str,
    body: GroupIn,
    request: Request,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    require_role(db, user.id, home_id, Role.OPERATOR)
    group = DeviceGroup(
        home_id=home_id,
        name=body.name.strip(),
        room=(body.room or "").strip() or None,
        device_ids=json.dumps(_devices(db, home_id, body.device_ids)),
    )
    db.add(group)
    db.commit()
    _audit(db, request, user, home_id, "group_created", group_id=group.id)
    return group_out(db, group)


@router.patch("/{group_id}", dependencies=[Depends(require_csrf)])
def change_group(
    home_id: str,
    group_id: str,
    body: GroupChange,
    request: Request,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    require_role(db, user.id, home_id, Role.OPERATOR)
    group = _group(db, home_id, group_id)
    if body.name is not None:
        group.name = body.name.strip()
    if body.room is not None:
        group.room = body.room.strip() or None
    if body.device_ids is not None:
        group.device_ids = json.dumps(_devices(db, home_id, body.device_ids))
    db.commit()
    _audit(db, request, user, home_id, "group_changed", group_id=group.id)
    return group_out(db, group)


@router.delete("/{group_id}", dependencies=[Depends(require_csrf)])
def delete_group(
    home_id: str,
    group_id: str,
    request: Request,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> dict[str, str]:
    require_role(db, user.id, home_id, Role.OPERATOR)
    group = _group(db, home_id, group_id)
    if group.source == "cync":
        group.deleted = True  # so the next Cync sync does not bring it back
    else:
        db.delete(group)
    db.commit()
    _audit(db, request, user, home_id, "group_deleted", group_id=group_id)
    return {"detail": "Deleted"}


@router.post("/{group_id}/command", dependencies=[Depends(require_csrf)])
def group_command(
    home_id: str,
    group_id: str,
    body: DeviceCommand,
    request: Request,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Send the command to every device in the group that can take it. One
    device failing does not stop the others; the answer lists each result."""
    require_role(db, user.id, home_id)
    group = _group(db, home_id, group_id)
    if body.command not in GROUP_COMMANDS:
        raise HTTPException(422, "groups take on, off, brightness, white and colour")
    audit = {"user_id": user.id, "home_id": home_id, "ip_address": client_ip(request)}
    results: list[dict[str, Any]] = []
    for device in members(db, group):
        if device.type not in ("light", "plug") or (
            device.type == "plug" and body.command not in ("turn_on", "turn_off")
        ):
            results.append({"device_id": device.id, "ok": None, "detail": "skipped"})
            continue
        try:
            apply_command(db, device, body, audit)
            results.append({"device_id": device.id, "ok": True, "detail": None})
        except CommandRejected as rejected:
            results.append(
                {"device_id": device.id, "ok": False, "detail": rejected.reason}
            )
    return {
        "group": group_out(db, group),
        "results": results,
        "devices": [_device_out(d) for d in members(db, group)],
    }


# ------------------------------------------------------------ rooms


@home_router.get("/rooms")
def get_rooms(
    home_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)
) -> list[str]:
    require_role(db, user.id, home_id)
    return room_names(db, home_id)


@home_router.post("/rooms", status_code=201, dependencies=[Depends(require_csrf)])
def create_room(
    home_id: str,
    body: RoomIn,
    request: Request,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> list[str]:
    require_role(db, user.id, home_id, Role.OPERATOR)
    ensure_room(db, home_id, body.name)
    db.commit()
    _audit(db, request, user, home_id, "room_created", name=body.name.strip())
    return room_names(db, home_id)


@home_router.delete("/rooms/{name}", dependencies=[Depends(require_csrf)])
def delete_room(
    home_id: str,
    name: str,
    request: Request,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> list[str]:
    """Devices and groups in the room move to "No room"."""
    require_role(db, user.id, home_id, Role.OPERATOR)
    for room in db.scalars(
        select(Room).where(Room.home_id == home_id, Room.name == name)
    ):
        db.delete(room)
    for device in db.scalars(
        select(Device).where(Device.home_id == home_id, Device.room == name)
    ):
        device.room = None
    for group in db.scalars(
        select(DeviceGroup).where(
            DeviceGroup.home_id == home_id, DeviceGroup.room == name
        )
    ):
        group.room = None
    db.commit()
    _audit(db, request, user, home_id, "room_deleted", name=name)
    return room_names(db, home_id)


@home_router.put("/devices/{device_id}/group", dependencies=[Depends(require_csrf)])
def choose_group(
    home_id: str,
    device_id: str,
    body: DeviceGroupChoice,
    request: Request,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> list[dict[str, Any]]:
    """Put a device in one group, or in none."""
    require_role(db, user.id, home_id, Role.OPERATOR)
    device = db.get(Device, device_id)
    if device is None or device.home_id != home_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found")
    if body.group_id is not None:
        _group(db, home_id, body.group_id)
    set_device_group(db, home_id, device_id, body.group_id)
    _audit(
        db,
        request,
        user,
        home_id,
        "device_group_set",
        device_id=device_id,
        group_id=body.group_id,
    )
    return [group_out(db, g) for g in list_groups(db, home_id)]


# ------------------------------------------------------------ display


@home_router.get("/display")
def get_display(
    home_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)
) -> dict[str, bool]:
    require_role(db, user.id, home_id)
    home = db.get(Home, home_id)
    return {"show_grouped_devices": bool(home and home.show_grouped_devices)}


@home_router.put("/display", dependencies=[Depends(require_csrf)])
def set_display(
    home_id: str,
    body: Display,
    request: Request,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> dict[str, bool]:
    require_role(db, user.id, home_id, Role.ADMIN)
    home = db.get(Home, home_id)
    if home is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found")
    home.show_grouped_devices = body.show_grouped_devices
    db.commit()
    _audit(
        db,
        request,
        user,
        home_id,
        "display_changed",
        show_grouped_devices=body.show_grouped_devices,
    )
    return {"show_grouped_devices": home.show_grouped_devices}
