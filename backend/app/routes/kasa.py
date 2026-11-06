"""TP-Link Kasa for one home: add devices by address, remove them, and the
optional TP-Link login newer firmware needs. Operators and up."""

import ipaddress
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy.orm import Session

from app.audit import record_event
from app.authorization import require_role
from app.db_config import get_db
from app.dependencies import client_ip, current_user, require_csrf
from app.kasa_home import (
    INTEGRATION,
    KasaUnavailable,
    add_host,
    device_out,
    list_devices,
    login_label,
    remove_host,
    remove_login,
    save_login,
)
from app.models import Device, Role, User

router = APIRouter(prefix="/api/v1/homes/{home_id}/integrations/kasa", tags=["kasa"])


class HostIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    host: str = Field(min_length=1, max_length=45)
    room: str | None = Field(default=None, max_length=50)

    @field_validator("host")
    @classmethod
    def local_address(cls, value: str) -> str:
        """Only addresses on the home network: the server connects to them."""
        try:
            address = ipaddress.ip_address(value.strip())
        except ValueError:
            raise ValueError("host must be the device's IP address") from None
        if not address.is_private or address.is_loopback or address.is_link_local:
            raise ValueError("host must be an address on your home network")
        return str(address)


class LoginIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    email: str = Field(min_length=3, max_length=255)
    password: str = Field(min_length=1, max_length=255)


def _audit(db: Session, request: Request, user: User, home_id: str, event: str) -> None:
    record_event(
        db,
        event,
        user_id=user.id,
        home_id=home_id,
        ip_address=client_ip(request),
        details={"integration": INTEGRATION},
    )


@router.get("")
def get_kasa(
    home_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)
) -> dict[str, Any]:
    require_role(db, user.id, home_id, Role.OPERATOR)
    return {
        "login": login_label(db, home_id),
        "devices": [device_out(d) for d in list_devices(db, home_id)],
    }


@router.post(
    "/devices",
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_csrf)],
)
def add_devices(
    home_id: str,
    body: HostIn,
    request: Request,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> list[dict[str, Any]]:
    require_role(db, user.id, home_id, Role.OPERATOR)
    try:
        added = add_host(db, home_id, body.host, body.room)
    except KasaUnavailable as error:
        raise HTTPException(error.status_code, error.reason) from None
    _audit(db, request, user, home_id, "device_added")
    return [device_out(d) for d in added]


@router.delete("/devices/{device_id}", dependencies=[Depends(require_csrf)])
def delete_device(
    home_id: str,
    device_id: str,
    request: Request,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> dict[str, str]:
    """Removes everything at that address (all of a strip's outlets)."""
    require_role(db, user.id, home_id, Role.OPERATOR)
    device = db.get(Device, device_id)
    if device is None or device.home_id != home_id or device.integration != INTEGRATION:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found")
    remove_host(db, device)
    _audit(db, request, user, home_id, "device_removed")
    return {"detail": "Removed"}


@router.put("/login", dependencies=[Depends(require_csrf)])
def put_login(
    home_id: str,
    body: LoginIn,
    request: Request,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """The TP-Link (Kasa app) account, for devices with newer firmware."""
    require_role(db, user.id, home_id, Role.OPERATOR)
    try:
        save_login(db, home_id, body.email.strip(), body.password)
    except KasaUnavailable as error:
        raise HTTPException(error.status_code, error.reason) from None
    _audit(db, request, user, home_id, "integration_login_saved")
    return {"login": login_label(db, home_id)}


@router.delete("/login", dependencies=[Depends(require_csrf)])
def delete_login(
    home_id: str,
    request: Request,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    require_role(db, user.id, home_id, Role.OPERATOR)
    remove_login(db, home_id)
    _audit(db, request, user, home_id, "integration_login_removed")
    return {"login": None}
