"""LG webOS TVs for one home: add by network address, pair (accept the
prompt on the TV), remove. Operators and up."""

import ipaddress
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy.orm import Session

from app.audit import record_event
from app.authorization import require_role
from app.db_config import get_db
from app.dependencies import client_ip, current_user, require_csrf
from app.lg_home import (
    INTEGRATION,
    LgUnavailable,
    add_tv,
    list_tvs,
    pair_tv,
    remove_tv,
    tv_out,
)
from app.models import Device, Role, User

router = APIRouter(prefix="/api/v1/homes/{home_id}/integrations/lg_tv", tags=["lg"])


class LgIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=100)
    host: str = Field(min_length=1, max_length=45)
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
    db: Session, request: Request, user: User, home_id: str, event: str, device_id: str
) -> None:
    record_event(
        db,
        event,
        user_id=user.id,
        home_id=home_id,
        ip_address=client_ip(request),
        details={"integration": INTEGRATION, "device_id": device_id},
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
    body: LgIn,
    request: Request,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    require_role(db, user.id, home_id, Role.OPERATOR)
    mac = body.mac.upper().replace("-", ":") if body.mac else None
    try:
        device = add_tv(db, home_id, body.name.strip(), body.host, mac, body.room)
    except LgUnavailable as error:
        raise HTTPException(error.status_code, error.reason) from None
    _audit(db, request, user, home_id, "tv_added", device.id)
    return tv_out(device)


@router.post("/tvs/{device_id}/pair", dependencies=[Depends(require_csrf)])
def pair(
    home_id: str,
    device_id: str,
    request: Request,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """The TV shows a prompt: accept it with the remote within a minute."""
    require_role(db, user.id, home_id, Role.OPERATOR)
    device = _tv(db, home_id, device_id)
    try:
        pair_tv(db, device)
    except LgUnavailable as error:
        raise HTTPException(error.status_code, error.reason) from None
    _audit(db, request, user, home_id, "tv_paired", device_id)
    return tv_out(device)


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
    _audit(db, request, user, home_id, "tv_removed", device_id)
    return {"detail": "TV removed"}
