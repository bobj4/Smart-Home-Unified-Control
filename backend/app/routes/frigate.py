"""Frigate: the owner saves the server's address and login; every member
sees recent events with thumbnails and plays their clips. Media is passed
through this app, so the browser never talks to Frigate directly."""

import ipaddress
from typing import Any
from urllib.parse import urlsplit

from fastapi import (
    APIRouter,
    Depends,
    Header,
    HTTPException,
    Path,
    Query,
    Request,
    status,
)
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field, StrictBool, field_validator
from sqlalchemy.orm import Session

from app import credentials
from app.audit import record_event
from app.authorization import require_role
from app.db_config import get_db
from app.dependencies import client_ip, current_user, require_csrf
from app.frigate_home import (
    INTEGRATION,
    FrigateUnavailable,
    call,
    client_for_home,
    server_out,
)
from app.guest_access import require_camera_viewer
from app.integrations import frigate
from app.models import Role, User
from app.vault import VaultError

settings_router = APIRouter(
    prefix="/api/v1/homes/{home_id}/integrations/frigate", tags=["frigate"]
)
router = APIRouter(prefix="/api/v1/homes/{home_id}/cameras", tags=["cameras"])

EVENT_ID = Path(pattern=r"^[A-Za-z0-9._-]{1,80}$")


class Server(BaseModel):
    model_config = ConfigDict(extra="forbid")
    url: str = Field(min_length=8, max_length=200)
    username: str | None = Field(default=None, max_length=100)
    password: str | None = Field(default=None, max_length=1024)
    verify_tls: StrictBool = True

    @field_validator("url")
    @classmethod
    def local_url(cls, value: str) -> str:
        """http(s) on this machine or the home network; no paths or logins in it."""
        parts = urlsplit(value.strip())
        if parts.scheme not in ("http", "https") or not parts.hostname:
            raise ValueError(
                "The address must look like http://192.168.1.20:5000 or "
                "https://frigate.lan:8971"
            )
        if parts.username or parts.password or parts.query or parts.fragment:
            raise ValueError("Put the username and password in their own fields")
        if parts.path not in ("", "/"):
            raise ValueError(
                "The address must end at the port (no /api or anything after it)"
            )
        try:
            address = ipaddress.ip_address(parts.hostname)
        except ValueError:
            address = None  # a host name such as frigate.lan or localhost
        if address is not None and not (address.is_private or address.is_loopback):
            raise ValueError("Frigate must be on this machine or your home network")
        try:
            port = parts.port
        except ValueError:
            raise ValueError("The port is not valid") from None
        netloc = (
            f"[{parts.hostname}]"
            if address and address.version == 6
            else parts.hostname
        )
        return f"{parts.scheme}://{netloc}{f':{port}' if port else ''}"


def _fail(error: FrigateUnavailable) -> HTTPException:
    return HTTPException(error.status_code, error.reason)


# ------------------------------------------------------------ settings (owner)


@settings_router.get("/server")
def get_server(
    home_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)
) -> dict[str, Any]:
    require_role(db, user.id, home_id, Role.ADMIN)
    return server_out(db, home_id)


@settings_router.put("/server", dependencies=[Depends(require_csrf)])
def save_server(
    home_id: str,
    body: Server,
    request: Request,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Check the settings with Frigate, then store them encrypted."""
    require_role(db, user.id, home_id, Role.ADMIN)
    username = (body.username or "").strip() or None
    if username and not body.password:
        raise HTTPException(422, "enter the password for that username")
    client = frigate.connect(body.url, username, body.password, body.verify_tls)
    try:
        call(client.cameras)
    except FrigateUnavailable as error:
        if error.status_code == 404:
            # Something answered, but has no Frigate API there.
            raise HTTPException(
                400,
                "That address answered, but not as Frigate. Check the port: "
                "5000 without a login, 8971 with one.",
            ) from None
        code = 400 if "refused" in error.reason else error.status_code
        raise HTTPException(code, error.reason) from None
    data = {
        "url": body.url,
        "username": username,
        "password": body.password,
        "verify_tls": body.verify_tls,
    }
    try:
        credentials.save(db, home_id, INTEGRATION, body.url, data)
    except VaultError as error:
        raise HTTPException(status.HTTP_409_CONFLICT, str(error)) from None
    record_event(
        db,
        "integration_account_saved",
        user_id=user.id,
        home_id=home_id,
        ip_address=client_ip(request),
        details={"integration": INTEGRATION, "url": body.url, "username": username},
    )
    return server_out(db, home_id)


@settings_router.delete("/server", dependencies=[Depends(require_csrf)])
def remove_server(
    home_id: str,
    request: Request,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    require_role(db, user.id, home_id, Role.ADMIN)
    if credentials.remove(db, home_id, INTEGRATION):
        record_event(
            db,
            "integration_account_removed",
            user_id=user.id,
            home_id=home_id,
            ip_address=client_ip(request),
            details={"integration": INTEGRATION},
        )
    return server_out(db, home_id)


# ------------------------------------------------------------ viewing (members)


@router.get("")
def list_cameras(
    home_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)
) -> list[str]:
    require_camera_viewer(db, user, home_id)  # operators, or guests allowed
    try:
        client = client_for_home(db, home_id)
        result: list[str] = call(client.cameras)
    except FrigateUnavailable as error:
        raise _fail(error) from None
    return result


@router.get("/events")
def list_events(
    home_id: str,
    limit: int = Query(default=24, ge=1, le=100),
    camera: str | None = Query(default=None, pattern=r"^[A-Za-z0-9_-]{1,64}$"),
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> list[dict[str, Any]]:
    require_camera_viewer(db, user, home_id)  # operators, or guests allowed
    try:
        client = client_for_home(db, home_id)
        result: list[dict[str, Any]] = call(lambda: client.events(limit, camera))
    except FrigateUnavailable as error:
        raise _fail(error) from None
    return result


def _media(media: frigate.Media) -> StreamingResponse:
    return StreamingResponse(
        media.body,
        status_code=media.status_code,
        media_type=media.content_type,
        headers={**media.headers, "Cache-Control": "private, max-age=300"},
    )


@router.get("/events/{event_id}/thumbnail")
def event_thumbnail(
    home_id: str,
    event_id: str = EVENT_ID,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> StreamingResponse:
    require_camera_viewer(db, user, home_id)  # operators, or guests allowed
    try:
        client = client_for_home(db, home_id)
        media: frigate.Media = call(lambda: client.thumbnail(event_id))
    except FrigateUnavailable as error:
        raise _fail(error) from None
    return _media(media)


@router.get("/events/{event_id}/clip")
def event_clip(
    home_id: str,
    event_id: str = EVENT_ID,
    range_header: str | None = Header(
        default=None, alias="Range", pattern=r"^bytes=\d*-\d*$"
    ),
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> StreamingResponse:
    """The event's video, passing Range through so the player can seek."""
    require_camera_viewer(db, user, home_id)  # operators, or guests allowed
    try:
        client = client_for_home(db, home_id)
        media: frigate.Media = call(lambda: client.clip(event_id, range_header))
    except FrigateUnavailable as error:
        raise _fail(error) from None
    return _media(media)
