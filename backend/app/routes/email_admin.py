"""Settings > Admin > Email server (optional), and recovery codes by email."""

import secrets
import time
from collections import defaultdict
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import mailer, vault
from app.audit import record_event
from app.db_config import get_db
from app.dependencies import client_ip, current_user, require_csrf
from app.login_policy import settings
from app.models import PasswordReset, User
from app.routes.admin import _hash, _require_owner_somewhere
from app.vault import VaultError

router = APIRouter(prefix="/api/v1/admin/email", tags=["admin"])
public_router = APIRouter(prefix="/api/v1", tags=["auth"])

RESET_LIFETIME = timedelta(hours=1)
MAX_EMAILS_PER_HOUR = 3
_sent: dict[str, list[float]] = defaultdict(list)


def _limit(login: str) -> None:
    """At most a few emails per account per hour (it costs someone's inbox)."""
    now = time.monotonic()
    recent = [t for t in _sent[login] if now - t < 3600]
    if len(recent) >= MAX_EMAILS_PER_HOUR:
        raise HTTPException(429, "Too many requests. Try again later.")
    _sent[login] = [*recent, now]


_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"


class EmailServer(BaseModel):
    model_config = ConfigDict(extra="forbid")
    host: str = Field(min_length=1, max_length=255)
    port: int = Field(ge=1, le=65535)
    security: Literal["starttls", "ssl", "none"]
    username: str | None = Field(default=None, max_length=255)
    password: str | None = Field(default=None, max_length=1024)  # None: keep
    sender: str = Field(min_length=3, max_length=255, pattern=r"^[^@\s]+@[^@\s]+$")


class TestEmail(BaseModel):
    model_config = ConfigDict(extra="forbid")
    to: str = Field(min_length=3, max_length=255, pattern=r"^[^@\s]+@[^@\s]+$")


class EmailRecovery(BaseModel):
    model_config = ConfigDict(extra="forbid")
    login: str = Field(min_length=3, max_length=255)


def _out(db: Session) -> dict[str, Any]:
    row = settings(db)
    return {
        "configured": mailer.configured(row),
        "host": row.smtp_host,
        "port": row.smtp_port,
        "security": row.smtp_security,
        "username": row.smtp_username,
        "sender": row.smtp_from,
        "password_saved": row.smtp_password is not None,
    }


@router.get("")
def get_email(
    user: User = Depends(current_user), db: Session = Depends(get_db)
) -> dict[str, Any]:
    _require_owner_somewhere(db, user)
    return _out(db)


@router.put("", dependencies=[Depends(require_csrf)])
def save_email(
    body: EmailServer,
    request: Request,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    _require_owner_somewhere(db, user)
    row = settings(db)
    if body.password is not None:
        try:
            row.smtp_password = (
                vault.encrypt({"password": body.password}) if body.password else None
            )
        except VaultError as error:
            raise HTTPException(409, str(error)) from None
    row.smtp_host = body.host.strip()
    row.smtp_port = body.port
    row.smtp_security = body.security
    row.smtp_username = (body.username or "").strip() or None
    row.smtp_from = body.sender.strip()
    db.commit()
    record_event(
        db,
        "email_server_saved",
        user_id=user.id,
        ip_address=client_ip(request),
        details={"host": row.smtp_host, "port": row.smtp_port},
    )
    return _out(db)


@router.delete("", dependencies=[Depends(require_csrf)])
def remove_email(
    request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)
) -> dict[str, Any]:
    _require_owner_somewhere(db, user)
    row = settings(db)
    row.smtp_host = row.smtp_username = row.smtp_password = row.smtp_from = None
    db.commit()
    record_event(
        db, "email_server_removed", user_id=user.id, ip_address=client_ip(request)
    )
    return _out(db)


@router.post("/test", dependencies=[Depends(require_csrf)])
def test_email(
    body: TestEmail, user: User = Depends(current_user), db: Session = Depends(get_db)
) -> dict[str, str]:
    _require_owner_somewhere(db, user)
    try:
        mailer.send_for(
            db, body.to, "Smart home: test email", "The email server works."
        )
    except (mailer.MailError, VaultError) as error:
        raise HTTPException(502, str(error)) from None
    return {"status": "sent"}


@public_router.post("/recover/email")
def email_recovery_code(
    body: EmailRecovery, request: Request, db: Session = Depends(get_db)
) -> dict[str, bool]:
    """Email a one-time code to the account's address. The answer is the same
    whether or not the account exists."""
    ip = client_ip(request)
    login = body.login.strip().lower()
    _limit(login)
    row = settings(db)
    if not (row.allow_recovery and mailer.configured(row)):
        raise HTTPException(404, "Recovery by email is not set up")
    user = db.scalars(select(User).where(func.lower(User.email) == login)).first()
    if user is not None and user.is_active and "@" in user.email:
        raw = "".join(secrets.choice(_ALPHABET) for _ in range(16))
        code = "-".join(raw[i : i + 4] for i in range(0, 16, 4))
        db.add(
            PasswordReset(
                user_id=user.id,
                code_hash=_hash(code),
                created_by=user.id,
                expires_at=datetime.now(UTC) + RESET_LIFETIME,
            )
        )
        db.commit()
        try:
            mailer.send_for(
                db,
                user.email,
                "Smart home: your recovery code",
                f"Your recovery code is {code}\n\nIt works once, for one hour. "
                "If you did not ask for it, ignore this email.",
            )
        except (mailer.MailError, VaultError):
            pass  # the answer stays the same; the admin can test the server
        record_event(db, "recovery_code_emailed", user_id=user.id, ip_address=ip)
    return {"sent": True}
