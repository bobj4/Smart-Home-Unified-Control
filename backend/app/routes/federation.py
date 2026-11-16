"""Homes at other sites, main server side (see app/federation.py).

  GET    /api/v1/homes/{id}/site            the link's state (admins)
  POST   /api/v1/homes/{id}/site/pairing    a pairing code (admins)
  DELETE /api/v1/homes/{id}/site            unlink (admins)
  POST   /api/v1/federation/pair            a site server uses a code
  WS     /api/v1/federation/connect         a site server stays connected

and on a site's own server (app/federation_site.py), admins:

  GET    /api/v1/homes/{id}/main-server     linked to a main server?
  POST   /api/v1/homes/{id}/main-server     link with its address and a code
  DELETE /api/v1/homes/{id}/main-server     unlink

and SiteForwarding, the middleware that sends a linked home's per-home
requests to its site.
"""

import re
from typing import Any

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Request,
    WebSocket,
    WebSocketDisconnect,
    status,
)
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import JSONResponse, Response

from app import federation, federation_guest, federation_site
from app.audit import record_event
from app.authorization import require_role
from app.db_config import SessionLocal, get_db
from app.dependencies import client_ip, current_user, require_csrf
from app.guest_access import require_guest
from app.models import GUEST_ROLE, Home, HomeMembership, Role, User
from app.sessions import CSRF_HEADER, SESSION_COOKIE, get_valid_session

router = APIRouter(tags=["sites"])
PER_HOME = re.compile(r"^/api/v1/homes/([^/]+)/([^/]+)(/.*)?$")
SAFE = {"GET", "HEAD", "OPTIONS"}


def _home(db: Session, user: User, home_id: str) -> Home:
    require_role(db, user.id, home_id, Role.ADMIN)
    home = db.get(Home, home_id)
    if home is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found")
    return home


@router.get("/api/v1/homes/{home_id}/site")
def site_status(
    home_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)
) -> dict[str, Any]:
    return federation.status(_home(db, user, home_id))


