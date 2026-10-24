"""A home's Rheem EcoNet account: finding its water heaters and sending set
points. Network calls go through app.integrations.rheem.connect."""

import json
import time
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import credentials
from app.features import integration_enabled
from app.integrations import rheem
from app.models import Device, utcnow
from app.vault import VaultError

INTEGRATION = "rheem_econet"


class RheemUnavailable(Exception):
    def __init__(self, status_code: int, reason: str) -> None:
        self.status_code = status_code
        self.reason = reason


def client_for_home(db: Session, home_id: str) -> rheem.RheemClient:
    if not integration_enabled(db, home_id, INTEGRATION):
        raise RheemUnavailable(409, "the Rheem EcoNet integration is turned off")
    try:
        login = credentials.load(db, home_id, INTEGRATION)
    except VaultError as error:
        raise RheemUnavailable(409, str(error)) from None
    if login is None:
        raise RheemUnavailable(409, "no EcoNet account is saved for this home")
    return rheem.connect(login["email"], login["password"])


def call(action: Any) -> Any:
    """Run one EcoNet call, turning its errors into RheemUnavailable."""
    try:
        return action()
    except rheem.RheemLoginError:
        raise RheemUnavailable(
            502, "EcoNet refused the saved email or password"
        ) from None
    except rheem.RheemError as error:
        raise RheemUnavailable(502, str(error)) from None


def sync(db: Session, home_id: str) -> dict[str, int]:
    """Create or update a device for every water heater on the account; delete
    ones no longer on the account (removed in the EcoNet app)."""
    client = client_for_home(db, home_id)
    heaters = call(client.list_water_heaters)
    existing = {
        d.external_id: d
        for d in db.scalars(
            select(Device).where(
                Device.home_id == home_id, Device.integration == INTEGRATION
            )
        )
    }
    created = updated = 0
    for heater in heaters:
        device = existing.pop(heater.serial, None)
        if device is None:
            device = Device(
                home_id=home_id,
                integration=INTEGRATION,
                external_id=heater.serial,
                type="water_heater",
                name=heater.name[:100] or "Water heater",
                capabilities="{}",
            )
            db.add(device)
            created += 1
        else:
            updated += 1
        device.state = json.dumps(heater.state())
        device.online = heater.connected
        device.last_updated = utcnow()
    for device in existing.values():
        db.delete(device)
    db.commit()
    return {"created": created, "updated": updated}


def check_set_point(device: Device, temperature: float) -> int:
    """Rheem takes whole degrees F within the heater's own range."""
    state = json.loads(device.state or "{}")
    if temperature != int(temperature):
        raise RheemUnavailable(422, "Rheem water heaters take whole degrees")
    low, high = state.get("min_set_point"), state.get("max_set_point")
    if low is not None and high is not None and not low <= temperature <= high:
        raise RheemUnavailable(422, f"this water heater accepts {low}-{high} F")
    return int(temperature)


def send_set_point(db: Session, device: Device, temperature: float) -> None:
    value = check_set_point(device, temperature)
    client = client_for_home(db, device.home_id)
    call(lambda: client.set_set_point(str(device.external_id), value))


def send_command(
    db: Session,
    device: Device,
    command: str,
    payload: dict[str, Any],
    state: dict[str, Any],
) -> None:
    """Carry out an accepted water-heater command on the real heater."""
    if command == "set_temperature":
        send_set_point(db, device, state["target_temperature"])
        return
    client = client_for_home(db, device.home_id)
    serial = str(device.external_id)
    if command in ("turn_off", "turn_on", "set_mode"):
        mode = state.get("mode")
        if not mode:
            raise RheemUnavailable(
                422, "this water heater cannot be switched on or off"
            )
        call(lambda: client.set_mode(serial, str(mode)))
    elif command == "set_away":
        call(lambda: client.set_away(serial, bool(payload["away"])))
    elif command == "resume_schedule":
        call(lambda: client.resume_schedule(serial))
    else:
        raise RheemUnavailable(422, "unsupported command")


USAGE_CACHE_SECONDS = 600
# (device id, days) -> (time fetched, usage); Rheem limits how often we ask.
_usage_cache: dict[tuple[str, int], tuple[float, dict[str, Any]]] = {}


def usage(db: Session, device: Device, days: int) -> dict[str, Any]:
    """Energy and water use for the graph (see RheemClient.usage)."""
    key = (device.id, days)
    cached = _usage_cache.get(key)
    if cached and time.monotonic() - cached[0] < USAGE_CACHE_SECONDS:
        return cached[1]
    client = client_for_home(db, device.home_id)
    found = call(lambda: client.usage(str(device.external_id), days))
    _usage_cache[key] = (time.monotonic(), found)
    return found
