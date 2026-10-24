"""An admin turns another member's account off (inactive) or on again.

An inactive account cannot log in and its sessions end at once (the login
check and current_user both refuse inactive users). It stays in the home,
so its role and the activity log are kept. Nobody can turn themselves off,
so a home always keeps at least the admin doing it.
"""

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict, StrictBool
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.audit import record_event
from app.authorization import require_role
from app.db_config import get_db
from app.dependencies import client_ip, current_user, require_csrf
from app.models import HomeMembership, Role, User
from app.models import Session as SessionModel

router = APIRouter(prefix="/api/v1/homes/{home_id}/members", tags=["members"])


class ActiveChange(BaseModel):
    model_config = ConfigDict(extra="forbid")
    active: StrictBool


@router.get("/status")
def member_status(
    home_id: str,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> dict[str, bool]:
    """{user_id: active} for everyone in the home (admins only)."""
    require_role(db, user.id, home_id, Role.ADMIN)
    rows = db.execute(
        select(User.id, User.is_active)
        .join(HomeMembership, HomeMembership.user_id == User.id)
        .where(HomeMembership.home_id == home_id)
    ).all()
    return {user_id: bool(active) for user_id, active in rows}


@router.put("/{user_id}/active", dependencies=[Depends(require_csrf)])
def set_active(
    home_id: str,
    user_id: str,
    body: ActiveChange,
    request: Request,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    require_role(db, user.id, home_id, Role.ADMIN)
    if user_id == user.id:
        raise HTTPException(
            status.HTTP_409_CONFLICT, "You cannot turn off your own account"
        )
    membership = db.scalars(
        select(HomeMembership).where(
            HomeMembership.home_id == home_id, HomeMembership.user_id == user_id
        )
    ).first()
    member = db.get(User, user_id)
    if membership is None or member is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found")
    member.is_active = body.active
    if not body.active:  # log them out everywhere now
        db.execute(delete(SessionModel).where(SessionModel.user_id == user_id))
    db.commit()
    record_event(
        db,
        "member_activated" if body.active else "member_deactivated",
        user_id=user.id,
        home_id=home_id,
        ip_address=client_ip(request),
        details={"member_id": user_id},
    )
    return {"user_id": user_id, "active": body.active}
