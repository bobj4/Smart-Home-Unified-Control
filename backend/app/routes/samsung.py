"""Samsung TVs for one home: add by network address, pair, remove. Admin+."""

import ipaddress
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy.orm import Session

from app.audit import record_event
from app.authorization import require_role
from app.db_config import get_db
from app.dependencies import client_ip, current_user, require_csrf
from app.models import Device, Role, User
from app.samsung_home import (
    INTEGRATION,
    SamsungUnavailable,
    add_tv,
    finish_pin_pairing,
    list_tvs,
    pair_tv,
    remove_tv,
    tv_out,
    update_tv,
)

router = APIRouter(
    prefix="/api/v1/homes/{home_id}/integrations/samsung_tv", tags=["samsung"]
)


class TvIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=100)
    host: str = Field(min_length=1, max_length=45)
    protocol: Literal["tizen", "legacy", "encrypted"] = "tizen"
    mac: str | None = Field(
        default=None, pattern=r"^([0-9A-Fa-f]{2}[:-]){5}[0-9A-Fa-f]{2}$"
    )
    room: str | None = Field(default=None, max_length=50)

    @field_validator("host")
    @classmethod
    def local_address(cls, value: str) -> str:
        """Only addresses on the home network: the server connects to them."""
        try:
            address = ipaddress.ip_address(value.strip())
        except ValueError:
            raise ValueError("host must be the TV's IP address") from None
        if not address.is_private or address.is_loopback or address.is_link_local:
            raise ValueError("host must be an address on your home network")
        return str(address)


def _tv(db: Session, home_id: str, device_id: str) -> Device:
    device = db.get(Device, device_id)
    if device is None or device.home_id != home_id or device.integration != INTEGRATION:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found")
    return device


def _audit(
    db: Session, request: Request, user: User, home_id: str, event: str, **details: Any
) -> None:
    record_event(
        db,
        event,
        user_id=user.id,
        home_id=home_id,
        ip_address=client_ip(request),
        details={"integration": INTEGRATION, **details},
    )


@router.get("/tvs")
def get_tvs(
    home_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)
) -> list[dict[str, Any]]:
    require_role(db, user.id, home_id, Role.OPERATOR)
    return [tv_out(d) for d in list_tvs(db, home_id)]


@router.post(
    "/tvs", status_code=status.HTTP_201_CREATED, dependencies=[Depends(require_csrf)]
)
def create_tv(
    home_id: str,
    body: TvIn,
    request: Request,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    require_role(db, user.id, home_id, Role.OPERATOR)
    mac = body.mac.upper().replace("-", ":") if body.mac else None
    try:
        device = add_tv(
            db, home_id, body.name.strip(), body.host, body.protocol, mac, body.room
        )
    except SamsungUnavailable as error:
        raise HTTPException(error.status_code, error.reason) from None
    _audit(
        db,
        request,
        user,
        home_id,
        "tv_added",
        device_id=device.id,
        protocol=body.protocol,
    )
    return tv_out(device)


@router.put("/tvs/{device_id}", dependencies=[Depends(require_csrf)])
def edit_tv(
    home_id: str,
    device_id: str,
    body: TvIn,
    request: Request,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Name, room, address, MAC and protocol. A new address or protocol means
    pairing again (the answer says so)."""
    require_role(db, user.id, home_id, Role.OPERATOR)
    device = _tv(db, home_id, device_id)
    mac = body.mac.upper().replace("-", ":") if body.mac else None
    try:
        room = body.room if "room" in body.model_fields_set else device.room
        repair = update_tv(
            db, device, body.name.strip(), body.host, body.protocol, mac, room
        )
    except SamsungUnavailable as error:
        raise HTTPException(error.status_code, error.reason) from None
    _audit(db, request, user, home_id, "tv_changed", device_id=device.id, repair=repair)
    return {**tv_out(device), "pair_again": repair}


@router.post("/tvs/{device_id}/pair", dependencies=[Depends(require_csrf)])
def pair(
    home_id: str,
    device_id: str,
    request: Request,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """The TV shows an Allow prompt: someone presses Allow within about 30 s.
    2014-2015 TVs show a PIN instead ("pin_required"): send it to /pin."""
    require_role(db, user.id, home_id, Role.OPERATOR)
    device = _tv(db, home_id, device_id)
    try:
        pin_required = pair_tv(db, device)
    except SamsungUnavailable as error:
        _audit(
            db,
            request,
            user,
            home_id,
            "tv_pair_failed",
            device_id=device_id,
            reason=error.reason,
        )
        raise HTTPException(error.status_code, error.reason) from None
    if pin_required:
        _audit(db, request, user, home_id, "tv_pin_shown", device_id=device_id)
        return {**tv_out(device), "pin_required": True}
    _audit(db, request, user, home_id, "tv_paired", device_id=device_id)
    return {**tv_out(device), "pin_required": False}


class PinIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    pin: str = Field(pattern=r"^\d{4}$")


@router.post("/tvs/{device_id}/pin", dependencies=[Depends(require_csrf)])
def pair_with_pin(
    home_id: str,
    device_id: str,
    body: PinIn,
    request: Request,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """2014-2015 TVs: the PIN the TV shows after /pair."""
    require_role(db, user.id, home_id, Role.OPERATOR)
    device = _tv(db, home_id, device_id)
    try:
        finish_pin_pairing(db, device, body.pin)
    except SamsungUnavailable as error:
        _audit(
            db,
            request,
            user,
            home_id,
            "tv_pair_failed",
            device_id=device_id,
            reason=error.reason,
        )
        raise HTTPException(error.status_code, error.reason) from None
    _audit(db, request, user, home_id, "tv_paired", device_id=device_id)
    return {**tv_out(device), "pin_required": False}


@router.delete("/tvs/{device_id}", dependencies=[Depends(require_csrf)])
def delete_tv(
    home_id: str,
    device_id: str,
    request: Request,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> dict[str, str]:
    require_role(db, user.id, home_id, Role.OPERATOR)
    remove_tv(db, _tv(db, home_id, device_id))
    _audit(db, request, user, home_id, "tv_removed", device_id=device_id)
    return {"detail": "Removed"}
