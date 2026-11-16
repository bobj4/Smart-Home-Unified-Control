"""Message of the day (Settings > Admin): shown to everyone after login.

  GET/PUT /api/v1/admin/motd           {"text": str | null}   admins
  POST    /api/v1/account/motd/dismiss {"version": int}       anyone

Each person can close it for now (nothing stored) or dismiss it for good.
A changed text is a new version and shows to everyone again.
"""

from typing import Any

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, ConfigDict, Field, StrictInt
from sqlalchemy.orm import Session

from app.audit import record_event
from app.db_config import get_db
from app.dependencies import client_ip, current_user, require_csrf
from app.login_policy import settings
from app.models import User
from app.routes.login_times import require_admin

router = APIRouter(tags=["message of the day"])
MAX_LENGTH = 2000


class MotdIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: str | None = Field(default=None, max_length=MAX_LENGTH)


class DismissIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    version: StrictInt


def motd_for(db: Session, user: User) -> dict[str, Any] | None:
    """The message for this person, or None (none set, or dismissed for good)."""
    row = settings(db)
    if not row.motd_text or (user.motd_dismissed or 0) >= row.motd_version:
        return None
    return {"text": row.motd_text, "version": row.motd_version}


@router.get("/api/v1/admin/motd")
def get_motd(
    user: User = Depends(current_user), db: Session = Depends(get_db)
) -> dict[str, Any]:
    require_admin(db, user)
    row = settings(db)
    return {"text": row.motd_text, "version": row.motd_version}


@router.put("/api/v1/admin/motd", dependencies=[Depends(require_csrf)])
def set_motd(
    body: MotdIn,
    request: Request,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    require_admin(db, user)
    row = settings(db)
    text = (body.text or "").strip() or None
    if text != row.motd_text:
        row.motd_text = text
        row.motd_version = (row.motd_version or 0) + 1
        db.commit()
        record_event(
            db,
            "motd_changed",
            user_id=user.id,
            ip_address=client_ip(request),
            details={"on": text is not None},
        )
    return {"text": row.motd_text, "version": row.motd_version}


@router.post("/api/v1/account/motd/dismiss", dependencies=[Depends(require_csrf)])
def dismiss_motd(
    body: DismissIn, user: User = Depends(current_user), db: Session = Depends(get_db)
) -> dict[str, Any]:
    """Dismiss for good: this version and older stop showing for this person."""
    user.motd_dismissed = max(user.motd_dismissed or 0, body.version)
    db.commit()
    return {"motd": motd_for(db, user)}
