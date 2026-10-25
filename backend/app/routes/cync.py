"""GE Cync account (owner) and light and plug discovery (admin) for a home."""

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from app import credentials, integration_status
from app.audit import record_event
from app.authorization import require_role
from app.cync_home import INTEGRATION, CyncUnavailable, log_in, sync
from app.db_config import get_db
from app.dependencies import client_ip, current_user, require_csrf
from app.models import Role, User

router = APIRouter(prefix="/api/v1/homes/{home_id}/integrations/cync", tags=["cync"])


class Login(BaseModel):
    model_config = ConfigDict(extra="forbid")
    email: str = Field(min_length=3, max_length=255, pattern=r"^[^@\s]+@[^@\s]+$")
    password: str = Field(min_length=1, max_length=1024)
    code: str | None = Field(default=None, pattern=r"^\d{4,8}$")


def _account_out(db: Session, home_id: str) -> dict[str, Any]:
    email = credentials.label(db, home_id, INTEGRATION)
    return {"configured": email is not None, "email": email}


def _audit(
    db: Session, request: Request, user: User, home_id: str, event: str, **details: Any
) -> None:
    record_event(
        db,
        event,
        user_id=user.id,
        home_id=home_id,
        ip_address=client_ip(request),
        details={"integration": INTEGRATION, **details},
    )


@router.get("/account")
def get_account(
    home_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)
) -> dict[str, Any]:
    require_role(db, user.id, home_id, Role.ADMIN)
    return _account_out(db, home_id)


@router.put("/account", dependencies=[Depends(require_csrf)])
def save_account(
    home_id: str,
    body: Login,
    request: Request,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Log in to Cync. Without a code Cync usually emails one first
    ("code_sent"); send the same email and password again with the code."""
    require_role(db, user.id, home_id, Role.ADMIN)
    email = body.email.strip()
    try:
        saved = log_in(db, home_id, email, body.password, body.code)
    except CyncUnavailable as error:
        _audit(db, request, user, home_id, "integration_login_failed", email=email)
        raise HTTPException(error.status_code, error.reason) from None
    if not saved:
        return {**_account_out(db, home_id), "code_sent": True}
    _audit(db, request, user, home_id, "integration_account_saved", email=email)
    integration_status.worked(home_id, INTEGRATION)  # a new login that works
    return {**_account_out(db, home_id), "code_sent": False}


@router.delete("/account", dependencies=[Depends(require_csrf)])
def remove_account(
    home_id: str,
    request: Request,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    require_role(db, user.id, home_id, Role.ADMIN)
    integration_status.worked(home_id, INTEGRATION)
    if credentials.remove(db, home_id, INTEGRATION):
        _audit(db, request, user, home_id, "integration_account_removed")
    return _account_out(db, home_id)


@router.post("/sync", dependencies=[Depends(require_csrf)])
def sync_devices(
    home_id: str,
    request: Request,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> dict[str, int]:
    """Find the account's lights and plugs."""
    require_role(db, user.id, home_id, Role.OPERATOR)
    try:
        result = sync(db, home_id)
    except CyncUnavailable as error:
        _audit(
            db, request, user, home_id, "integration_sync_failed", reason=error.reason
        )
        raise HTTPException(error.status_code, error.reason) from None
    _audit(db, request, user, home_id, "integration_synced", **result)
    return result
