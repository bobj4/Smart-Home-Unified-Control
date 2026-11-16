"""Homes at other sites, on the site's own server (see app/federation.py).

Admin > Home > "Link to a main server": the main server's address and a
pairing code from it. This server then keeps a connection open to the main
server (reconnecting when it drops) and answers the requests the main
server sends for this home, running each one here in-process as a "Main
server" user with the requester's role (admin, operator or member) in this
home, so this server's own rules apply too.

Saved per home, encrypted (credential "federation:main"):
{"main_url", "token", "main_home_id", "main_home_name"}.
"""

import asyncio
import json
import logging
import secrets
from typing import Any
from urllib.parse import urlparse

import aiohttp
import requests
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import credentials
from app.auth import hash_password
from app.db_config import SessionLocal
from app.models import HomeMembership, IntegrationCredential, Role, User
from app.sessions import CSRF_HEADER, SESSION_COOKIE, create_session, get_valid_session

CREDENTIAL = "federation:main"
ROLES = (Role.ADMIN.value, Role.OPERATOR.value, Role.MEMBER.value)
SERVICE_DOMAIN = "main-server.invalid"  # never a real address: nobody logs in
RETRY_SECONDS = (5, 10, 30, 60)
CHECK_SECONDS = 30
TIMEOUT_SECONDS = 15

log = logging.getLogger(__name__)


class LinkProblem(Exception):
    def __init__(self, status_code: int, reason: str) -> None:
        self.status_code = status_code
        self.reason = reason


def _clean_url(url: str) -> str:
    parsed = urlparse(url.strip().rstrip("/"))
    if parsed.scheme != "https" or not parsed.netloc:
        raise LinkProblem(422, "the main server's address must start with https://")
    return f"https://{parsed.netloc}{parsed.path}"


def link(
    db: Session, home_id: str, main_url: str, code: str, site_name: str
) -> dict[str, Any]:
    """Use a pairing code from the main server and save what it gives."""
    url = _clean_url(main_url)
    try:
        answer = requests.post(
            f"{url}/api/v1/federation/pair",
            json={
                "code": code.strip(),
                "site_home_id": home_id,
                "site_name": site_name,
            },
            timeout=TIMEOUT_SECONDS,
        )
    except requests.RequestException as error:
        raise LinkProblem(
            502, f"could not reach the main server: {type(error).__name__}"
        ) from None
    if answer.status_code == 404:
        raise LinkProblem(
            409, "the main server did not take that code (wrong or expired)"
        )
    if answer.status_code != 200:
        raise LinkProblem(502, f"the main server answered {answer.status_code}")
    data = answer.json()
    saved = {
        "main_url": url,
        "token": str(data["token"]),
        "main_home_id": str(data["home_id"]),
        "main_home_name": str(data.get("home_name") or ""),
    }
    credentials.save(db, home_id, CREDENTIAL, "Main server", saved)
    return status(db, home_id)


def unlink(db: Session, home_id: str) -> None:
    credentials.remove(db, home_id, CREDENTIAL)
    _stop(home_id)


def saved_link(db: Session, home_id: str) -> dict[str, Any] | None:
    return credentials.load(db, home_id, CREDENTIAL)


def status(db: Session, home_id: str) -> dict[str, Any]:
    saved = saved_link(db, home_id)
    if not saved:
        return {"linked": False}
    return {
        "linked": True,
        "main_url": saved["main_url"],
        "main_home_name": saved.get("main_home_name"),
        "connected": home_id in _connected,
    }


# ------------------------------------------------------------ running requests


def service_user(db: Session, home_id: str, role: str) -> User:
    """The "Main server" user of this role in this home, made if needed. No
    one can log in as it (a random password, an address that cannot exist)."""
    email = f"{role}.{home_id[:8]}@{SERVICE_DOMAIN}"
    user = db.scalars(select(User).where(User.email == email)).first()
    if user is None:
        user = User(
            email=email,
            hashed_password=hash_password(secrets.token_urlsafe(32)),
            name=f"Main server ({role})",
            is_active=True,
            is_superuser=False,
            is_totp_enabled=True,  # stands in for the main server's own login
            totp_secret=None,
        )
        db.add(user)
        db.flush()
        db.add(HomeMembership(user_id=user.id, home_id=home_id, role=role))
        db.commit()
    return user


_sessions: dict[tuple[str, str], tuple[str, str]] = {}


def _session(home_id: str, role: str) -> tuple[str, str]:
    """(session token, CSRF token) for the role's service user."""
    with SessionLocal() as db:
        known = _sessions.get((home_id, role))
        if known is not None and get_valid_session(db, known[0]) is not None:
            return known
        user = service_user(db, home_id, role)
        made = create_session(
            db, user.id, "main-server", keep=True, keep_seconds=7 * 86400
        )
    _sessions[(home_id, role)] = made
    return made


