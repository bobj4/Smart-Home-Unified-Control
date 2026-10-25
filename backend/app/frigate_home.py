"""A home's Frigate server: saved connection settings and a client for them.
Network calls go through app.integrations.frigate (replaced by a fake in tests)."""

from typing import Any

from sqlalchemy.orm import Session

from app import credentials
from app.features import integration_enabled
from app.integrations import frigate
from app.vault import VaultError

INTEGRATION = "frigate"


class FrigateUnavailable(Exception):
    def __init__(self, status_code: int, reason: str) -> None:
        self.status_code = status_code
        self.reason = reason


def server_out(db: Session, home_id: str) -> dict[str, Any]:
    """What the owner sees: never the password."""
    try:
        saved = credentials.load(db, home_id, INTEGRATION)
    except VaultError:
        saved = None
    if not saved:
        return {"configured": False, "url": None, "username": None, "verify_tls": True}
    return {
        "configured": True,
        "url": saved["url"],
        "username": saved.get("username"),
        "verify_tls": bool(saved.get("verify_tls", True)),
    }


# "could not reach Frigate: <requests error>" in plain words.
_UNREACHABLE = {
    "ConnectionError": "Could not connect to Frigate. Check the address and port, "
    "and that Frigate is running.",
    "ConnectTimeout": "Frigate did not answer within 10 seconds. Check the address, "
    "and that this server can reach it.",
    "ReadTimeout": "Frigate did not answer within 10 seconds. Check the address, "
    "and that this server can reach it.",
    "Timeout": "Frigate did not answer within 10 seconds. Check the address, "
    "and that this server can reach it.",
    "SSLError": "The HTTPS connection to Frigate failed. If Frigate uses its own "
    'self-signed certificate, untick "Check its HTTPS certificate"; if that port '
    "has no HTTPS, start the address with http://.",
    "InvalidURL": "That address is not valid.",
}


def plain_reason(reason: str) -> str:
    """The adapter's error, as a person setting Frigate up can act on it."""
    prefix = "could not reach Frigate: "
    if reason.startswith(prefix):
        kind = reason[len(prefix) :]
        return _UNREACHABLE.get(kind, f"Could not connect to Frigate ({kind}).")
    return reason


def call(action: Any) -> Any:
    """Run one Frigate call, turning its errors into FrigateUnavailable."""
    try:
        return action()
    except frigate.FrigateNotFound:
        raise FrigateUnavailable(404, "Not found") from None
    except frigate.FrigateLoginError as error:
        raise FrigateUnavailable(502, str(error)) from None
    except frigate.FrigateError as error:
        raise FrigateUnavailable(502, plain_reason(str(error))) from None


def client_for_home(db: Session, home_id: str) -> frigate.FrigateClient:
    if not integration_enabled(db, home_id, INTEGRATION):
        raise FrigateUnavailable(409, "the Frigate integration is turned off")
    try:
        saved = credentials.load(db, home_id, INTEGRATION)
    except VaultError as error:
        raise FrigateUnavailable(409, str(error)) from None
    if not saved:
        raise FrigateUnavailable(
            409, "Frigate is not set up yet (Settings > Integrations)"
        )
    return frigate.connect(
        saved["url"],
        saved.get("username"),
        saved.get("password"),
        bool(saved.get("verify_tls", True)),
    )
