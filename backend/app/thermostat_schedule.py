"""Reading a Cync thermostat's schedules over the live connection: its weekly
heat, cool and auto set point schedules and which sensors it reads when.
Read-only: asking for a setting changes nothing on the thermostat."""

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


def read_schedule(db: Session, device: Device, refresh: bool = False) -> dict[str, Any]:
    """The thermostat's weekly heat/cool/auto schedules and its sensor
    schedule, read over the live connection (no setting changes)."""
    cached = _schedule_cache.get(device.id)
    fresh = cached and time.monotonic() - cached[0] < SCHEDULE_CACHE_SECONDS
    if cached and fresh and not refresh:
        return cached[1]
    cloud_id = json.loads(device.capabilities or "{}").get("cloud_id")
    if device.type != "thermostat" or cloud_id is None:
        raise CyncUnavailable(409, "schedules are read from Cync thermostats only")
    _login_for_home(db, device.home_id)
    live = cync_live.connection(device.home_id)
    if live is None:
        raise CyncUnavailable(503, "Cync is still connecting; try again in a minute")
    names = cync_schedule.read_names()
    values = _call(
        lambda: cync.thermostat_settings_on_open(live[0], live[1], int(cloud_id), names)
    )
    if not values:
        raise CyncUnavailable(502, "the thermostat did not answer")
    try:
        week = cync_schedule.week_from_settings(values)
    except cync_schedule.ScheduleError as error:
        raise CyncUnavailable(502, f"could not read a schedule: {error}") from None
    state = json.loads(device.state or "{}")
    for periods in week["sensors"].values():
        for period in periods or []:
            if period["read"] == "sensor":
                period["label"] = _sensor_label(state, period.get("pin"))
    result = {"week": week, "missing": [n for n in names if n not in values]}
    _schedule_cache[device.id] = (time.monotonic(), result)
    return result
