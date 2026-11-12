"""Homes at other sites, on the main server.

A home here can have its devices at another site, run by that site's own
server (the same app; "site server"). People, logins, roles and guests stay
here on the main server; the devices, their integrations and their state
stay at the site. The site server needs no open port: it connects out to
the main server and keeps the connection open (app/federation_site.py).

Linking (Admin > Home, "Another site"):
  1. here: "Link a server at another site" gives a pairing code (half an
     hour, once);
  2. there: Admin > Home > "Link to a main server" with this server's
     address and the code: the site gets a token for this home (only its
     SHA-256 is kept here) and connects to /api/v1/federation/connect.

Then the per-home requests in FORWARDED for this home go to the site: the
main server checks the person's login and their role in the home here, and
the site runs the request as that role (its own checks apply too). If the
site is not connected, they get a 503 saying so.
"""

import asyncio
import hashlib
import json
import secrets
import time
import uuid
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Home

PAIRING_SECONDS = 1800
REQUEST_SECONDS = 25
MAX_BODY = 2 * 1024 * 1024
# The per-home parts of the API a site answers (/api/v1/homes/{id}/<part>).
FORWARDED = frozenset(
    {
        "devices",
        "groups",
        "rooms",
        "layout",
        "integrations",
        "cameras",
        "display",
        "safety-limits",
        "tv-scan",
        "thermostat-access",
    }
)
OFFLINE = "This home's server at the other site is not connected right now."


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


class SiteOffline(Exception):
    """The home's site server is not connected (or did not answer)."""


class Link:
    """One connected site server: send it requests, match its answers."""

    def __init__(
        self,
        send: Callable[[str], Awaitable[None]],
        loop: asyncio.AbstractEventLoop | None = None,
    ) -> None:
        self.send = send
        self.loop = loop or asyncio.get_running_loop()  # the connection's own
        self.waiting: dict[str, asyncio.Future[dict[str, Any]]] = {}
        self.connected_at = time.time()
        self.last_seen = time.time()


# main home id -> its connected site; main home id -> the site's home id
_links: dict[str, Link] = {}
_remote: dict[str, str] | None = None


def remote_homes(db: Session) -> dict[str, str]:
    """{home id here: its home at the site} for every linked home (kept in
    memory; changed by pair() and unlink())."""
    global _remote
    if _remote is None:
        _remote = {
            home.id: str(home.site_home_id)
            for home in db.scalars(
                select(Home).where(Home.site_token_hash.is_not(None))
            )
        }
    return _remote


def forget_cache() -> None:  # tests, and after a change
    global _remote
    _remote = None


def new_pairing(db: Session, home: Home) -> str:
    """A pairing code for this home (shown once; half an hour)."""
    code = "-".join(secrets.token_hex(2).upper() for _ in range(3))
    home.site_pairing_hash = _hash(code)
    home.site_pairing_until = datetime.now(UTC) + timedelta(seconds=PAIRING_SECONDS)
    db.commit()
    return code


def pair(db: Session, code: str, site_home_id: str, site_name: str) -> tuple[Home, str]:
    """A site server used a pairing code: the home it is for, and the token
    it connects with from now on. Raises LookupError."""
    home = db.scalars(
        select(Home).where(Home.site_pairing_hash == _hash(code.strip().upper()))
    ).first()
    until = home.site_pairing_until if home else None
    if home is None or until is None or until.replace(tzinfo=UTC) < datetime.now(UTC):
        raise LookupError("that pairing code is wrong or has expired")
    token = secrets.token_urlsafe(32)
    home.site_token_hash = _hash(token)
    home.site_home_id = site_home_id
    home.site_name = site_name
    home.site_pairing_hash = None
    home.site_pairing_until = None
    db.commit()
    forget_cache()
    return home, token


def home_for_token(db: Session, token: str) -> Home | None:
    if not token:
        return None
    return db.scalars(select(Home).where(Home.site_token_hash == _hash(token))).first()


def unlink(db: Session, home: Home) -> None:
    """The home's devices are no longer at a site (its token stops working)."""
    home.site_token_hash = None
    home.site_home_id = None
    home.site_name = None
    home.site_pairing_hash = None
    home.site_pairing_until = None
    db.commit()
    forget_cache()
    link = _links.pop(home.id, None)
    if link is not None:
        for waiting in link.waiting.values():
            waiting.cancel()


def connected(home_id: str, link: Link) -> None:
    old = _links.get(home_id)
    _links[home_id] = link
    if old is not None:  # the site came back on a new connection
        for waiting in old.waiting.values():
            waiting.cancel()


def disconnected(home_id: str, link: Link) -> None:
    if _links.get(home_id) is link:
        _links.pop(home_id, None)
    for waiting in link.waiting.values():
        waiting.cancel()


def answered(link: Link, text: str) -> None:
    """A message from the site: the answer to one of our requests."""
    link.last_seen = time.time()
    try:
        message = json.loads(text)
    except ValueError:
        return
    if not isinstance(message, dict) or message.get("type") != "response":
        return
    waiting = link.waiting.pop(str(message.get("id")), None)
    if waiting is not None and not waiting.done():
        waiting.set_result(message)


def status(home: Home) -> dict[str, Any]:
    link = _links.get(home.id)
    pending = home.site_pairing_until is not None and home.site_pairing_until.replace(
        tzinfo=UTC
    ) > datetime.now(UTC)
    return {
        "linked": home.site_token_hash is not None,
        "site_name": home.site_name,
        "connected": link is not None,
        "connected_since": datetime.fromtimestamp(link.connected_at, UTC).isoformat()
        if link
        else None,
        "pairing_open": pending,
    }


async def _ask(link: Link, request: dict[str, Any]) -> dict[str, Any]:
    """On the connection's loop: send the request, wait for its answer."""
    request_id = uuid.uuid4().hex
    waiting: asyncio.Future[dict[str, Any]] = link.loop.create_future()
    link.waiting[request_id] = waiting
    try:
        await link.send(json.dumps({"type": "request", "id": request_id, **request}))
        return await asyncio.wait_for(waiting, REQUEST_SECONDS)
    finally:
        link.waiting.pop(request_id, None)


async def forward(home_id: str, request: dict[str, Any]) -> dict[str, Any]:
    """Send one request to the home's site and wait for its answer:
    {"status", "content_type", "body"}. Raises SiteOffline."""
    link = _links.get(home_id)
    if link is None:
        raise SiteOffline(OFFLINE)
    try:
        if asyncio.get_running_loop() is link.loop:
            return await _ask(link, request)
        # Another loop (a second worker thread): ask on the connection's.
        running = asyncio.run_coroutine_threadsafe(_ask(link, request), link.loop)
        return await asyncio.wrap_future(running)
    except (TimeoutError, asyncio.CancelledError, ConnectionError, RuntimeError):
        raise SiteOffline(OFFLINE) from None
