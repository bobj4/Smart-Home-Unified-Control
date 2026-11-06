"""A Cync thermostat's own settings (the Settings window under Schedule):
Early On, the unit its screen shows and daylight saving time can be
changed; the installer settings are shown as the thermostat reports them.

The names and indexes are the Cync app's (docs/CYNC-THERMOSTAT.md). These
points are not in the thermostat's regular report, so each is asked for by
name (ReadSetting), like the schedules. Writing them has not been tried on
the owner's thermostat: a change only counts if the thermostat holds the new
value when it is read back.
"""

import time
from typing import Any

from sqlalchemy.orm import Session

from app.cync_home import CyncUnavailable, _call
from app.integrations import cync
from app.models import Device
from app.thermostat_schedule import _connection

CACHE_SECONDS = 300
# key: (setting name, data point, kind); "bool" ones can be changed here.
SETTINGS: dict[str, tuple[str, int, str]] = {
    "early_on": ("EarlyON_Enable", 23, "bool"),
    "celsius": ("Temperature_Unit", 20, "bool"),  # its screen: true = Celsius
    "auto_dst": ("Auto_DST", 118, "bool"),
    "dehumidify": ("Dehumidification_Enable", 19, "info"),
    "dehumidify_to": ("Dehumidification_Setpoint", 18, "info"),
    "min_fan_runtime": ("Min_Fan_Runtime", 26, "info"),
    "temperature_offset": ("Temperature_Offset", 21, "info"),
    "humidity_offset": ("Humidity_Offset", 22, "info"),
    "auto_deadband": ("Auto_Mode_Deadband", 15, "info"),
    "heat_pump_changeover": ("HeatPump_Changeover_Mode", 27, "info"),
}
EDITABLE = [key for key, (_, _, kind) in SETTINGS.items() if kind == "bool"]

# device id -> (time read, settings)
_cache: dict[str, tuple[float, dict[str, Any]]] = {}


def _flag(value: Any) -> bool | None:
    """A yes/no setting as the thermostat answers it (true/false or 1/0)."""
    if isinstance(value, bool):
        return value
    if isinstance(value, int) and value in (0, 1):
        return bool(value)
    if isinstance(value, str) and value.strip().lower() in ("true", "false", "1", "0"):
        return value.strip().lower() in ("true", "1")
    return None


def _shown(value: Any) -> Any:
    """An installer setting for display: plain values only."""
    if value is None or isinstance(value, bool | int | float):
        return value
    if isinstance(value, str):
        return value[:40]
    return None  # a list or object: not something this window shows


def _result(values: dict[str, Any]) -> dict[str, Any]:
    names = {name: key for key, (name, _, _) in SETTINGS.items()}
    out: dict[str, Any] = {key: None for key in SETTINGS}
    for name, value in values.items():
        key = names.get(name)
        if key:
            out[key] = _flag(value) if key in EDITABLE else _shown(value)
    missing = [key for key, (name, _, _) in SETTINGS.items() if name not in values]
    return {"settings": out, "missing": missing, "editable": EDITABLE}


def read_settings(db: Session, device: Device, refresh: bool = False) -> dict[str, Any]:
    cached = _cache.get(device.id)
    if cached and not refresh and time.monotonic() - cached[0] < CACHE_SECONDS:
        return cached[1]
    api, loop, cloud_id = _connection(db, device)
    names = [name for name, _, _ in SETTINGS.values()]
    values = _call(lambda: cync.thermostat_settings_on_open(api, loop, cloud_id, names))
    if not values:
        raise CyncUnavailable(502, "the thermostat did not answer")
    result = _result(values)
    _cache[device.id] = (time.monotonic(), result)
    return result


def write_settings(
    db: Session, device: Device, changes: dict[str, bool]
) -> dict[str, Any]:
    """Change yes/no settings, then read them back; refused unless the
    thermostat now holds every new value."""
    if not changes or any(key not in EDITABLE for key in changes):
        raise CyncUnavailable(422, "nothing that can be changed here")
    api, loop, cloud_id = _connection(db, device)
    entries: list[tuple[int, Any]] = [
        (SETTINGS[key][1], bool(value)) for key, value in changes.items()
    ]
    names = [SETTINGS[key][0] for key in changes]
    held = _call(
        lambda: cync.thermostat_write_settings_on_open(
            api, loop, cloud_id, entries, names
        )
    )
    _cache.pop(device.id, None)
    wrong = [
        key
        for key, value in changes.items()
        if _flag(held.get(SETTINGS[key][0])) is not bool(value)
    ]
    if wrong:
        raise CyncUnavailable(
            502,
            "the thermostat did not take the change; open Settings again to see "
            "what it holds",
        )
    return read_settings(db, device, refresh=True)
