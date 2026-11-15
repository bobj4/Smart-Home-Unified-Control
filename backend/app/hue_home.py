"""A home's Philips Hue Bridge: pairing, finding its lights and plugs,
commands and the state refresh. The bridge's key is stored encrypted.
Network calls go through app.integrations.hue."""

import json
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import credentials, integration_status
from app.features import integration_enabled
from app.integrations import hue
from app.models import Device, utcnow
from app.vault import VaultError

INTEGRATION = "hue"


class HueUnavailable(Exception):
    def __init__(self, status_code: int, reason: str) -> None:
        self.status_code = status_code
        self.reason = reason


def _guard(action: Any) -> Any:
    try:
        return action()
    except hue.HueButton as error:
        raise HueUnavailable(409, str(error)) from None
    except hue.HueError as error:
        raise HueUnavailable(502, str(error)) from None


def _bridge(db: Session, home_id: str) -> tuple[str, str]:
    try:
        saved = credentials.load(db, home_id, INTEGRATION)
    except VaultError as error:
        raise HueUnavailable(409, str(error)) from None
    if not saved:
        raise HueUnavailable(409, "pair the Hue Bridge first (Settings > Integrations)")
    return str(saved["host"]), str(saved["key"])


def status(db: Session, home_id: str) -> dict[str, Any]:
    host = credentials.label(db, home_id, INTEGRATION)
    count = len(list_lights(db, home_id))
    return {"paired": host is not None, "host": host, "devices": count}


def list_lights(db: Session, home_id: str) -> list[Device]:
    return list(
        db.scalars(
            select(Device)
            .where(Device.home_id == home_id, Device.integration == INTEGRATION)
            .order_by(Device.name)
        )
    )


def pair(db: Session, home_id: str, host: str) -> dict[str, int]:
    """Ask the bridge for a key (its button pressed), save it, find devices."""
    if not integration_enabled(db, home_id, INTEGRATION):
        raise HueUnavailable(409, "the Philips Hue integration is turned off")
    key = _guard(lambda: hue.pair(host))
    try:
        credentials.save(db, home_id, INTEGRATION, host, {"host": host, "key": key})
    except VaultError as error:
        raise HueUnavailable(409, str(error)) from None
    return sync(db, home_id)


def sync(db: Session, home_id: str) -> dict[str, int]:
    """Create or update a device per light and plug; remove ones gone from
    the bridge."""
    host, key = _bridge(db, home_id)
    found = _guard(lambda: hue.lights(host, key))
    try:  # the Hue app's rooms, for lights not given a room here
        rooms = hue.rooms(host, key)
    except hue.HueError:
        rooms = {}
    existing = {d.external_id: d for d in list_lights(db, home_id)}
    created = 0
    for info in found:
        device = existing.pop(info["id"], None)
        if device is None:
            device = Device(
                home_id=home_id,
                integration=INTEGRATION,
                external_id=info["id"],
                type=info["kind"],
                name=info["name"],
                state="{}",
            )
            db.add(device)
            created += 1
        if not device.room and rooms.get(info["id"]):
            device.room = rooms[info["id"]]
        device.capabilities = json.dumps(
            {
                "dimming": info["kind"] == "light",
                "white": info["white"],
                "color": info["color"],
            }
        )
        _apply(device, info)
    for gone in existing.values():
        db.delete(gone)
    db.commit()
    return {"created": created, "updated": len(found) - created}


def _apply(device: Device, info: dict[str, Any]) -> bool:
    """Take the bridge's report into the device; returns whether it changed."""
    state = json.loads(device.state or "{}")
    new = {**state, "on": info["on"]}
    if info.get("brightness") is not None and device.type == "light":
        new["brightness"] = info["brightness"]
    changed = new != state or device.online != info["online"]
    device.state = json.dumps(new)
    device.online = info["online"]
    if changed:
        device.last_updated = utcnow()
    return changed


def unpair(db: Session, home_id: str) -> None:
    for device in list_lights(db, home_id):
        db.delete(device)
    credentials.remove(db, home_id, INTEGRATION)
    db.commit()


def list_scenes(db: Session, home_id: str) -> list[dict[str, str]]:
    """The scenes saved in the Hue app ([] when Hue is off or not paired)."""
    if not integration_enabled(db, home_id, INTEGRATION):
        return []
    if credentials.label(db, home_id, INTEGRATION) is None:
        return []
    host, key = _bridge(db, home_id)
    found: list[dict[str, str]] = _guard(lambda: hue.scenes(host, key))
    return found


def recall_scene(db: Session, home_id: str, scene: str) -> None:
    if not integration_enabled(db, home_id, INTEGRATION):
        raise HueUnavailable(409, "the Philips Hue integration is turned off")
    host, key = _bridge(db, home_id)
    _guard(lambda: hue.recall(host, key, scene))


def send_command(
    db: Session, device: Device, command: str, state: dict[str, Any]
) -> None:
    """Carry out an already validated light or plug command on the bridge."""
    host, key = _bridge(db, device.home_id)
    body = _guard(lambda: hue.body_for(command, state))
    _guard(lambda: hue.set_state(host, key, str(device.external_id), body))


def refresh(db: Session, home_id: str) -> int:
    """Read every light's state from the bridge; returns how many changed."""
    if not integration_enabled(db, home_id, INTEGRATION):
        return 0
    if credentials.label(db, home_id, INTEGRATION) is None:
        return 0
    host, key = _bridge(db, home_id)
    try:
        found = {i["id"]: i for i in _guard(lambda: hue.lights(host, key))}
    except HueUnavailable as error:
        # The bridge does not answer: its lights cannot be reached either.
        integration_status.failed(home_id, INTEGRATION, error.reason)
        gone = 0
        for device in list_lights(db, home_id):
            if device.online:
                device.online = False
                device.last_updated = utcnow()
                gone += 1
        db.commit()
        return gone
    integration_status.worked(home_id, INTEGRATION)
    changed = 0
    for device in list_lights(db, home_id):
        info = found.get(str(device.external_id))
        if info is not None and _apply(device, info):
            changed += 1
    db.commit()
    return changed
