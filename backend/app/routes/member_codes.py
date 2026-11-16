"""The active codes a home's admins made, to show on their cards again: the
person's enrollment code on "Waiting to join", a reset code on the member.
Admins only. The enrollment list itself never shows codes."""

from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.authorization import require_role
from app.db_config import get_db
from app.dependencies import current_user
from app.member_codes import shown
from app.models import Enrollment, HomeMembership, PasswordReset, Role, User
from app.sessions import as_utc

router = APIRouter(prefix="/api/v1/homes/{home_id}/members", tags=["members"])


@router.get("/codes")
def active_codes(
    home_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)
) -> dict[str, Any]:
    """{"enrollments": {enrollment id: code}, "resets": {member's user id:
    {"code", "expires_at"}}} (the newest reset code an admin here made)."""
    require_role(db, user.id, home_id, Role.ADMIN)
    now = datetime.now(UTC)
    enrollments: dict[str, str] = {}
    for enrollment in db.scalars(
        select(Enrollment).where(
            Enrollment.home_id == home_id,
            Enrollment.used_at.is_(None),
            Enrollment.code_secret.is_not(None),
        )
    ):
        code = shown(enrollment.code_secret)
        if code and as_utc(enrollment.expires_at) > now:
            enrollments[enrollment.id] = code
    members = select(HomeMembership.user_id).where(HomeMembership.home_id == home_id)
    admins = members.where(HomeMembership.role == Role.ADMIN.value)
    resets: dict[str, dict[str, str]] = {}
    for reset in db.scalars(
        select(PasswordReset)
        .where(
            PasswordReset.user_id.in_(members),
            PasswordReset.created_by.in_(admins),
            PasswordReset.created_by != PasswordReset.user_id,
            PasswordReset.used_at.is_(None),
            PasswordReset.code_secret.is_not(None),
        )
        .order_by(PasswordReset.created_at)
    ):
        code = shown(reset.code_secret)
        if code and as_utc(reset.expires_at) > now:
            resets[reset.user_id] = {
                "code": code,
                "expires_at": as_utc(reset.expires_at).isoformat(),
            }
    return {"enrollments": enrollments, "resets": resets}
