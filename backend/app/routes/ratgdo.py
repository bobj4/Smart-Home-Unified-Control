"""ratgdo garage door openers for one home: add by network address, remove.
Operators and up."""

import ipaddress
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy.orm import Session

from app.audit import record_event
from app.authorization import require_role
from app.db_config import get_db
from app.dependencies import client_ip, current_user, require_csrf
from app.models import Device, Role, User
from app.ratgdo_home import (
    INTEGRATION,
    RatgdoUnavailable,
    add_door,
    door_out,
    list_doors,
    remove_door,
)

router = APIRouter(
    prefix="/api/v1/homes/{home_id}/integrations/ratgdo", tags=["ratgdo"]
)


class DoorIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=100)
    host: str = Field(min_length=1, max_length=45)
    room: str | None = Field(default=None, max_length=50)

    @field_validator("host")
    @classmethod
    def local_address(cls, value: str) -> str:
        """Only addresses on the home network: the server connects to them."""
        try:
            address = ipaddress.ip_address(value.strip())
        except ValueError:
            raise ValueError("host must be the ratgdo's IP address") from None
        if not address.is_private or address.is_loopback or address.is_link_local:
            raise ValueError("host must be an address on your home network")
        return str(address)


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


@router.get("/doors")
def get_doors(
    home_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)
) -> list[dict[str, Any]]:
    require_role(db, user.id, home_id, Role.OPERATOR)
    return [door_out(d) for d in list_doors(db, home_id)]


@router.post(
    "/doors", status_code=status.HTTP_201_CREATED, dependencies=[Depends(require_csrf)]
)
def create_door(
    home_id: str,
    body: DoorIn,
    request: Request,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    require_role(db, user.id, home_id, Role.OPERATOR)
    try:
        device = add_door(db, home_id, body.name.strip(), body.host, body.room)
    except RatgdoUnavailable as error:
        raise HTTPException(error.status_code, error.reason) from None
    _audit(db, request, user, home_id, "device_added", device.id)
    return door_out(device)


@router.delete("/doors/{device_id}", dependencies=[Depends(require_csrf)])
def delete_door(
    home_id: str,
    device_id: str,
    request: Request,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> dict[str, str]:
    require_role(db, user.id, home_id, Role.OPERATOR)
    device = db.get(Device, device_id)
    if device is None or device.home_id != home_id or device.integration != INTEGRATION:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found")
    remove_door(db, device)
    _audit(db, request, user, home_id, "device_removed", device_id)
    return {"detail": "Opener removed"}
