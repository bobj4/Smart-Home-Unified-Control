"""A Cync thermostat's own settings (the Settings window under Schedule).

The names and indexes are the Cync app's (docs/CYNC-THERMOSTAT.md). These
points are not in the thermostat's regular report, so each is asked for by
name (ReadSetting), like the schedules. Writing them has not been tried on
the owner's thermostat: a change only counts if the thermostat holds the new
value when it is read back.

Kinds: "bool" (yes/no, written as one byte), "int" (a whole number), "text"
(a number the thermostat keeps as text, such as "-1.0F": written in the same
form as it reads, so a setting it has not reported cannot be changed),
"choice" (one of CHOICES) and "info" (shown, not changed here).

The system type is different: the thermostat reports it in its regular
report (HvacTypeStatus), so it is written like the mode and checked there.
"""

import json
import time
from typing import Any

from sqlalchemy.orm import Session

from app.cync_home import CyncUnavailable, _call
from app.integrations import cync, cync_thermostat
from app.models import Device
from app.thermostat_schedule import _connection
from app.thermostat_setting_names import (
    CHOICES,
    EDITABLE,
    HVAC_SET,
    INSTALLER,
    LIMITS,
    SETTINGS,
    SYSTEM_TYPES,
)

CACHE_SECONDS = 300


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


