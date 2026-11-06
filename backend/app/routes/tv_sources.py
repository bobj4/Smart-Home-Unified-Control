"""SmartThings for Samsung TVs: connect a token (operators and up), link each
TV, and read a TV's inputs by name (anyone who uses the TV)."""

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from app.audit import record_event
from app.authorization import require_role
from app.db_config import get_db
from app.dependencies import client_ip, current_user, require_csrf
from app.models import Role, User
from app.routes.samsung import _tv
from app.samsung_home import list_tvs
from app.tv_sources import (
    SourcesUnavailable,
    connect,
    connected,
    disconnect,
    link,
    linked_id,
    smartthings_tvs,
    tv_sources,
)

router = APIRouter(
    prefix="/api/v1/homes/{home_id}/integrations/samsung_tv", tags=["samsung"]
)


class TokenIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    token: str = Field(min_length=10, max_length=200, pattern=r"^[A-Za-z0-9-]+$")


class LinkIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    smartthings_id: str | None = Field(
        default=None, max_length=64, pattern=r"^[A-Za-z0-9-]+$"
    )


def _audit(db: Session, request: Request, user: User, home_id: str, event: str) -> None:
    record_event(
        db,
        event,
        user_id=user.id,
        home_id=home_id,
        ip_address=client_ip(request),
        details={"integration": "smartthings"},
    )


def _run(action: Any) -> Any:
    try:
        return action()
    except SourcesUnavailable as error:
        raise HTTPException(error.status_code, error.reason) from None


@router.get("/smartthings")
def get_smartthings(
    home_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)
) -> dict[str, Any]:
    """Whether SmartThings is connected, its TVs when it is, and which
    SmartThings TV each of the home's TVs is linked to."""
    require_role(db, user.id, home_id, Role.OPERATOR)
    links = {d.id: linked_id(d) for d in list_tvs(db, home_id)}
    if not connected(db, home_id):
        return {"connected": False, "tvs": [], "links": links}
    found = _run(lambda: smartthings_tvs(db, home_id))
    return {"connected": True, "tvs": found, "links": links}


@router.put("/smartthings", dependencies=[Depends(require_csrf)])
def put_smartthings(
    home_id: str,
    body: TokenIn,
    request: Request,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    require_role(db, user.id, home_id, Role.OPERATOR)
    found = _run(lambda: connect(db, home_id, body.token))
    _audit(db, request, user, home_id, "smartthings_connected")
    links = {d.id: linked_id(d) for d in list_tvs(db, home_id)}
    return {"connected": True, "tvs": found, "links": links}


@router.delete("/smartthings", dependencies=[Depends(require_csrf)])
def delete_smartthings(
    home_id: str,
    request: Request,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    require_role(db, user.id, home_id, Role.OPERATOR)
    disconnect(db, home_id)
    _audit(db, request, user, home_id, "smartthings_disconnected")
    links = {d.id: linked_id(d) for d in list_tvs(db, home_id)}
    return {"connected": False, "tvs": [], "links": links}


@router.put("/tvs/{device_id}/smartthings", dependencies=[Depends(require_csrf)])
def put_link(
    home_id: str,
    device_id: str,
    body: LinkIn,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    require_role(db, user.id, home_id, Role.OPERATOR)
    device = _tv(db, home_id, device_id)
    link(db, device, body.smartthings_id)
    return {"device_id": device.id, "smartthings_id": linked_id(device)}


@router.get("/tvs/{device_id}/sources")
def get_sources(
    home_id: str,
    device_id: str,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """The TV's inputs by name and the current one."""
    require_role(db, user.id, home_id, Role.MEMBER)
    device = _tv(db, home_id, device_id)
    return dict(_run(lambda: tv_sources(db, device)))
