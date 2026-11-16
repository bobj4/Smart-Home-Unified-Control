"""Settings > Admin > HTTPS: the certificate and the HTTPS switch.

Owner of any home only (like the login rules). A change takes effect when
the server is restarted with scripts/serve.py.
"""

import os
import signal
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, StrictBool
from sqlalchemy.orm import Session

from app import tls
from app.audit import record_event
from app.backup import BackupError, database_path
from app.db_config import get_db
from app.dependencies import client_ip, current_user, require_csrf
from app.login_policy import settings
from app.models import User
from app.routes.admin import _require_owner_somewhere
from app.vault import VaultError

router = APIRouter(prefix="/api/v1/admin/https", tags=["admin"])
# Left in the data folder when the toggle is switched on (or "Fetch now");
# on the server, smarthome-cert.path sees it and runs the import at once,
# which writes its outcome to RESULT_FILE ("status\nmessage") and removes
# the request. The app shows the outcome in a popup.
REQUEST_FILE = "cert-import-requested"
RESULT_FILE = "cert-import-result"
RESULTS = ("changed", "same", "off", "not_found", "refused")


def _data_folder() -> Path | None:
    try:
        return database_path().parent
    except BackupError:
        return None  # not SQLite: no shared folder with the server


def request_import() -> bool:
    """Ask the server to import now. False if the request could not be left
    (the 6-hourly check still runs)."""
    folder = _data_folder()
    if folder is None:
        return False
    try:
        (folder / RESULT_FILE).unlink(missing_ok=True)
        (folder / REQUEST_FILE).write_text("requested\n", encoding="utf-8")
    except OSError:
        return False
    return True


def _last_check(folder: Path) -> dict[str, str] | None:
    path = folder / RESULT_FILE
    try:
        text = path.read_text(encoding="utf-8", errors="replace")[:2000]
        at = datetime.fromtimestamp(path.stat().st_mtime, UTC)
    except OSError:
        return None
    status, _, message = text.partition("\n")
    status = status.strip()
    return {
        "status": status if status in RESULTS else "unknown",
        "message": message.strip()[:500],
        "at": at.isoformat(),
    }


class Certificate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    certificate: str = Field(min_length=1, max_length=tls.MAX_CERTIFICATE_CHARS)
    private_key: str = Field(min_length=1, max_length=tls.MAX_KEY_CHARS)


class Switch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    enabled: StrictBool


def _out(db: Session, request: Request) -> dict[str, Any]:
    row = settings(db)
    active = request.url.scheme == "https"
    return {
        "enabled": row.https_enabled,
        "active": active,
        "restart_needed": row.https_enabled != active,
        "certificate": tls.describe(row.tls_certificate)
        if row.tls_certificate
        else None,
    }


def _auto(db: Session) -> dict[str, Any]:
    row = settings(db)
    folder = _data_folder()
    return {
        "on": bool(row.cert_auto_import),
        "source": row.cert_import_source,
        "imported_at": row.cert_imported_at.isoformat()
        if row.cert_imported_at
        else None,
        # Waiting for the server to take the request, and its last answer.
        "pending": bool(folder and (folder / REQUEST_FILE).exists()),
        "last_check": _last_check(folder) if folder else None,
    }


@router.get("/auto-import")
def get_auto_import(
    user: User = Depends(current_user), db: Session = Depends(get_db)
) -> dict[str, Any]:
    _require_owner_somewhere(db, user)
    return _auto(db)


@router.get("")
def get_https(
    request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)
) -> dict[str, Any]:
    _require_owner_somewhere(db, user)
    return _out(db, request)


@router.put("/certificate", dependencies=[Depends(require_csrf)])
def save_certificate(
    body: Certificate,
    request: Request,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    _require_owner_somewhere(db, user)
    try:
        tls.save(db, body.certificate, body.private_key)
    except tls.TlsError as error:
        raise HTTPException(status_code=422, detail=str(error)) from None
    except VaultError as error:
        raise HTTPException(status_code=409, detail=str(error)) from None
    db.commit()
    out = _out(db, request)
    cert = out["certificate"]
    record_event(
        db,
        "https_certificate_saved",
        user_id=user.id,
        ip_address=client_ip(request),
        details={"subject": cert["subject"], "not_after": cert["not_after"]},
    )
    return out


@router.delete("/certificate", dependencies=[Depends(require_csrf)])
def delete_certificate(
    request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)
) -> dict[str, Any]:
    _require_owner_somewhere(db, user)
    tls.remove(db)
    db.commit()
    record_event(
        db, "https_certificate_removed", user_id=user.id, ip_address=client_ip(request)
    )
    return _out(db, request)


@router.put("/auto-import", dependencies=[Depends(require_csrf)])
def switch_auto_import(
    body: Switch,
    request: Request,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Take the certificate from this server's web server (deploy/linux/smarthome
    cert-import does the reading, on the server, while this is on)."""
    _require_owner_somewhere(db, user)
    settings(db).cert_auto_import = body.enabled
    db.commit()
    if body.enabled:
        request_import()
    record_event(
        db,
        "https_auto_import_switched",
        user_id=user.id,
        ip_address=client_ip(request),
        details={"enabled": body.enabled},
    )
    return _auto(db)


@router.post("/auto-import/request", dependencies=[Depends(require_csrf)])
def request_auto_import(
    user: User = Depends(current_user), db: Session = Depends(get_db)
) -> dict[str, Any]:
    """Fetch now: ask the server to import the certificate at once."""
    _require_owner_somewhere(db, user)
    if not settings(db).cert_auto_import:
        raise HTTPException(status_code=409, detail="Switch it on first.")
    request_import()
    return _auto(db)


@router.put("", dependencies=[Depends(require_csrf)])
def switch_https(
    body: Switch,
    request: Request,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    _require_owner_somewhere(db, user)
    row = settings(db)
    if body.enabled and not row.tls_certificate:
        raise HTTPException(status_code=409, detail="upload a certificate first")
    row.https_enabled = body.enabled
    db.commit()
    record_event(
        db,
        "https_switched",
        user_id=user.id,
        ip_address=client_ip(request),
        details={"enabled": body.enabled},
    )
    return _out(db, request)


# ------------------------------------------------------------ restart

# Files container engines leave in a container (Docker, Podman): there,
# the restart policy starts the app again after it stops.
CONTAINER_MARKERS = ("/.dockerenv", "/run/.containerenv")


def restart_available() -> bool:
    """Whether the app is started again by itself after it stops."""
    return any(Path(marker).exists() for marker in CONTAINER_MARKERS)


def _stop_server() -> None:
    """Stop the way `docker stop` does; the restart policy starts it again."""
    os.kill(os.getpid(), signal.SIGTERM)


@router.get("/restart")
def get_restart(
    user: User = Depends(current_user), db: Session = Depends(get_db)
) -> dict[str, Any]:
    _require_owner_somewhere(db, user)
    return {"available": restart_available()}


@router.post("/restart", dependencies=[Depends(require_csrf)])
def restart_server(
    request: Request,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Restart the app so an HTTPS change takes effect (a second later, so
    this answer still reaches the browser)."""
    _require_owner_somewhere(db, user)
    if not restart_available():
        raise HTTPException(
            status_code=409,
            detail="The app cannot restart itself here: restart the server "
            "(deploy/linux/smarthome restart, or scripts/serve.py again).",
        )
    record_event(
        db,
        "server_restart_requested",
        user_id=user.id,
        ip_address=client_ip(request),
        details={"https": bool(settings(db).https_enabled)},
    )
    threading.Timer(1.0, _stop_server).start()
    return {"restarting": True, "https": bool(settings(db).https_enabled)}
