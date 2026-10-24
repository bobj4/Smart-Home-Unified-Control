"""Guest routes (see app/guest_access.py).

  GET  /api/v1/homes/{home_id}/guest                       the guest's page
  POST /api/v1/homes/{home_id}/guest/devices/{id}/command  a guest command
  GET  /api/v1/homes/{home_id}/members/{user_id}/guest-access   (admins)
  PUT  /api/v1/homes/{home_id}/members/{user_id}/guest-access   (admins)

A guest command goes through the same checks as anyone's (safety limits,
the integration, the device answering) after the guest check.
"""

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
from app.features import list_integrations
from app.guest_access import (
    FLAGS,
    access_for,
    access_out,
    allowed,
    can_see,
    membership,
    require_guest,
)
from app.models import GUEST_ROLE, Device, DeviceSafetyLimits, Role, User
from app.routes.devices import (
    CommandRejected,
    DeviceCommand,
    _device_out,
    apply_command,
)
from app.safety import limits_out

router = APIRouter(prefix="/api/v1/homes/{home_id}", tags=["guests"])


class GuestAccessIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    light_power: StrictBool
    light_settings: StrictBool
    cameras: StrictBool
    water_heater: StrictBool
    show_blocked: StrictBool
    thermostat_ids: list[str] = Field(max_length=100)


def _guest_device(device: Device) -> dict[str, Any]:
    out = _device_out(device)
    out.pop("network", None)  # a guest does not need addresses
    return out


@router.get("/guest")
def guest_page(
    home_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)
) -> dict[str, Any]:
    access = require_guest(db, user, home_id)
    devices = []
    for device in db.scalars(
        select(Device).where(Device.home_id == home_id).order_by(Device.name)
    ):
        if can_see(access, device):
            devices.append(_guest_device(device))
        elif access.show_blocked:
            devices.append(
                {
                    "id": device.id,
                    "name": device.name,
                    "type": device.type,
                    "room": device.room,
                    "online": device.online,
                    "state": {},  # never a blocked device's state
                    "blocked": True,
                }
            )
    limits = db.scalars(
        select(DeviceSafetyLimits).where(DeviceSafetyLimits.home_id == home_id)
    )
    return {
        "access": access_out(access),
        "devices": devices,
        "limits": [limits_out(row) for row in limits],
        "integrations_on": [
            i["id"] for i in list_integrations(db, home_id) if i["enabled"]
        ],
    }


@router.post("/guest/devices/{device_id}/command", dependencies=[Depends(require_csrf)])
def guest_command(
    home_id: str,
    device_id: str,
    body: DeviceCommand,
    request: Request,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    access = require_guest(db, user, home_id)
    device = db.scalars(
        select(Device).where(Device.id == device_id, Device.home_id == home_id)
    ).first()
    if device is None or not (can_see(access, device) or access.show_blocked):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found")
    audit = {"user_id": user.id, "home_id": home_id, "ip_address": client_ip(request)}
    if not allowed(access, device, body.command):
        record_event(
            db,
            "guest_command_refused",
            **audit,
            details={"device_id": device.id, "command": body.command},
        )
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Guests cannot do that here")
    try:
        state = apply_command(db, device, body, audit)
    except CommandRejected as rejected:
        raise HTTPException(rejected.status_code, rejected.reason) from None
    return {"device_id": device.id, "state": state}


def _guest_member(db: Session, home_id: str, user_id: str) -> None:
    member = membership(db, user_id, home_id)
    if member is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found")
    if member.role != GUEST_ROLE:
        raise HTTPException(status.HTTP_409_CONFLICT, "That person is not a guest")


@router.get("/members/{user_id}/guest-access")
def get_guest_access(
    home_id: str,
    user_id: str,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    require_role(db, user.id, home_id, Role.ADMIN)
    _guest_member(db, home_id, user_id)
    return access_out(access_for(db, home_id, user_id))


@router.put("/members/{user_id}/guest-access", dependencies=[Depends(require_csrf)])
def set_guest_access(
    home_id: str,
    user_id: str,
    body: GuestAccessIn,
    request: Request,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    require_role(db, user.id, home_id, Role.ADMIN)
    _guest_member(db, home_id, user_id)
    wanted = list(dict.fromkeys(body.thermostat_ids))
    home_thermostats = set(
        db.scalars(
            select(Device.id).where(
                Device.home_id == home_id, Device.type == "thermostat"
            )
        ).all()
    )
    if not set(wanted) <= home_thermostats:
        raise HTTPException(422, "Pick thermostats of this home")
    access = access_for(db, home_id, user_id)
    if access.id is None:
        db.add(access)
    for flag in FLAGS:
        setattr(access, flag, getattr(body, flag))
    access.thermostat_ids = json.dumps(wanted)
    db.commit()
    out = access_out(access)
    record_event(
        db,
        "guest_access_changed",
        user_id=user.id,
        home_id=home_id,
        ip_address=client_ip(request),
        details={"guest_id": user_id, **out},
    )
    return out
