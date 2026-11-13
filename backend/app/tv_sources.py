"""A home's SmartThings link, for Samsung TV inputs by name and for turning a
TV on that Wake-on-LAN cannot reach. Optional: without it the remote keeps
its fixed inputs (TV, HDMI 1-4, USB) sent as keys."""

import json
import logging
import re
from typing import Any

from sqlalchemy.orm import Session

from app import credentials, smartthings_oauth
from app.integrations import smartthings
from app.models import Device
from app.vault import VaultError

log = logging.getLogger(__name__)
CREDENTIAL = "samsung_tv:smartthings"


class SourcesUnavailable(Exception):
    def __init__(self, status_code: int, reason: str) -> None:
        self.status_code = status_code
        self.reason = reason


def _guard(action: Any) -> Any:
    try:
        return action()
    except smartthings.SmartThingsDenied:
        raise SourcesUnavailable(
            409,
            "SmartThings refused the sign-in: connect it again in Settings > Integrations",
        ) from None
    except smartthings.SmartThingsError as error:
        raise SourcesUnavailable(502, str(error)) from None


def _token(db: Session, home_id: str) -> str:
    try:
        saved = credentials.load(db, home_id, CREDENTIAL)
    except VaultError as error:
        raise SourcesUnavailable(409, str(error)) from None
    if not saved or not (saved.get("token") or saved.get("oauth")):
        raise SourcesUnavailable(
            409, "connect SmartThings first (Settings > Integrations)"
        )
    # A sign-in (OAuth) is renewed here first when it is about to end.
    return str(_guard(lambda: smartthings_oauth.access_token(db, home_id, saved)))


def connected(db: Session, home_id: str) -> bool:
    return credentials.label(db, home_id, CREDENTIAL) is not None


def connect(db: Session, home_id: str, token: str) -> list[dict[str, str]]:
    """Check the token by listing the TVs, then save it. Returns the TVs."""
    found = _guard(lambda: smartthings.tvs(token))
    try:
        credentials.save(db, home_id, CREDENTIAL, "SmartThings", {"token": token})
    except VaultError as error:
        raise SourcesUnavailable(409, str(error)) from None
    return list(found)


def disconnect(db: Session, home_id: str) -> None:
    credentials.remove(db, home_id, CREDENTIAL)


def smartthings_tvs(db: Session, home_id: str) -> list[dict[str, str]]:
    token = _token(db, home_id)
    return list(_guard(lambda: smartthings.tvs(token)))


def linked_id(device: Device) -> str | None:
    value = json.loads(device.capabilities or "{}").get("smartthings_id")
    return str(value) if value else None


def link(db: Session, device: Device, smartthings_id: str | None) -> None:
    """Which SmartThings device this TV is (None = not linked)."""
    data = json.loads(device.capabilities or "{}")
    data["smartthings_id"] = smartthings_id
    device.capabilities = json.dumps(data)
    db.commit()


def tv_sources(db: Session, device: Device) -> dict[str, Any]:
    st_id = linked_id(device)
    if not st_id:
        raise SourcesUnavailable(409, "link this TV to SmartThings first")
    token = _token(db, device.home_id)
    return dict(_guard(lambda: smartthings.sources(token, st_id)))


def set_tv_source(db: Session, device: Device, source: str) -> None:
    st_id = linked_id(device)
    if not st_id:
        raise SourcesUnavailable(409, "link this TV to SmartThings first")
    token = _token(db, device.home_id)
    _guard(lambda: smartthings.set_source(token, st_id, source))


def _plain(name: str) -> str:
    """A TV's name without "[TV]" or "TV" ("[TV] Den" and "Den TV" match)."""
    return " ".join(re.sub(r"\[tv\]|\btv\b", " ", name.casefold()).split())


def _power_link(db: Session, device: Device, token: str) -> str | None:
    """The SmartThings TV to turn on: the linked one, else (linked now) the
    one of the same name, else the account's only TV."""
    st_id = linked_id(device)
    if st_id:
        return st_id
    found = smartthings.tvs(token)
    name = _plain(device.name)
    same = [tv for tv in found if name and _plain(tv["name"]) == name]
    pick = same if len(same) == 1 else found if len(found) == 1 else []
    if not pick:
        return None
    link(db, device, pick[0]["id"])
    return pick[0]["id"]


def turn_on(db: Session, device: Device) -> bool:
    """Ask SmartThings to turn the TV on. False when it cannot (not
    connected, no TV to link to, or SmartThings refused): the caller still
    has Wake-on-LAN or the power key."""
    if not connected(db, device.home_id):
        return False
    try:
        token = _token(db, device.home_id)
        st_id = _power_link(db, device, token)
        if st_id is None:
            log.info(
                "%s: no SmartThings TV to turn on (link it in Settings)", device.name
            )
            return False
        smartthings.switch_on(token, st_id)
    except (SourcesUnavailable, smartthings.SmartThingsError) as error:
        log.info(
            "%s: SmartThings could not turn it on: %s",
            device.name,
            getattr(error, "reason", error),
        )
        return False
    return True


def saved_login(db: Session, home_id: str) -> dict[str, Any] | None:
    """The saved SmartThings login (None if none or unreadable)."""
    try:
        return credentials.load(db, home_id, CREDENTIAL)
    except VaultError:
        return None
