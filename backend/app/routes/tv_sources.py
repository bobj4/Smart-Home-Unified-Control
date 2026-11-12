"""SmartThings for Samsung TVs: connect it (operators and up) by signing in
(OAuth, renews itself) or with a 24-hour token, link each TV, and read a TV's
inputs by name (anyone who uses the TV). The sign-in comes back to
/api/v1/smartthings/callback (routes/smartthings_callback.py)."""

from typing import Any
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from app.audit import record_event
from app.authorization import require_role
from app.db_config import get_db
from app.dependencies import client_ip, current_user, require_csrf
from app.models import Role, User
from app.routes.samsung import _tv
from app.samsung_home import list_tvs
from app.smartthings_oauth import CALLBACK, OAuthProblem, finish, start, status
from app.tv_sources import (
    SourcesUnavailable,
    connect,
    connected,
    disconnect,
    link,
    linked_id,
    saved_login,
    smartthings_tvs,
    tv_sources,
)

router = APIRouter(
    prefix="/api/v1/homes/{home_id}/integrations/samsung_tv", tags=["samsung"]
)
# Where SmartThings sends the person back after signing in (no home in the
# address: it is the one registered in the SmartApp).
callback_router = APIRouter(tags=["samsung"])


class TokenIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    token: str = Field(min_length=10, max_length=200, pattern=r"^[A-Za-z0-9-]+$")


class OAuthIn(BaseModel):
    """The SmartApp made for this server (client ID and secret), and where
    SmartThings sends the person back (this server's callback address).
    Empty ID and secret: sign in again with the saved ones."""

    model_config = ConfigDict(extra="forbid")
    client_id: str = Field(default="", max_length=100, pattern=r"^[A-Za-z0-9-]*$")
    client_secret: str = Field(default="", max_length=200, pattern=r"^[A-Za-z0-9-]*$")
    redirect_uri: str = Field(min_length=10, max_length=300)


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
    how = status(saved_login(db, home_id))
    if how["problem"]:  # a sign-in that must be done again: no TVs to list
        return {"connected": True, "tvs": [], "links": links, **how}
    found = _run(lambda: smartthings_tvs(db, home_id))
    return {"connected": True, "tvs": found, "links": links, **how}


@router.post("/smartthings/oauth", dependencies=[Depends(require_csrf)])
def start_oauth(
    home_id: str,
    body: OAuthIn,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> dict[str, str]:
    """Where to send the person to sign in to SmartThings."""
    require_role(db, user.id, home_id, Role.OPERATOR)
    if not body.redirect_uri.endswith(CALLBACK):
        raise HTTPException(422, f"the redirect address must end in {CALLBACK}")
    app = {
        "client_id": body.client_id,
        "client_secret": body.client_secret,
        "redirect_uri": body.redirect_uri,
    }
    if not app["client_id"] or not app["client_secret"]:
        saved = saved_login(db, home_id) or {}
        if not saved.get("oauth"):
            raise HTTPException(422, "enter the SmartApp's client ID and secret")
        app = {
            **app,
            "client_id": saved["client_id"],
            "client_secret": saved["client_secret"],
        }
    try:
        url = start(home_id, user.id, app)
    except OAuthProblem as problem:
        raise HTTPException(problem.status_code, problem.reason) from None
    return {"authorize_url": url}


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


@callback_router.get(CALLBACK)
def oauth_callback(
    request: Request,
    code: str = Query(default="", max_length=200),
    state: str = Query(default="", max_length=100),
    error: str = Query(default="", max_length=100),
    db: Session = Depends(get_db),
) -> RedirectResponse:
    """Finish the sign-in, then back to Settings > Integrations with how it
    went (?smartthings=connected, or ?smartthings_error=<why>). No login
    here: see smartthings_oauth.finish."""
    back = "#settings/integrations"
    if error or not code or not state:
        why = (
            "SmartThings was not allowed" if error else "SmartThings sent nothing back"
        )
        return RedirectResponse(f"/?{urlencode({'smartthings_error': why})}{back}", 303)
    try:
        home_id, user_id = finish(db, state, code)
    except OAuthProblem as problem:
        query = urlencode({"smartthings_error": problem.reason})
        return RedirectResponse(f"/?{query}{back}", 303)
    record_event(
        db,
        "smartthings_connected",
        user_id=user_id,
        home_id=home_id,
        ip_address=client_ip(request),
        details={"integration": "smartthings", "method": "oauth"},
    )
    return RedirectResponse(f"/?smartthings=connected{back}", 303)
