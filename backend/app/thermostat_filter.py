"""A Cync thermostat's own air-filter reminder, read from and written to the
thermostat (filter_reminders.py keeps it and counts the time left).

From the Cync app 6.20 (docs/CYNC-THERMOSTAT.md, Air filter):
- Event_Filter_Replacement_En (point 54, yes/no): the reminder is on.
- Filter_Replacement_Method (point 61, 3 bytes): 0 = calendar months or
  1 = run hours, then the number (2 bytes, big-endian): months 1 to 12, run
  hours 100 to 1500 in hundreds.
- Filter_Replacement_Reset (point 88, yes/no): the app writes "no" when the
  filter is replaced, and the thermostat starts its count again.
- FilterInfoStatus (point 106, in its regular report): the reset date and
  the run hours since (state "filter_reset" and "filter_hours").

The two settings are not in the regular report: they are asked for by name
with the other settings (thermostat_settings.read_settings), and once in a
while by the alerts check (sync).
"""

import json
import time
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import cync_live, filter_reminders
from app.cync_home import CyncUnavailable, _call
from app.integrations import cync, cync_thermostat
from app.models import Device
from app.thermostat_schedule import _connection

ENABLED, ENABLED_POINT = "Event_Filter_Replacement_En", 54
METHOD, METHOD_POINT = "Filter_Replacement_Method", 61
RESET_POINT = 88
NAMES = [ENABLED, METHOD]
METHOD_CODES = {0: "months", 1: "hours"}
SYNC_SECONDS = 6 * 3600  # how often the alerts check reads them again

# device id -> when the alerts check last read them
_synced: dict[str, float] = {}


def _flag(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    if isinstance(value, int) and value in (0, 1):
        return bool(value)
    if isinstance(value, str) and value.strip().lower() in ("true", "false", "1", "0"):
        return value.strip().lower() in ("true", "1")
    return None


def _as_bytes(value: Any) -> bytes | None:
    """A bytes setting as the thermostat answers it: a list of numbers (as
    the schedules come) or hex text."""
    if isinstance(value, list) and all(
        isinstance(v, int) and not isinstance(v, bool) for v in value
    ):
        return bytes(v & 0xFF for v in value)
    if isinstance(value, str):
        try:
            return bytes.fromhex(value)
        except ValueError:
            return None
    return None


def decode_method(value: Any) -> tuple[str, int] | None:
    """(mode, every) from Filter_Replacement_Method, or None."""
    raw = _as_bytes(value)
    if raw is None or len(raw) < 3 or raw[0] not in METHOD_CODES:
        return None
    return METHOD_CODES[raw[0]], int.from_bytes(raw[1:3], "big")


def encode_method(mode: str, every: int) -> bytes:
    code = {name: code for code, name in METHOD_CODES.items()}[mode]
    return bytes([code]) + every.to_bytes(2, "big")


def is_cync(device: Device) -> bool:
    cloud_id = json.loads(device.capabilities or "{}").get("cloud_id")
    return device.integration == "cync" and cloud_id is not None


def store(db: Session, device: Device, values: dict[str, Any]) -> None:
    """Keep what a settings read found (both answers, or nothing)."""
    enabled = _flag(values.get(ENABLED))
    method = decode_method(values.get(METHOD))
    if enabled is None or method is None:
        return
    mode, every = method
    low, high = filter_reminders.LIMITS[mode]
    if not low <= every <= high:
        every = filter_reminders.DEFAULTS[mode]  # never set: the app's default
        if enabled:
            return  # an odd answer: keep what is known
    filter_reminders.follow(db, device, mode if enabled else "off", every)


def _forget_settings(device: Device) -> None:
    from app import thermostat_settings  # it reads these too

    thermostat_settings._cache.pop(device.id, None)


def write(db: Session, device: Device, mode: str, every: int | None) -> dict[str, Any]:
    """Set the reminder: on a Cync thermostat, written to it and read back
    (refused unless it holds the new values), then kept here."""
    kept = filter_reminders.check(mode, every)
    if is_cync(device):
        on = mode != "off"
        entries: list[tuple[int, Any]] = [(ENABLED_POINT, on)]
        if kept is not None:
            entries.append((METHOD_POINT, encode_method(mode, kept)))
        api, loop, cloud_id = _connection(db, device)
        held = _call(
            lambda: cync.thermostat_write_settings_on_open(
                api, loop, cloud_id, entries, NAMES
            )
        )
        _forget_settings(device)
        took = _flag(held.get(ENABLED)) is on and (
            kept is None or decode_method(held.get(METHOD)) == (mode, kept)
        )
        if not took:
            raise CyncUnavailable(
                502,
                "the thermostat did not take the change; open Settings again to "
                "see what it holds",
            )
    return filter_reminders.save(db, device, mode, kept)


def reset(db: Session, device: Device) -> bool | None:
    """Changed Filter on the thermostat itself: True when it took it (its
    report then shows today's reset date), False when it could not be
    reached, None when it is not a Cync thermostat."""
    if not is_cync(device):
        return None
    try:
        api, loop, cloud_id = _connection(db, device)
        points = _call(
            lambda: cync.thermostat_write_on_open(
                api, loop, cloud_id, [(RESET_POINT, False)]
            )
        )
    except CyncUnavailable:
        return False
    if cync_thermostat.FILTER not in points:
        return False
    state = json.loads(device.state or "{}")
    before = (state.get("filter_reset"), state.get("filter_hours"))
    state.update(cync_thermostat.thermostat_state(points))
    device.state = json.dumps(state)
    db.commit()
    # Taken when its count started again: a new reset day, fewer hours, or none.
    hours = state.get("filter_hours")
    if not isinstance(hours, int | float):
        return state.get("filter_reset") != before[0]
    was = before[1] if isinstance(before[1], int | float) else None
    return (
        state.get("filter_reset") != before[0]
        or hours == 0
        or (was is not None and hours < was)
    )


def sync(db: Session, home_id: str, now: float | None = None) -> None:
    """Read the filter settings of the home's Cync thermostats again (at most
    every SYNC_SECONDS each), so a change made in the Cync app is followed.
    Quietly skipped while Cync is not connected."""
    if cync_live.connection(home_id) is None:
        return
    now = time.monotonic() if now is None else now
    devices = db.scalars(
        select(Device).where(
            Device.home_id == home_id,
            Device.type == "thermostat",
            Device.integration == "cync",
        )
    ).all()
    for device in devices:
        last = _synced.get(device.id)
        if not is_cync(device) or (last is not None and now - last < SYNC_SECONDS):
            continue
        _synced[device.id] = now
        try:
            store(db, device, read(db, device))
        except CyncUnavailable:
            continue


def read(db: Session, device: Device) -> dict[str, Any]:
    """The two filter settings, as the thermostat answers them."""
    api, loop, cloud_id = _connection(db, device)
    return dict(
        _call(lambda: cync.thermostat_settings_on_open(api, loop, cloud_id, NAMES))
    )
