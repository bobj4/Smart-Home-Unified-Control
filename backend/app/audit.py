"""Audit log writer (SEC-80). Secrets never reach the log (SEC-32)."""

import json
from typing import Any

from sqlalchemy.orm import Session

from app.models import AuditEvent

# A key containing any of these words is redacted, at any depth.
_SENSITIVE_WORDS = (
    "password",
    "token",
    "secret",
    "totp",
    "recovery",
    "csrf",
    "session",
    "key",
    "code",
    "credential",
)


def redact(value: Any) -> Any:
    """Return a copy with sensitive keys replaced by "[REDACTED]"."""
    if isinstance(value, dict):
        return {
            k: "[REDACTED]"
            if any(w in str(k).lower() for w in _SENSITIVE_WORDS)
            else redact(v)
            for k, v in value.items()
        }
    if isinstance(value, list | tuple):
        return [redact(v) for v in value]
    return value


def record_event(
    db: Session,
    event_type: str,
    *,
    user_id: str | None = None,
    home_id: str | None = None,
    ip_address: str | None = None,
    details: dict[str, Any] | None = None,
) -> None:
    """Write one audit row and commit it."""
    db.add(
        AuditEvent(
            event_type=event_type,
            user_id=user_id,
            home_id=home_id,
            ip_address=ip_address,
            details=json.dumps(redact(details or {}), default=str),
        )
    )
    db.commit()
