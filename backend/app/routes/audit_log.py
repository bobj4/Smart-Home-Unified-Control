"""Owner's view of a home's activity log."""

import json
from typing import Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

from app.authorization import require_role
from app.db_config import get_db
from app.dependencies import current_user
from app.models import AuditEvent, HomeMembership, Role, User
from app.sessions import as_utc

router = APIRouter(prefix="/api/v1/homes/{home_id}/audit", tags=["audit"])


@router.get("")
def list_events(
    home_id: str,
    limit: int = Query(default=50, ge=1, le=200),
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> list[dict[str, Any]]:
    """Newest first: events for this home, and account events (logins and so
    on) of this home's members."""
    require_role(db, user.id, home_id, Role.ADMIN)
    members = select(HomeMembership.user_id).where(HomeMembership.home_id == home_id)
    rows = db.execute(
        select(AuditEvent, User.email)
        .outerjoin(User, User.id == AuditEvent.user_id)
        .where(
            or_(
                AuditEvent.home_id == home_id,
                and_(AuditEvent.home_id.is_(None), AuditEvent.user_id.in_(members)),
            )
        )
        .order_by(AuditEvent.created_at.desc())
        .limit(limit)
    )
    return [
        {
            "created_at": as_utc(event.created_at).isoformat(),
            "event_type": event.event_type,
            "user_email": email,
            "ip_address": event.ip_address,
            "details": json.loads(event.details or "{}"),
        }
        for event, email in rows
    ]
