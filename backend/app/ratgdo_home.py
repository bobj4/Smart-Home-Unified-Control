"""A home's ratgdo garage door openers: adding by address, removing,
commands and the state refresh."""

import json
from functools import partial
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import probes
from app.features import integration_enabled
from app.integrations import ratgdo
from app.models import Device, utcnow

INTEGRATION = "ratgdo"


class RatgdoUnavailable(Exception):
    def __init__(self, status_code: int, reason: str) -> None:
        self.status_code = status_code
        self.reason = reason


def door_out(device: Device) -> dict[str, Any]:
    return {"device_id": device.id, "name": device.name, "host": device.external_id}


def list_doors(db: Session, home_id: str) -> list[Device]:
    return list(
        db.scalars(
            select(Device)
            .where(Device.home_id == home_id, Device.integration == INTEGRATION)
            .order_by(Device.name)
        )
    )


def add_door(
    db: Session, home_id: str, name: str, host: str, room: str | None
) -> Device:
    if not integration_enabled(db, home_id, INTEGRATION):
        raise RatgdoUnavailable(409, "the ratgdo integration is turned off")
    if any(d.external_id == host for d in list_doors(db, home_id)):
        raise RatgdoUnavailable(409, "an opener with that address is already added")
    try:
        found = _read(host)
    except ratgdo.RatgdoError as error:
        raise RatgdoUnavailable(502, str(error)) from None
    device = Device(
        home_id=home_id,
        integration=INTEGRATION,
        external_id=host,
        type="garage_door",
        name=name,
        room=room,
        capabilities="{}",
        state=json.dumps(found),
        online=True,
    )
    db.add(device)
    db.commit()
    return device


def remove_door(db: Session, device: Device) -> None:
    db.delete(device)
    db.commit()


def send_command(device: Device, command: str) -> None:
    try:
        ratgdo.act(str(device.external_id), command)
    except ratgdo.RatgdoError as error:
        raise RatgdoUnavailable(502, str(error)) from None


def _read(host: str) -> dict[str, Any]:
    """The door, and the opener's obstruction sensor, light and lockout."""
    found = ratgdo.door(host)
    return {**found, **ratgdo.extras(host)}


def refresh(db: Session, home_id: str) -> int:
    """Read each opener's door; returns how many changed."""
    if not integration_enabled(db, home_id, INTEGRATION):
        return 0
    doors = [
        d for d in list_doors(db, home_id) if probes.due(f"ratgdo:{d.external_id}")
    ]
    answers = probes.gather({d.id: partial(_read, str(d.external_id)) for d in doors})
    changed = 0
    for device in doors:
        answer = answers[device.id]
        if isinstance(answer, Exception) and not isinstance(answer, ratgdo.RatgdoError):
            raise answer
        found: dict[str, Any] | None = None if isinstance(answer, Exception) else answer
        online = found is not None
        probes.answered(f"ratgdo:{device.external_id}", online)
        state = json.loads(device.state or "{}")
        new = {**state, **found} if found else state
        if new != state or device.online != online:
            device.state = json.dumps(new)
            device.online = online
            device.last_updated = utcnow()
            changed += 1
    db.commit()
    return changed
