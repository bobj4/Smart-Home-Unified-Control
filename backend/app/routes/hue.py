"""Philips Hue for one home: pair the bridge, find its lights again, or
disconnect it. Operators and up."""

import ipaddress
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy.orm import Session

from app.audit import record_event
from app.authorization import require_role
from app.db_config import get_db
from app.dependencies import client_ip, current_user, require_csrf
from app.hue_home import HueUnavailable, pair, status, sync, unpair
from app.models import Role, User

router = APIRouter(prefix="/api/v1/homes/{home_id}/integrations/hue", tags=["hue"])


class BridgeIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    host: str = Field(min_length=1, max_length=45)

    @field_validator("host")
    @classmethod
    def local_address(cls, value: str) -> str:
        """Only addresses on the home network: the server connects to them."""
        try:
            address = ipaddress.ip_address(value.strip())
        except ValueError:
            raise ValueError("host must be the bridge's IP address") from None
        if not address.is_private or address.is_loopback or address.is_link_local:
            raise ValueError("host must be an address on your home network")
        return str(address)


def _audit(db: Session, request: Request, user: User, home_id: str, event: str) -> None:
    record_event(
        db,
        event,
        user_id=user.id,
        home_id=home_id,
        ip_address=client_ip(request),
        details={"integration": "hue"},
    )


def _run(action: Any) -> Any:
    try:
        return action()
    except HueUnavailable as error:
        raise HTTPException(error.status_code, error.reason) from None


@router.get("")
def get_bridge(
    home_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)
) -> dict[str, Any]:
    require_role(db, user.id, home_id, Role.OPERATOR)
    return status(db, home_id)


@router.post("/pair", dependencies=[Depends(require_csrf)])
def pair_bridge(
    home_id: str,
    body: BridgeIn,
    request: Request,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Press the bridge's button first; then this asks it for a key."""
    require_role(db, user.id, home_id, Role.OPERATOR)
    found = _run(lambda: pair(db, home_id, body.host))
    _audit(db, request, user, home_id, "integration_paired")
    return {**status(db, home_id), **found}


@router.post("/sync", dependencies=[Depends(require_csrf)])
def sync_bridge(
    home_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)
) -> dict[str, Any]:
    require_role(db, user.id, home_id, Role.OPERATOR)
    found = _run(lambda: sync(db, home_id))
    return {**status(db, home_id), **found}


@router.delete("", dependencies=[Depends(require_csrf)])
def unpair_bridge(
    home_id: str,
    request: Request,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    require_role(db, user.id, home_id, Role.OPERATOR)
    unpair(db, home_id)
    _audit(db, request, user, home_id, "integration_unpaired")
    return status(db, home_id)
