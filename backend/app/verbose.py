"""Verbose logging (Settings > Activity log, admins; off by default).

While it is on, the activity log also records integration detail, all as
event types starting with "verbose_":
  verbose_request         every change request (not page reads): who,
                          method, path, result status and time taken
  verbose_vendor_command  each command sent to a device's vendor (Cync,
                          Rheem, Samsung): result and time taken
  verbose_refresh         each background read of an integration: whether it
                          ran, why it was skipped or failed, time taken
  verbose_device_online / verbose_device_offline
                          a device's connection changing, from any source
Nothing secret is recorded: no request bodies, query strings or headers, and
details still pass through the audit redaction (SEC-32).
"""

import asyncio
import json
import re
import time
from typing import Any

from sqlalchemy import event, inspect, select
from sqlalchemy.orm import Session
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.audit import record_event
from app.db_config import SessionLocal
from app.models import AuditEvent, Device, Home, SystemSettings
from app.models import Session as SessionModel
from app.sessions import SESSION_COOKIE, hash_token

_HOME = re.compile(r"^/api/v1/homes/([0-9a-fA-F-]{36})(/|$)")


def enabled(db: Session) -> bool:
    with db.no_autoflush:
        row = db.get(SystemSettings, 1)
    return bool(row and row.verbose_logging)


def note(
    db: Session,
    event_type: str,
    *,
    home_id: str | None = None,
    user_id: str | None = None,
    details: dict[str, Any] | None = None,
) -> None:
    """Record a verbose_ event if verbose logging is on (commits)."""
    if enabled(db):
        record_event(
            db,
            f"verbose_{event_type}",
            home_id=home_id,
            user_id=user_id,
            details=details,
        )


def note_apart(
    event_type: str,
    *,
    home_id: str | None = None,
    details: dict[str, Any] | None = None,
) -> None:
    """note() in a session of its own, so the caller's transaction is left
    alone (nothing of theirs is committed or rolled back)."""
    with SessionLocal() as db:
        note(db, event_type, home_id=home_id, details=details)


def ms_since(start: float) -> int:
    return int((time.monotonic() - start) * 1000)


@event.listens_for(Session, "before_flush")
def _online_changes(db: Session, _context: Any, _instances: Any) -> None:
    """A device's online flag changed (refresh, live updates, sync)."""
    changed = []
    for obj in db.dirty:
        if not isinstance(obj, Device):
            continue
        history = inspect(obj).attrs.online.history
        if history.added and history.deleted and history.added[0] != history.deleted[0]:
            changed.append(obj)
    if not changed or not enabled(db):
        return
    for device in changed:
        db.add(
            AuditEvent(
                event_type="verbose_device_online"
                if device.online
                else "verbose_device_offline",
                home_id=device.home_id,
                details=json.dumps(
                    {"device": device.name, "integration": device.integration}
                ),
            )
        )


class VerboseRequestMiddleware:
    """Records each change request (POST, PUT, PATCH, DELETE under /api/)
    while verbose logging is on. Pure ASGI: the response is not buffered."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if (
            scope["type"] != "http"
            or scope.get("method") in ("GET", "HEAD", "OPTIONS")
            or not str(scope.get("path", "")).startswith("/api/")
        ):
            await self.app(scope, receive, send)
            return
        start = time.monotonic()
        status: dict[str, int] = {}

        async def watch(message: Message) -> None:
            if message["type"] == "http.response.start":
                status["code"] = int(message["status"])
            await send(message)

        try:
            await self.app(scope, receive, watch)
        finally:
            client = scope.get("client")
            await asyncio.to_thread(
                _record_request,
                str(scope.get("method")),
                str(scope.get("path", "")),
                status.get("code", 500),
                ms_since(start),
                client[0] if client else None,
                _session_token(scope),
            )


def _session_token(scope: Scope) -> str | None:
    """The session cookie, only to name who made the request."""
    for name, value in scope.get("headers", []):
        if name == b"cookie":
            for part in value.decode("latin-1").split(";"):
                key, _, token = part.strip().partition("=")
                if key == SESSION_COOKIE and token:
                    return token
    return None


def _record_request(
    method: str, path: str, status: int, ms: int, ip: str | None, token: str | None
) -> None:
    with SessionLocal() as db:
        if not enabled(db):
            return
        match = _HOME.match(path)
        home_id = match.group(1) if match else None
        if home_id is not None and db.get(Home, home_id) is None:
            home_id = None
        session = (
            db.scalars(
                select(SessionModel.user_id).where(
                    SessionModel.hash_token == hash_token(token)
                )
            ).first()
            if token
            else None
        )
        record_event(
            db,
            "verbose_request",
            home_id=home_id,
            user_id=session,
            ip_address=ip,
            details={"method": method, "path": path[:200], "status": status, "ms": ms},
        )
