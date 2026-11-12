"""SmartThings sign-in that keeps itself (OAuth), instead of a personal
access token that lasts 24 hours.

The owner makes an "OAuth-In" SmartApp once (SmartThings CLI: `smartthings
apps:create`, scopes r:devices:* and x:devices:*) whose redirect URI is this
server's /api/v1/smartthings/callback, and enters its client ID and secret
here. "Connect SmartThings" sends them to Samsung to sign in; SmartThings
sends them back with a code, swapped for a 24-hour access token and a
refresh token. The refresh runs about every 12 hours (refresh_all), so the
refresh token (about 29 days unused) never lapses while the server runs.

Saved like the token was (credential "samsung_tv:smartthings", encrypted):
{"oauth": true, "client_id", "client_secret", "redirect_uri",
 "access_token", "refresh_token", "expires_at" (epoch seconds),
 "renewed_at", "problem" (None, or why it must be connected again)}.
"""

import secrets
import time
from typing import Any

from sqlalchemy.orm import Session

from app import credentials, integration_status
from app.integrations import smartthings

CREDENTIAL = "samsung_tv:smartthings"
INTEGRATION = "samsung_tv"
RENEW_SECONDS = 12 * 3600  # renew once the token is this old
SOON_SECONDS = 600  # or when it ends within this
START_SECONDS = 900  # a sign-in must come back within this
CALLBACK = "/api/v1/smartthings/callback"
RECONNECT = "SmartThings needs connecting again (Settings > Integrations)"

# state -> (home id, user id, app details, started)
_started: dict[str, tuple[str, str, dict[str, str], float]] = {}


class OAuthProblem(Exception):
    def __init__(self, status_code: int, reason: str) -> None:
        self.status_code = status_code
        self.reason = reason


def start(home_id: str, user_id: str, app: dict[str, str]) -> str:
    """The SmartThings sign-in page to send the person to. `app`: client_id,
    client_secret, redirect_uri."""
    if not app["redirect_uri"].startswith("https://"):
        raise OAuthProblem(
            422, "SmartThings only sends you back to an https:// address"
        )
    now = time.monotonic()
    for state, entry in list(_started.items()):
        if now - entry[3] > START_SECONDS:
            _started.pop(state, None)
    state = secrets.token_urlsafe(24)
    _started[state] = (home_id, user_id, dict(app), now)
    return smartthings.authorize_url(app["client_id"], app["redirect_uri"], state)


def _saved(answer: dict[str, Any], app: dict[str, str]) -> dict[str, Any]:
    now = time.time()
    return {
        "oauth": True,
        **app,
        "access_token": str(answer["access_token"]),
        "refresh_token": str(answer.get("refresh_token") or ""),
        "expires_at": now + float(answer.get("expires_in") or 86400),
        "renewed_at": now,
        "problem": None,
    }


def finish(db: Session, state: str, code: str) -> tuple[str, str]:
    """Swap the code SmartThings sent back for tokens and save them.
    Returns (home id, who started it).

    The way back from SmartThings carries no login (the session cookie is
    SameSite=Strict): the state, random, used once and only for
    START_SECONDS, is what ties it to the home and person who started it."""
    entry = _started.pop(state, None)
    if entry is None or time.monotonic() - entry[3] > START_SECONDS:
        raise OAuthProblem(400, "that sign-in has expired: connect SmartThings again")
    home_id, started_by, app, _ = entry
    try:
        answer = smartthings.token_request(
            app["client_id"],
            app["client_secret"],
            {
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": app["redirect_uri"],
            },
        )
        smartthings.tvs(str(answer["access_token"]))  # it works
    except smartthings.SmartThingsError as error:
        raise OAuthProblem(502, str(error)) from None
    credentials.save(db, home_id, CREDENTIAL, "SmartThings", _saved(answer, app))
    integration_status.worked(home_id, INTEGRATION)
    return home_id, started_by


def _renew(db: Session, home_id: str, saved: dict[str, Any]) -> dict[str, Any]:
    app = {k: str(saved[k]) for k in ("client_id", "client_secret", "redirect_uri")}
    try:
        answer = smartthings.token_request(
            app["client_id"],
            app["client_secret"],
            {
                "grant_type": "refresh_token",
                "refresh_token": str(saved["refresh_token"]),
            },
        )
    except smartthings.SmartThingsDenied:
        # The refresh token is used up or lapsed: only signing in again helps.
        credentials.save(
            db, home_id, CREDENTIAL, "SmartThings", {**saved, "problem": RECONNECT}
        )
        integration_status.failed(home_id, INTEGRATION, RECONNECT)
        raise
    fresh = _saved(answer, app)
    if not fresh["refresh_token"]:
        fresh["refresh_token"] = saved["refresh_token"]
    credentials.save(db, home_id, CREDENTIAL, "SmartThings", fresh)
    integration_status.worked(home_id, INTEGRATION)
    return fresh


def access_token(db: Session, home_id: str, saved: dict[str, Any]) -> str:
    """The token to call SmartThings with: a saved personal token as it is,
    an OAuth one renewed first if it is about to end."""
    if not saved.get("oauth"):
        return str(saved["token"])
    if saved.get("problem"):
        raise smartthings.SmartThingsDenied(str(saved["problem"]))
    if float(saved["expires_at"]) - time.time() < SOON_SECONDS:
        saved = _renew(db, home_id, saved)
    return str(saved["access_token"])


def keep_fresh(db: Session, home_id: str) -> bool:
    """Renew the home's SmartThings sign-in once it is RENEW_SECONDS old
    (from the background refresh). Returns whether it was renewed."""
    if credentials.label(db, home_id, CREDENTIAL) is None:
        return False
    saved = credentials.load(db, home_id, CREDENTIAL) or {}
    if not saved.get("oauth") or saved.get("problem"):
        return False
    old = time.time() - float(saved.get("renewed_at") or 0) >= RENEW_SECONDS
    if not old and float(saved["expires_at"]) - time.time() >= SOON_SECONDS:
        return False
    try:
        _renew(db, home_id, saved)
    except smartthings.SmartThingsDenied:
        return False
    except smartthings.SmartThingsError as error:
        integration_status.failed(home_id, INTEGRATION, str(error))  # try next pass
        return False
    return True


def status(saved: dict[str, Any] | None) -> dict[str, Any]:
    """What Settings shows: how it is connected, and any problem."""
    if not saved:
        return {"method": None, "problem": None}
    if not saved.get("oauth"):
        return {"method": "token", "problem": None}
    return {
        "method": "oauth",
        "problem": saved.get("problem"),
        "client_id": saved.get("client_id"),
        "redirect_uri": saved.get("redirect_uri"),
    }
