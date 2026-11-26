"""Google Nest (Device Access) for one home: the project and OAuth client,
signing in (Google's page; the person pastes back the address it lands
on), and finding the devices. See app/nest_home.py and docs/NEST.md."""

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from app import credentials, integration_status, nest_home
from app.audit import record_event
from app.authorization import require_role
from app.db_config import get_db
from app.dependencies import client_ip, current_user, require_csrf
from app.models import Role, User

router = APIRouter(
    prefix="/api/v1/homes/{home_id}/integrations/google_nest", tags=["nest"]
)


class App(BaseModel):
    model_config = ConfigDict(extra="forbid")
    project_id: str = Field(min_length=8, max_length=64, pattern=r"^[A-Za-z0-9-]+$")
    client_id: str = Field(min_length=10, max_length=200, pattern=r"^[A-Za-z0-9.\-_]+$")
    client_secret: str = Field(default="", max_length=200)
    subscription: str = Field(
        default="",
        max_length=300,
        pattern=r"^$|^projects/[a-z][a-z0-9-]{4,61}[a-z0-9]/subscriptions/[A-Za-z][A-Za-z0-9._~%+-]{2,254}$",
    )


class Finish(BaseModel):
    model_config = ConfigDict(extra="forbid")
    address: str = Field(min_length=4, max_length=4000)


def _problem(error: nest_home.NestUnavailable) -> HTTPException:
    return HTTPException(error.status_code, error.reason)


@router.get("/account")
def get_nest(
    home_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)
) -> dict[str, Any]:
    require_role(db, user.id, home_id, Role.OPERATOR)
    try:
        return nest_home.status(db, home_id)
    except nest_home.NestUnavailable as error:
        raise _problem(error) from None


@router.put("/account", dependencies=[Depends(require_csrf)])
def start_sign_in(
    home_id: str,
    body: App,
    request: Request,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Keep the project and OAuth client; returns Google's sign-in page."""
    require_role(db, user.id, home_id, Role.ADMIN)
    try:
        url = nest_home.start(db, home_id, body.model_dump())
    except nest_home.NestUnavailable as error:
        raise _problem(error) from None
    record_event(
        db,
        "integration_account_saved",
        user_id=user.id,
        home_id=home_id,
        ip_address=client_ip(request),
        details={"integration": nest_home.INTEGRATION, "project_id": body.project_id},
    )
    return {**nest_home.status(db, home_id), "authorize_url": url}


@router.post("/finish", dependencies=[Depends(require_csrf)])
def finish_sign_in(
    home_id: str,
    body: Finish,
    request: Request,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """The address Google sent the person to: signs in and finds the devices."""
    require_role(db, user.id, home_id, Role.ADMIN)
    try:
        found = nest_home.finish(db, home_id, body.address)
    except nest_home.NestUnavailable as error:
        raise _problem(error) from None
    record_event(
        db,
        "nest_signed_in",
        user_id=user.id,
        home_id=home_id,
        ip_address=client_ip(request),
        details=found,
    )
    return {**nest_home.status(db, home_id), **found}


@router.post("/sync", dependencies=[Depends(require_csrf)])
def sync_devices(
    home_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)
) -> dict[str, Any]:
    require_role(db, user.id, home_id, Role.OPERATOR)
    try:
        found = nest_home.sync(db, home_id)
    except nest_home.NestUnavailable as error:
        integration_status.failed(home_id, nest_home.INTEGRATION, error.reason)
        raise _problem(error) from None
    integration_status.worked(home_id, nest_home.INTEGRATION)
    return found


@router.delete("/account", dependencies=[Depends(require_csrf)])
def disconnect(
    home_id: str,
    request: Request,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Forget the sign-in and the client (the devices stay until removed)."""
    require_role(db, user.id, home_id, Role.ADMIN)
    credentials.remove(db, home_id, nest_home.INTEGRATION)
    record_event(
        db,
        "integration_account_removed",
        user_id=user.id,
        home_id=home_id,
        ip_address=client_ip(request),
        details={"integration": nest_home.INTEGRATION},
    )
    return nest_home.status(db, home_id)
