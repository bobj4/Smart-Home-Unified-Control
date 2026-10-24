"""Server-side sessions (SEC-03).

The browser holds a random token in an HttpOnly cookie; the database holds
only its SHA-256 hash. A session ends after IDLE_TIMEOUT_SECONDS without
activity or TOTAL_TIMEOUT_SECONDS after login, whichever comes first.
Logout deletes the row.
"""

import hashlib
import secrets
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.db_config import settings
from app.models import Session as SessionModel

SESSION_COOKIE = "session_token"
CSRF_COOKIE = "csrf_token"
CSRF_HEADER = "X-CSRF-Token"


def as_utc(value: datetime) -> datetime:
    """SQLite returns naive datetimes; they are stored in UTC."""
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def create_session(
    db: Session, user_id: str, ip_address: str | None
) -> tuple[str, str]:
    """Store a new session and return (session_token, csrf_token)."""
    token = secrets.token_urlsafe(32)
    csrf = secrets.token_urlsafe(32)
    now = datetime.now(UTC)
    db.add(
        SessionModel(
            user_id=user_id,
            hash_token=hash_token(token),
            csrf_token=csrf,
            created_at=now,
            expires_at=now + timedelta(seconds=settings.TOTAL_TIMEOUT_SECONDS),
            last_activity=now,
            ip_address=ip_address,
        )
    )
    db.commit()
    return token, csrf


def get_valid_session(db: Session, token: str | None) -> SessionModel | None:
    """Return the live session for a token and record activity.

    Expired or idle sessions are deleted and None is returned.
    """
    if not token:
        return None
    session = db.scalars(
        select(SessionModel).where(SessionModel.hash_token == hash_token(token))
    ).first()
    if session is None:
        return None
    now = datetime.now(UTC)
    idle = timedelta(seconds=settings.IDLE_TIMEOUT_SECONDS)
    if now >= as_utc(session.expires_at) or now - as_utc(session.last_activity) > idle:
        db.delete(session)
        db.commit()
        return None
    session.last_activity = now
    db.commit()
    return session


def delete_session(db: Session, session: SessionModel) -> None:
    db.delete(session)
    db.commit()


def delete_user_sessions(db: Session, user_id: str) -> None:
    db.execute(delete(SessionModel).where(SessionModel.user_id == user_id))
    db.commit()
