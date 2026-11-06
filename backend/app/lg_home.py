"""A home's LG webOS TVs: adding, pairing (a prompt on the TV), commands,
the on/off refresh. The TV's key is stored encrypted. Network calls go
through app.integrations.lg (and Wake-on-LAN, for turning on)."""

import json
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import credentials
from app.features import integration_enabled
from app.integrations import lg, samsung
from app.models import Device, utcnow
from app.vault import VaultError

INTEGRATION = "lg_tv"


class LgUnavailable(Exception):
    def __init__(self, status_code: int, reason: str) -> None:
        self.status_code = status_code
        self.reason = reason


def _key_name(device: Device) -> str:
    return f"{INTEGRATION}:{device.id}"


def tv_out(device: Device) -> dict[str, Any]:
    caps = json.loads(device.capabilities or "{}")
    return {
        "device_id": device.id,
        "name": device.name,
        "host": device.external_id,
        "mac": caps.get("mac"),
        "paired": bool(caps.get("paired")),
    }


def list_tvs(db: Session, home_id: str) -> list[Device]:
    return list(
        db.scalars(
            select(Device)
            .where(Device.home_id == home_id, Device.integration == INTEGRATION)
            .order_by(Device.name)
        )
    )


def add_tv(
    db: Session, home_id: str, name: str, host: str, mac: str | None, room: str | None
) -> Device:
    if not integration_enabled(db, home_id, INTEGRATION):
        raise LgUnavailable(409, "the LG TV integration is turned off")
    if any(d.external_id == host for d in list_tvs(db, home_id)):
        raise LgUnavailable(409, "a TV with that address is already added")
    device = Device(
        home_id=home_id,
        integration=INTEGRATION,
        external_id=host,
        type="tv",
        name=name,
        room=room,
        capabilities=json.dumps({"mac": mac, "paired": False}),
        state="{}",
        online=False,
    )
    db.add(device)
    db.commit()
    return device


def pair_tv(db: Session, device: Device) -> None:
    """Show the prompt on the TV; once accepted, keep its key."""
    try:
        key = lg.pair(str(device.external_id))
    except lg.LgDenied as error:
        raise LgUnavailable(409, str(error)) from None
    except lg.LgError as error:
        raise LgUnavailable(502, str(error)) from None
    try:
        credentials.save(
            db, device.home_id, _key_name(device), str(device.external_id), {"key": key}
        )
    except VaultError as error:
        raise LgUnavailable(409, str(error)) from None
    caps = json.loads(device.capabilities or "{}")
    device.capabilities = json.dumps({**caps, "paired": True})
    device.online = True
    db.commit()


def remove_tv(db: Session, device: Device) -> None:
    credentials.remove(db, device.home_id, _key_name(device))
    db.delete(device)
    db.commit()


def _key(db: Session, device: Device) -> str:
    try:
        saved = credentials.load(db, device.home_id, _key_name(device))
    except VaultError as error:
        raise LgUnavailable(409, str(error)) from None
    if not saved or not saved.get("key"):
        raise LgUnavailable(409, "pair the TV first (Settings > Integrations)")
    return str(saved["key"])


def tv_apps(db: Session, device: Device) -> list[dict[str, str]]:
    key = _key(db, device)
    try:
        found = lg.apps(str(device.external_id), key)
    except lg.LgError as error:
        raise LgUnavailable(502, str(error)) from None
    return sorted(found, key=lambda app: app["name"].lower())


def send_tv_command(
    db: Session, device: Device, command: str, payload: dict[str, Any]
) -> None:
    """Carry out an already validated TV command on the TV."""
    caps = json.loads(device.capabilities or "{}")
    if command == "turn_on":
        if not caps.get("mac"):
            raise LgUnavailable(422, "add the TV's MAC address to turn it on")
        try:
            samsung.wake(str(caps["mac"]))  # plain Wake-on-LAN, any brand
        except samsung.TvError as error:
            raise LgUnavailable(502, str(error)) from None
        return
    key = _key(db, device)
    try:
        lg.command(str(device.external_id), key, command, payload)
    except lg.LgUnsupported as error:
        raise LgUnavailable(422, str(error)) from None
    except lg.LgDenied as error:
        raise LgUnavailable(409, str(error)) from None
    except lg.LgError as error:
        raise LgUnavailable(502, str(error)) from None


def refresh(db: Session, home_id: str) -> int:
    """Update each paired TV's on/off; returns how many changed."""
    if not integration_enabled(db, home_id, INTEGRATION):
        return 0
    changed = 0
    for tv in list_tvs(db, home_id):
        if not json.loads(tv.capabilities or "{}").get("paired"):
            continue
        on = lg.is_on(str(tv.external_id))
        state = json.loads(tv.state or "{}")
        if state.get("on") != on:
            tv.state = json.dumps({**state, "on": on})
            tv.last_updated = utcnow()
            changed += 1
    db.commit()
    return changed
