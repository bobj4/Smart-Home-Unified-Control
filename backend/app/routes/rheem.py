"""Rheem EcoNet account and water-heater discovery for one home."""

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import credentials, integration_status
from app.audit import record_event
from app.authorization import require_role
from app.db_config import get_db
from app.dependencies import client_ip, current_user, require_csrf
from app.integrations import rheem
from app.models import Device, Role, User
from app.rheem_home import INTEGRATION, RheemUnavailable, call, sync, usage
from app.vault import VaultError

router = APIRouter(
    prefix="/api/v1/homes/{home_id}/integrations/rheem_econet", tags=["rheem"]
)
usage_router = APIRouter(prefix="/api/v1/homes/{home_id}/devices", tags=["rheem"])


class Account(BaseModel):
    model_config = ConfigDict(extra="forbid")
    email: str = Field(min_length=3, max_length=255, pattern=r"^[^@\s]+@[^@\s]+$")
    password: str = Field(min_length=1, max_length=1024)


def _account_out(db: Session, home_id: str) -> dict[str, Any]:
    email = credentials.label(db, home_id, INTEGRATION)
    return {"configured": email is not None, "email": email}


@router.get("/account")
def get_account(
    home_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)
) -> dict[str, Any]:
    require_role(db, user.id, home_id, Role.ADMIN)
    return _account_out(db, home_id)


@router.put("/account", dependencies=[Depends(require_csrf)])
def save_account(
    home_id: str,
    body: Account,
    request: Request,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Check the login with EcoNet, then store it encrypted."""
    require_role(db, user.id, home_id, Role.ADMIN)
    email = body.email.strip()
    client = rheem.connect(email, body.password)
    try:
        call(client.list_water_heaters)
    except RheemUnavailable as error:
        code = 400 if "refused" in error.reason else error.status_code
        raise HTTPException(code, error.reason) from None
    try:
        credentials.save(
            db, home_id, INTEGRATION, email, {"email": email, "password": body.password}
        )
    except VaultError as error:
        raise HTTPException(status.HTTP_409_CONFLICT, str(error)) from None
    record_event(
        db,
        "integration_account_saved",
        user_id=user.id,
        home_id=home_id,
        ip_address=client_ip(request),
        details={"integration": INTEGRATION, "email": email},
    )
    integration_status.worked(home_id, INTEGRATION)  # a new login that works
    return _account_out(db, home_id)


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
        record_event(
            db,
            "integration_account_removed",
            user_id=user.id,
            home_id=home_id,
            ip_address=client_ip(request),
            details={"integration": INTEGRATION},
        )
    return _account_out(db, home_id)


@router.post("/sync", dependencies=[Depends(require_csrf)])
def sync_devices(
    home_id: str,
    request: Request,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> dict[str, int]:
    """Find the account's water heaters and refresh their state."""
    require_role(db, user.id, home_id, Role.OPERATOR)
    try:
        result = sync(db, home_id)
    except RheemUnavailable as error:
        record_event(
            db,
            "integration_sync_failed",
            user_id=user.id,
            home_id=home_id,
            ip_address=client_ip(request),
            details={"integration": INTEGRATION, "reason": error.reason},
        )
        raise HTTPException(error.status_code, error.reason) from None
    record_event(
        db,
        "integration_synced",
        user_id=user.id,
        home_id=home_id,
        ip_address=client_ip(request),
        details={"integration": INTEGRATION, **result},
    )
    return result


@usage_router.get("/{device_id}/usage")
def heater_usage(
    home_id: str,
    device_id: str,
    days: int = Query(1, ge=1, le=31),
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """A Rheem water heater's energy and water use, for the usage graph."""
    require_role(db, user.id, home_id)
    device = db.scalars(
        select(Device).where(Device.id == device_id, Device.home_id == home_id)
    ).first()
    if device is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found")
    if device.integration != INTEGRATION:
        raise HTTPException(409, "usage is reported by Rheem water heaters only")
    try:
        return usage(db, device, days)
    except RheemUnavailable as error:
        raise HTTPException(error.status_code, error.reason) from None
