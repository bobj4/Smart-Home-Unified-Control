"""Settings > Admin > HTTPS: the certificate and the HTTPS switch.

Owner of any home only (like the login rules). A change takes effect when
the server is restarted with scripts/serve.py.
"""

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
# Left in the data folder when the toggle is switched on; on the server,
# smarthome-cert.path sees it and runs the import at once (then removes it).
REQUEST_FILE = "cert-import-requested"


def request_import() -> None:
    try:
        folder = database_path().parent
        (folder / REQUEST_FILE).write_text("requested\n", encoding="utf-8")
    except (BackupError, OSError):
        pass  # not SQLite, or not writable: the 6-hourly check still runs


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
    return {
        "on": bool(row.cert_auto_import),
        "source": row.cert_import_source,
        "imported_at": row.cert_imported_at.isoformat()
        if row.cert_imported_at
        else None,
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