def _whole(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.strip().lstrip("-").isdigit():
        return int(value.strip())
    return None


def _number(text: Any) -> tuple[float, str] | None:
    """'-1.0F' -> (-1.0, 'F'); '3' -> (3.0, ''); anything else -> None."""
    if isinstance(text, bool) or not isinstance(text, str | int | float):
        return None
    raw = str(text).strip()
    suffix = raw[-1:] if raw[-1:].isalpha() else ""
    try:
        return float(raw[: len(raw) - len(suffix)]), suffix.upper()
    except ValueError:
        return None


def _value(key: str, raw: Any) -> Any:
    kind = SETTINGS[key][2]
    if kind == "bool":
        return _flag(raw)
    if kind == "int":
        return _whole(raw)
    if kind == "choice":
        code = _whole(raw)
        return code if code in CHOICES[key] else None
    if kind == "info":
        return (
            raw
            if isinstance(raw, int | float | str) and not isinstance(raw, bool)
            else None
        )
    found = _number(raw)
    return f"{found[0]:g}{found[1]}" if found else None


def _result(values: dict[str, Any]) -> dict[str, Any]:
    names = {name: key for key, (name, _, _) in SETTINGS.items()}
    out: dict[str, Any] = {key: None for key in SETTINGS}
    for name, value in values.items():
        key = names.get(name)
        if key:
            out[key] = _value(key, value)
    missing = [key for key, (name, _, _) in SETTINGS.items() if name not in values]
    limits = {key: list(span) for key, span in LIMITS.items()}
    choices = {key: {str(k): v for k, v in c.items()} for key, c in CHOICES.items()}
    choices["system_type"] = {str(k): v for k, v in SYSTEM_TYPES.items()}
    return {
        "settings": out,
        "raw": values,
        "missing": missing,
        "editable": EDITABLE,
        "limits": limits,
        "choices": choices,
        "installer": sorted(INSTALLER),
    }


def _system_code(device: Device) -> int | None:
    """The system type from the thermostat's regular report."""
    label = json.loads(device.state or "{}").get("system")
    for code, name in cync_thermostat.SYSTEMS.items():
        if name == label and code in SYSTEM_TYPES:
            return code
    return None


def _with_system(device: Device, result: dict[str, Any]) -> dict[str, Any]:
    out = {k: v for k, v in result.items() if k != "raw"}
    out["settings"] = {**result["settings"], "system_type": _system_code(device)}
    return out


def read_settings(db: Session, device: Device, refresh: bool = False) -> dict[str, Any]:
    cached = _cache.get(device.id)
    if cached and not refresh and time.monotonic() - cached[0] < CACHE_SECONDS:
        return _with_system(device, cached[1])
    api, loop, cloud_id = _connection(db, device)
    names = [name for name, _, _ in SETTINGS.values()]
    values = _call(lambda: cync.thermostat_settings_on_open(api, loop, cloud_id, names))
    if not values:
        raise CyncUnavailable(502, "the thermostat did not answer")
    result = _result(values)
    _cache[device.id] = (time.monotonic(), result)
    return _with_system(device, result)


def _entry(key: str, value: Any, raw: dict[str, Any]) -> Any:
    """What to write for one change, in the form the thermostat keeps it."""
    kind = SETTINGS[key][2]
    if kind == "bool":
        return bool(value)
    if kind == "choice":
        if isinstance(value, bool) or value not in CHOICES[key]:
            raise CyncUnavailable(422, f"{key} must be one of {sorted(CHOICES[key])}")
        return int(value)
    low, high = LIMITS[key]
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise CyncUnavailable(422, f"{key} must be a number")
    if not low <= value <= high:
        raise CyncUnavailable(422, f"{key} must be from {low:g} to {high:g}")
    if kind == "int":
        if value != int(value):
            raise CyncUnavailable(422, f"{key} must be a whole number")
        return int(value)
    current = _number(raw.get(SETTINGS[key][0]))
    if current is None:
        raise CyncUnavailable(
            422,
            "the thermostat has not reported this setting, so the form to write "
            "it in is not known",
        )
    if round(value * 2) != value * 2:
        raise CyncUnavailable(422, f"{key} goes in steps of 0.5")
    return f"{value:.1f}{current[1]}"


def _held(key: str, wanted: Any, answer: Any) -> bool:
    kind = SETTINGS[key][2]
    if kind == "bool":
        return _flag(answer) is bool(wanted)
    if kind in ("int", "choice"):
        return _whole(answer) == wanted
    got, sent = _number(answer), _number(wanted)
    return got is not None and sent is not None and abs(got[0] - sent[0]) < 0.05


def write_settings(
    db: Session, device: Device, changes: dict[str, Any]
) -> dict[str, Any]:
    """Change settings, then read them back; refused unless the thermostat
    now holds every new value."""
    if not changes or any(key not in EDITABLE for key in changes):
        raise CyncUnavailable(422, "nothing that can be changed here")
    if "system_type" in changes:
        if len(changes) > 1:
            raise CyncUnavailable(422, "change the system type on its own")
        return write_system_type(db, device, changes["system_type"])
    raw: dict[str, Any] = {}
    if any(SETTINGS[key][2] == "text" for key in changes):
        read_settings(db, device)  # the form each text setting is kept in
        cached = _cache.get(device.id)
        raw = cached[1].get("raw", {}) if cached else {}
    wanted = {key: _entry(key, value, raw) for key, value in changes.items()}
    api, loop, cloud_id = _connection(db, device)
    entries: list[tuple[int, Any]] = [(SETTINGS[k][1], v) for k, v in wanted.items()]
    names = [SETTINGS[key][0] for key in wanted]
    held = _call(
        lambda: cync.thermostat_write_settings_on_open(
            api, loop, cloud_id, entries, names
        )
    )
    _cache.pop(device.id, None)
    if not all(_held(k, v, held.get(SETTINGS[k][0])) for k, v in wanted.items()):
        raise CyncUnavailable(
            502,
            "the thermostat did not take the change; open Settings again to see "
            "what it holds",
        )
    return read_settings(db, device, refresh=True)


def write_system_type(db: Session, device: Device, code: Any) -> dict[str, Any]:
    """Write HVAC_Type_Set and check the thermostat's report shows it; the
    stored state (its modes follow the system) is updated from that report."""
    if isinstance(code, bool) or code not in SYSTEM_TYPES:
        raise CyncUnavailable(422, "unknown system type")
    api, loop, cloud_id = _connection(db, device)
    points = _call(
        lambda: cync.thermostat_write_on_open(api, loop, cloud_id, [(HVAC_SET, code)])
    )
    if points.get(cync_thermostat.HVAC_TYPE) != code:
        raise CyncUnavailable(
            502, "the thermostat did not take the change; check it in the Cync app"
        )
    state = json.loads(device.state or "{}")
    state.update(cync_thermostat.thermostat_state(points))
    device.state = json.dumps(state)
    db.commit()
    return read_settings(db, device)
