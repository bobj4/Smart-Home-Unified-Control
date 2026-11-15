"""What each device alerts about: the bell beside each device in Settings >
Devices (replacing Admin > Alerts' home-wide settings).

Every device has a master switch. Devices with more to choose have their
own settings (a popup); the rest only turn their alert on and off (the
bell itself):
  garage_door   open longer than open_minutes; close it after
                auto_close_minutes (0: never); obstruction; offline_minutes
  water_heater  problems (a new Rheem alert); offline_minutes
  thermostat    offline_minutes; too_cold / too_hot (°, None: off)
  others        offline (after OFFLINE_MINUTES)
Minutes of 0 turn that alert off. Devices nobody has set use DEFAULTS:
garage doors, water heaters and thermostats on, the rest off (a light
switched off at the wall is not news).
"""

import json
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Device, DeviceAlert

OFFLINE_MINUTES = 15
# Each setting: (default, kind, low, high); kind "minutes", "bool" or
# "degrees" (None allowed).
SETTINGS: dict[str, dict[str, tuple[Any, str, int, int]]] = {
    "garage_door": {
        "open_minutes": (15, "minutes", 0, 1440),
        "auto_close_minutes": (0, "minutes", 0, 1440),
        "obstruction": (True, "bool", 0, 1),
        "offline_minutes": (OFFLINE_MINUTES, "minutes", 0, 1440),
    },
    "water_heater": {
        "problems": (True, "bool", 0, 1),
        "offline_minutes": (OFFLINE_MINUTES, "minutes", 0, 1440),
    },
    "thermostat": {
        "offline_minutes": (OFFLINE_MINUTES, "minutes", 0, 1440),
        "too_cold": (None, "degrees", -20, 120),
        "too_hot": (None, "degrees", -20, 120),
    },
}
ON_BY_DEFAULT = ("garage_door", "water_heater", "thermostat")


class DeviceAlertError(Exception):
    def __init__(self, reason: str) -> None:
        self.reason = reason


def has_popup(device_type: str) -> bool:
    return device_type in SETTINGS


def defaults(device_type: str) -> dict[str, Any]:
    return {key: rule[0] for key, rule in SETTINGS.get(device_type, {}).items()}


def config(device: Device, row: DeviceAlert | None) -> dict[str, Any]:
    """{"enabled", "popup", "settings"} for a device (its defaults if unset)."""
    settings = defaults(device.type)
    enabled = device.type in ON_BY_DEFAULT
    if row is not None:
        enabled = bool(row.enabled)
        try:
            saved = json.loads(row.settings or "{}")
        except ValueError:
            saved = {}
        settings.update({k: v for k, v in saved.items() if k in settings})
    return {"enabled": enabled, "popup": has_popup(device.type), "settings": settings}


def for_home(db: Session, home_id: str) -> dict[str, dict[str, Any]]:
    devices = db.scalars(select(Device).where(Device.home_id == home_id)).all()
    rows = {
        r.device_id: r
        for r in db.scalars(
            select(DeviceAlert).where(
                DeviceAlert.device_id.in_([d.id for d in devices])
            )
        )
    }
    return {d.id: config(d, rows.get(d.id)) for d in devices}


def for_device(db: Session, device: Device) -> dict[str, Any]:
    return config(device, db.get(DeviceAlert, device.id))


def _check(device_type: str, settings: dict[str, Any]) -> dict[str, Any]:
    rules = SETTINGS.get(device_type, {})
    out = {}
    for key, value in settings.items():
        if key not in rules:
            raise DeviceAlertError(f"{key} is not an alert setting for this device")
        _, kind, low, high = rules[key]
        if kind == "bool":
            if not isinstance(value, bool):
                raise DeviceAlertError(f"{key} is on or off")
        elif kind == "degrees" and value is None:
            pass
        elif (
            not isinstance(value, int)
            or isinstance(value, bool)
            or not low <= value <= high
        ):
            raise DeviceAlertError(f"{key} is a whole number from {low} to {high}")
        out[key] = value
    return out


def save(
    db: Session, device: Device, enabled: bool | None, settings: dict[str, Any] | None
) -> dict[str, Any]:
    row = db.get(DeviceAlert, device.id)
    current = config(device, row)
    merged = {**current["settings"], **_check(device.type, settings or {})}
    cold, hot = merged.get("too_cold"), merged.get("too_hot")
    if cold is not None and hot is not None and cold >= hot:
        raise DeviceAlertError("too cold must be below too hot")
    if row is None:
        row = DeviceAlert(device_id=device.id)
        db.add(row)
    row.enabled = current["enabled"] if enabled is None else enabled
    row.settings = json.dumps(merged)
    db.commit()
    return config(device, row)
