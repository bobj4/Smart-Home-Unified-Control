"""A Cync thermostat's schedules over the live connection: its weekly heat,
cool and auto set point schedules and which sensors it reads when.

Reading asks for each setting by name and changes nothing. Writing sends
the chosen days in one set packet, then reads them back: the change only
counts if the thermostat now holds exactly what was sent (writing schedules
had not been tried on the owner's thermostat before this)."""

import copy
import json
import time
from typing import Any

from sqlalchemy.orm import Session

from app import cync_live
from app.cync_home import CyncUnavailable, _call, _login_for_home
from app.integrations import cync, cync_schedule
from app.models import Device

SCHEDULE_CACHE_SECONDS = 300
# device id -> (time read, schedule); reading all 28 takes several seconds
_schedule_cache: dict[str, tuple[float, dict[str, Any]]] = {}


def _sensor_label(state: dict[str, Any], pin: str | None) -> str:
    for sensor in state.get("sensors") or []:
        if pin and sensor.get("pin") == pin:
            return str(sensor.get("name") or "Remote sensor")
    return f"Remote sensor {pin}" if pin else "Remote sensor"


def _connection(db: Session, device: Device) -> tuple[Any, Any, int]:
    cloud_id = json.loads(device.capabilities or "{}").get("cloud_id")
    if device.type != "thermostat" or cloud_id is None:
        raise CyncUnavailable(409, "schedules are read from Cync thermostats only")
    _login_for_home(db, device.home_id)
    live = cync_live.connection(device.home_id)
    if live is None:
        raise CyncUnavailable(503, "Cync is still connecting; try again in a minute")
    return live[0], live[1], int(cloud_id)


def _label_sensors(state: dict[str, Any], periods: list[dict[str, Any]] | None) -> None:
    for period in periods or []:
        if period["read"] == "sensor":
            period["label"] = _sensor_label(state, period.get("pin"))


def read_schedule(db: Session, device: Device, refresh: bool = False) -> dict[str, Any]:
    """The thermostat's weekly heat/cool/auto schedules and its sensor
    schedule, read over the live connection (no setting changes)."""
    cached = _schedule_cache.get(device.id)
    fresh = cached and time.monotonic() - cached[0] < SCHEDULE_CACHE_SECONDS
    if cached and fresh and not refresh:
        return cached[1]
    api, loop, cloud_id = _connection(db, device)
    names = cync_schedule.read_names()
    values = _call(lambda: cync.thermostat_settings_on_open(api, loop, cloud_id, names))
    if not values:
        raise CyncUnavailable(502, "the thermostat did not answer")
    try:
        week = cync_schedule.week_from_settings(values)
    except cync_schedule.ScheduleError as error:
        raise CyncUnavailable(502, f"could not read a schedule: {error}") from None
    state = json.loads(device.state or "{}")
    for periods in week["sensors"].values():
        _label_sensors(state, periods)
    result = {"week": week, "missing": [n for n in names if n not in values]}
    _schedule_cache[device.id] = (time.monotonic(), result)
    return result


def check_day(
    kind: str,
    periods: list[dict[str, Any]],
    state: dict[str, Any],
    bounds: tuple[float | None, float | None],
) -> None:
    """Refuse what the thermostat must not be given: set points outside the
    safety limits, cooling not above heating, unknown remote sensors."""
    low, high = bounds
    for period in periods:
        keys = (
            ("heat", "cool") if kind == "auto" else (kind,) if kind != "sensors" else ()
        )
        for key in keys:
            value = period.get(key)
            if isinstance(value, bool) or not isinstance(value, int | float):
                raise cync_schedule.ScheduleError(f"{key} must be a number")
            if low is None or high is None or not low <= value <= high:
                raise cync_schedule.ScheduleError(
                    f"set points must be within the safety limits {low}-{high}"
                )
        if kind == "auto" and not period["heat"] < period["cool"]:
            raise cync_schedule.ScheduleError("cooling must be set above heating")
        if kind == "sensors" and period.get("read") == "sensor":
            pins = {x.get("pin") for x in state.get("sensors") or [] if x.get("pin")}
            if period.get("pin") not in pins:
                raise cync_schedule.ScheduleError(
                    "that remote sensor is not on the thermostat"
                )


def write_schedule(
    db: Session,
    device: Device,
    kind: str,
    days: list[str],
    periods: list[dict[str, Any]],
    bounds: tuple[float | None, float | None],
) -> dict[str, Any]:
    """Give the chosen days of one schedule these periods (none: clear them),
    then read them back. Returns the schedule as read from the thermostat."""
    state = json.loads(device.state or "{}")
    unit = "C" if state.get("device_unit") == "C" else "F"
    try:
        check_day(kind, periods, state, bounds)
        raw = cync_schedule.encode_day(kind, periods, unit)
    except cync_schedule.ScheduleError as error:
        raise CyncUnavailable(422, str(error)) from None
    api, loop, cloud_id = _connection(db, device)
    known = _schedule_cache.get(device.id)
    entries = [(cync_schedule.day_index(kind, day), raw) for day in days]
    names = [cync_schedule.day_name(kind, day) for day in days]
    held = _call(
        lambda: cync.thermostat_write_settings_on_open(
            api, loop, cloud_id, entries, names
        )
    )
    _schedule_cache.pop(device.id, None)  # what the thermostat holds now is unknown
    wrong = [
        day
        for day, name in zip(days, names, strict=True)
        if name not in held or not cync_schedule.same_day(kind, periods, held[name])
    ]
    if wrong:
        raise CyncUnavailable(
            502,
            "the thermostat did not store the schedule for "
            + ", ".join(
                cync_schedule.DAY_NAMES[cync_schedule.DAYS.index(d)] for d in wrong
            )
            + "; open the schedule again to see what it holds",
        )
    if known is None:
        return read_schedule(db, device, refresh=True)
    # The rest of the week is as read before; these days as read back now.
    result = copy.deepcopy(known[1])
    for day, name in zip(days, names, strict=True):
        value = cync_schedule.setting_bytes(held[name])
        if value is None:
            result["week"][kind][day] = None
        elif kind == "sensors":
            result["week"][kind][day] = cync_schedule.parse_sensor_schedule(value)
            _label_sensors(state, result["week"][kind][day])
        else:
            result["week"][kind][day] = cync_schedule.parse_schedule(kind, value)
    _schedule_cache[device.id] = (time.monotonic(), result)
    return result