@router.post(
    "/api/v1/homes/{home_id}/site/pairing", dependencies=[Depends(require_csrf)]
)
def site_pairing(
    home_id: str,
    request: Request,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    home = _home(db, user, home_id)
    code = federation.new_pairing(db, home)
    record_event(
        db,
        "site_pairing_started",
        user_id=user.id,
        home_id=home_id,
        ip_address=client_ip(request),
    )
    return {
        "code": code,
        "minutes": federation.PAIRING_SECONDS // 60,
        **federation.status(home),
    }


@router.delete("/api/v1/homes/{home_id}/site", dependencies=[Depends(require_csrf)])
def site_unlink(
    home_id: str,
    request: Request,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    home = _home(db, user, home_id)
    federation.unlink(db, home)
    record_event(
        db,
        "site_unlinked",
        user_id=user.id,
        home_id=home_id,
        ip_address=client_ip(request),
    )
    return federation.status(home)


class PairIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    code: str = Field(min_length=6, max_length=20)
    site_home_id: str = Field(min_length=1, max_length=36)
    site_name: str = Field(default="", max_length=100)


@router.post("/api/v1/federation/pair")
def pair_site(
    body: PairIn, request: Request, db: Session = Depends(get_db)
) -> dict[str, str]:
    """A site server with a pairing code gets the token it connects with.
    No login: the code (random, half an hour, once) is the permission."""
    try:
        home, token = federation.pair(
            db, body.code, body.site_home_id, body.site_name.strip() or "Site"
        )
    except LookupError as error:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(error)) from None
    record_event(
        db,
        "site_linked",
        home_id=home.id,
        ip_address=client_ip(request),
        details={"site": home.site_name},
    )
    return {"token": token, "home_id": home.id, "home_name": home.name}


@router.websocket("/api/v1/federation/connect")
async def site_connect(websocket: WebSocket) -> None:
    token = websocket.headers.get("authorization", "").removeprefix("Bearer ").strip()
    with SessionLocal() as db:
        home = federation.home_for_token(db, token)
        home_id = home.id if home else None
    if home_id is None:
        await websocket.close(code=4401)
        return
    await websocket.accept()
    link = federation.Link(websocket.send_text)
    federation.connected(home_id, link)
    try:
        while True:
            federation.answered(link, await websocket.receive_text())
    except WebSocketDisconnect:
        pass
    finally:
        federation.disconnected(home_id, link)


def _deny(code: int, detail: str) -> Response:
    return JSONResponse({"detail": detail}, status_code=code)


class SiteForwarding(BaseHTTPMiddleware):
    """Per-home requests for a home whose devices are at another site go to
    that site, after the login, role and CSRF checks here."""

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        match = PER_HOME.match(request.url.path)
        part = match.group(2) if match else None
        if match is None or (part not in federation.FORWARDED and part != "guest"):
            return await call_next(request)
        home_id = match.group(1)
        access = None
        with SessionLocal() as db:
            site_home = federation.remote_homes(db).get(home_id)
            if site_home is None:
                return await call_next(request)
            session = get_valid_session(db, request.cookies.get(SESSION_COOKIE))
            if session is None:
                return _deny(401, "Not authenticated")
            member = (
                db.query(HomeMembership)
                .filter_by(user_id=session.user_id, home_id=home_id)
                .first()
            )
            csrf = session.csrf_token
            user_id = session.user_id
            role = member.role if member else None
            if role == GUEST_ROLE:
                user = db.get(User, user_id)
                try:
                    access = require_guest(db, user, home_id) if user else None
                except HTTPException as refused:
                    return _deny(refused.status_code, str(refused.detail))
                if access is not None and access in db:  # a saved one: keep it
                    db.expunge(access)
        if role is None:
            return _deny(404, "Not found")
        if request.method not in SAFE and request.headers.get(CSRF_HEADER) != csrf:
            return _deny(403, "CSRF check failed")
        if role == GUEST_ROLE:
            # The guest's permissions are here: applied here (federation_guest).
            if access is None:
                return _deny(403, "Forbidden")
            if part == "guest":
                try:
                    return await federation_guest.handle(
                        request, home_id, site_home, match.group(3) or "", access
                    )
                except federation.SiteOffline as offline:
                    return _deny(503, str(offline))
            if part == "cameras" and request.method in SAFE and access.cameras:
                role = Role.OPERATOR.value  # a guest allowed to watch the cameras
            else:
                return _deny(403, "Forbidden")
        elif part == "guest":
            return _deny(403, "Forbidden")
        body = await request.body()
        if len(body) > federation.MAX_BODY:
            return _deny(413, "Too large")
        path = f"/api/v1/homes/{site_home}/{match.group(2)}{match.group(3) or ''}"
        try:
            answer = await federation.forward(
                home_id,
                {
                    "method": request.method,
                    "path": path,
                    "query": request.url.query,
                    "body": body.decode("utf-8", "replace"),
                    "role": role,
                },
            )
        except federation.SiteOffline as offline:
            return _deny(503, str(offline))
        if request.method not in SAFE:
            with SessionLocal() as db:
                record_event(
                    db,
                    "site_request",
                    user_id=user_id,
                    home_id=home_id,
                    ip_address=client_ip(request),
                    details={
                        "method": request.method,
                        "part": match.group(2),
                        "status": answer.get("status"),
                    },
                )
        return Response(
            content=str(answer.get("body") or ""),
            status_code=int(answer.get("status") or 502),
            media_type=str(answer.get("content_type") or "application/json"),
        )


# ------------------------------------------------------------ on a site's server


class MainServerIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    main_url: str = Field(min_length=10, max_length=300)
    code: str = Field(min_length=6, max_length=20)


def _run(action: Any) -> Any:
    try:
        return action()
    except federation_site.LinkProblem as problem:
        raise HTTPException(problem.status_code, problem.reason) from None


@router.get("/api/v1/homes/{home_id}/main-server")
def main_server_status(
    home_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)
) -> dict[str, Any]:
    _home(db, user, home_id)
    return federation_site.status(db, home_id)


@router.post(
    "/api/v1/homes/{home_id}/main-server", dependencies=[Depends(require_csrf)]
)
def main_server_link(
    home_id: str,
    body: MainServerIn,
    request: Request,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    home = _home(db, user, home_id)
    if home.site_token_hash:
        raise HTTPException(409, "this home's devices are at another site already")
    linked = _run(
        lambda: federation_site.link(db, home_id, body.main_url, body.code, home.name)
    )
    record_event(
        db,
        "main_server_linked",
        user_id=user.id,
        home_id=home_id,
        ip_address=client_ip(request),
        details={"main_url": linked["main_url"]},
    )
    return dict(linked)


@router.delete(
    "/api/v1/homes/{home_id}/main-server", dependencies=[Depends(require_csrf)]
)
def main_server_unlink(
    home_id: str,
    request: Request,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    _home(db, user, home_id)
    federation_site.unlink(db, home_id)
    record_event(
        db,
        "main_server_unlinked",
        user_id=user.id,
        home_id=home_id,
        ip_address=client_ip(request),
    )
    return federation_site.status(db, home_id)
