"""Where everyone is logged in, for admins (Admin > 2 Factor Login, beside
everyone's approved devices).

  GET    /api/v1/admin/sessions        the logged-in devices of the people
                                       in my homes, newest activity first
  DELETE /api/v1/admin/sessions/{id}   log one of them out

Like approved devices, an admin sees the people who share a home where they
are an admin (SEC-11: never other homes' people).
"""

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.audit import record_event
from app.db_config import get_db
from app.dependencies import client_ip, current_session, current_user, require_csrf
from app.models import Session as SessionModel
from app.models import User
from app.routes.login_times import _people, require_admin
from app.sessions import as_utc

router = APIRouter(prefix="/api/v1/admin/sessions", tags=["login times"])


@router.get("")
def all_sessions(
    user: User = Depends(current_user),
    session: SessionModel = Depends(current_session),
    db: Session = Depends(get_db),
) -> list[dict[str, Any]]:
    people = _people(db, require_admin(db, user))
    rows = db.scalars(
        select(SessionModel)
        .where(SessionModel.user_id.in_(list(people)))
        .order_by(SessionModel.last_activity.desc())
    )
    return [
        {
            "id": s.id,
            "user_id": s.user_id,
            "user": people[s.user_id].email,
            "user_name": people[s.user_id].name,
            "created_at": as_utc(s.created_at).isoformat(),
            "last_activity": as_utc(s.last_activity).isoformat(),
            "ip_address": s.ip_address,
            "current": s.id == session.id,
        }
        for s in rows
    ]


@router.delete("/{session_id}", dependencies=[Depends(require_csrf)])
def end_session(
    session_id: str,
    request: Request,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> dict[str, str]:
    people = _people(db, require_admin(db, user))
    target = db.get(SessionModel, session_id)
    if target is None or target.user_id not in people:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found")
    whose = target.user_id
    db.delete(target)
    db.commit()
    record_event(
        db,
        "session_revoked_by_admin",
        user_id=user.id,
        ip_address=client_ip(request),
        details={"user_id": whose},
    )
    return {"detail": "Logged out"}
