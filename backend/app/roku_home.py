"""A home's Roku TVs and players: adding by address, removing, commands and
the on/off refresh. Network calls go through app.integrations.roku."""

import json
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.features import integration_enabled
from app.integrations import roku
from app.models import Device, utcnow

INTEGRATION = "roku_tv"


class RokuUnavailable(Exception):
    def __init__(self, status_code: int, reason: str) -> None:
        self.status_code = status_code
        self.reason = reason


def tv_out(device: Device) -> dict[str, Any]:
    caps = json.loads(device.capabilities or "{}")
    return {
        "device_id": device.id,
        "name": device.name,
        "host": device.external_id,
        "model": caps.get("model"),
        "is_tv": bool(caps.get("is_tv")),
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
    db: Session, home_id: str, name: str | None, host: str, room: str | None
) -> Device:
    if not integration_enabled(db, home_id, INTEGRATION):
        raise RokuUnavailable(409, "the Roku integration is turned off")
    if any(d.external_id == host for d in list_tvs(db, home_id)):
        raise RokuUnavailable(409, "a Roku with that address is already added")
    try:
        found = roku.info(host)
    except roku.RokuError as error:
        raise RokuUnavailable(502, str(error)) from None
    device = Device(
        home_id=home_id,
        integration=INTEGRATION,
        external_id=host,
        type="tv",
        name=(name or str(found["name"] or "Roku"))[:100],
        room=room,
        capabilities=json.dumps({"model": found["model"], "is_tv": found["is_tv"]}),
        state=json.dumps({"on": bool(found["on"])}),
        online=True,
    )
    db.add(device)
    db.commit()
    return device


def remove_tv(db: Session, device: Device) -> None:
    db.delete(device)
    db.commit()


def tv_apps(device: Device) -> list[dict[str, str]]:
    try:
        found = roku.apps(str(device.external_id))
    except roku.RokuError as error:
        raise RokuUnavailable(502, str(error)) from None
    return sorted(found, key=lambda app: app["name"].lower())


def send_tv_command(device: Device, command: str, payload: dict[str, Any]) -> None:
    """Carry out an already validated TV command on the Roku."""
    caps = json.loads(device.capabilities or "{}")
    if command in (
        "set_input",
        "set_channel",
        "channel_up",
        "channel_down",
    ) and not caps.get("is_tv"):
        raise RokuUnavailable(422, "a Roku player has no TV inputs or channels")
    try:
        roku.command(str(device.external_id), command, payload)
    except roku.RokuUnsupported as error:
        raise RokuUnavailable(422, str(error)) from None
    except roku.RokuError as error:
        raise RokuUnavailable(502, str(error)) from None


def refresh(db: Session, home_id: str) -> int:
    """Update each Roku's on/off and reachability; returns how many changed."""
    if not integration_enabled(db, home_id, INTEGRATION):
        return 0
    changed = 0
    for tv in list_tvs(db, home_id):
        on = roku.is_on(str(tv.external_id))
        online = on is not None
        state = json.loads(tv.state or "{}")
        if tv.online != online or (online and state.get("on") != on):
            tv.online = online
            if online:
                tv.state = json.dumps({**state, "on": on})
            tv.last_updated = utcnow()
            changed += 1
    db.commit()
    return changed