async def run_here(app: Any, home_id: str, request: dict[str, Any]) -> dict[str, Any]:
    """Run one request from the main server on this server's own API (in
    process, as the role's service user). Only this home's per-home API."""
    role = str(request.get("role"))
    path = str(request.get("path") or "")
    if role not in ROLES or not path.startswith(f"/api/v1/homes/{home_id}/"):
        return {
            "status": 403,
            "content_type": "application/json",
            "body": '{"detail":"Forbidden"}',
        }
    token, csrf = await asyncio.to_thread(_session, home_id, role)
    body = str(request.get("body") or "").encode()
    headers = [
        (b"host", b"site.internal"),
        (b"cookie", f"{SESSION_COOKIE}={token}".encode()),
        (CSRF_HEADER.lower().encode(), csrf.encode()),
        (b"content-type", b"application/json"),
        (b"content-length", str(len(body)).encode()),
    ]
    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": str(request.get("method") or "GET").upper(),
        "scheme": "https",
        "path": path,
        "raw_path": path.encode(),
        "query_string": str(request.get("query") or "").encode(),
        "headers": headers,
        "client": ("127.0.0.1", 0),
        "server": ("site.internal", 443),
    }
    sent = False
    out: dict[str, Any] = {"status": 500, "content_type": "application/json"}
    chunks: list[bytes] = []

    async def receive() -> dict[str, Any]:
        nonlocal sent
        if sent:
            return {"type": "http.disconnect"}
        sent = True
        return {"type": "http.request", "body": body, "more_body": False}

    async def send(message: dict[str, Any]) -> None:
        if message["type"] == "http.response.start":
            out["status"] = message["status"]
            for name, value in message.get("headers", []):
                if name.lower() == b"content-type":
                    out["content_type"] = value.decode()
        elif message["type"] == "http.response.body":
            chunks.append(message.get("body", b""))

    await app(scope, receive, send)
    out["body"] = b"".join(chunks).decode("utf-8", "replace")
    return out


# ------------------------------------------------------------ staying connected

_tasks: dict[str, asyncio.Task[None]] = {}
_connected: set[str] = set()


def _stop(home_id: str) -> None:
    task = _tasks.pop(home_id, None)
    if task is not None:
        task.cancel()
    _connected.discard(home_id)


async def _stay_connected(app: Any, home_id: str) -> None:
    attempt = 0
    while True:
        with SessionLocal() as db:
            saved = saved_link(db, home_id)
        if not saved:
            return
        url = (
            saved["main_url"].replace("https://", "wss://", 1)
            + "/api/v1/federation/connect"
        )
        headers = {"Authorization": f"Bearer {saved['token']}"}
        try:
            async with (
                aiohttp.ClientSession() as http,
                http.ws_connect(url, headers=headers, heartbeat=30) as ws,
            ):
                attempt = 0
                _connected.add(home_id)
                async for message in ws:
                    if message.type != aiohttp.WSMsgType.TEXT:
                        continue
                    asyncio.create_task(_answer(app, home_id, ws, message.data))
        except (aiohttp.ClientError, OSError, TimeoutError) as error:
            log.info("main server connection for a home: %s", type(error).__name__)
        finally:
            _connected.discard(home_id)
        await asyncio.sleep(RETRY_SECONDS[min(attempt, len(RETRY_SECONDS) - 1)])
        attempt += 1


async def _answer(app: Any, home_id: str, ws: Any, text: str) -> None:
    try:
        request = json.loads(text)
    except ValueError:
        return
    if not isinstance(request, dict) or request.get("type") != "request":
        return
    try:
        answer = await run_here(app, home_id, request)
    except Exception as error:  # noqa: BLE001 - one bad request must not end the link
        log.exception("a request from the main server failed")
        answer = {
            "status": 500,
            "content_type": "application/json",
            "body": json.dumps({"detail": type(error).__name__}),
        }
    await ws.send_str(
        json.dumps({"type": "response", "id": request.get("id"), **answer})
    )


async def run_forever(app: Any) -> None:
    """Keep a connection to the main server for each linked home (checked
    every CHECK_SECONDS, so a new link connects and an unlinked one stops)."""
    while True:
        with SessionLocal() as db:
            linked = set(
                db.scalars(
                    select(IntegrationCredential.home_id).where(
                        IntegrationCredential.integration == CREDENTIAL
                    )
                )
            )
        for home_id in linked:
            task = _tasks.get(home_id)
            if task is None or task.done():
                _tasks[home_id] = asyncio.create_task(_stay_connected(app, home_id))
        for home_id in list(_tasks):
            if home_id not in linked:
                _stop(home_id)
        await asyncio.sleep(CHECK_SECONDS)
