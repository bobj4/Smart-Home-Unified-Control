"""A home's login policy. Owner only."""

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict, StrictBool
from sqlalchemy.orm import Session

from app.audit import record_event
from app.authorization import require_role
from app.db_config import get_db
from app.dependencies import client_ip, current_user, require_csrf
from app.models import Home, Role, User

router = APIRouter(prefix="/api/v1/homes/{home_id}/security", tags=["security"])


class SecurityPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")
    require_two_factor: StrictBool


@router.get("")
def get_policy(
    home_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)
) -> dict[str, Any]:
    require_role(db, user.id, home_id, Role.ADMIN)
    home = db.get(Home, home_id)
    return {"require_two_factor": bool(home and home.require_two_factor)}


@router.put("", dependencies=[Depends(require_csrf)])
def set_policy(
    home_id: str,
    body: SecurityPolicy,
    request: Request,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Require two-factor login for every member, or stop requiring it.
    The owner must use two-factor themselves before requiring it."""
    require_role(db, user.id, home_id, Role.ADMIN)
    if body.require_two_factor and not user.is_totp_enabled:
        raise HTTPException(
            status.HTTP_409_CONFLICT, "Turn on two-factor login for yourself first"
        )
    home = db.get(Home, home_id)
    if home is None:  # cannot happen: require_role found the membership
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found")
    home.require_two_factor = body.require_two_factor
    db.commit()
    record_event(
        db,
        "home_security_changed",
        user_id=user.id,
        home_id=home_id,
        ip_address=client_ip(request),
        details={"require_two_factor": body.require_two_factor},
    )
    return {"require_two_factor": home.require_two_factor}
