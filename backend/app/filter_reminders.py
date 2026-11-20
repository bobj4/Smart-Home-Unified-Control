"""Thermostat air-filter reminders, as in the Cync app: every so many HVAC
run hours, or every so many days, since the filter was last changed. Set in
the thermostat's installer settings; the time left shows in its Info.

When one is due, the bell shows it to everyone in the home (it cannot be
dismissed) until an operator or admin presses Changed Filter, and it is sent
once by email and notification to those who chose "filter" alerts. Run
hours come from the thermostat's own filter counter (state "filter_hours");
the count at the last change is kept, so its own reset does not matter.
"""

import json
import math
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Device, FilterReminder, utcnow

MODES = ("off", "hours", "days")
LIMITS = {"hours": (50, 5000), "days": (7, 730)}
DEFAULTS = {"hours": 500, "days": 90}


class FilterError(ValueError):
    """A reminder setting out of range."""


def _aware(when: datetime) -> datetime:
    return when if when.tzinfo else when.replace(tzinfo=UTC)


def runtime(device: Device) -> float | None:
    value = json.loads(device.state or "{}").get("filter_hours")
    return float(value) if isinstance(value, int | float) else None


def status(
    device: Device, row: FilterReminder | None, now: datetime | None = None
) -> dict[str, Any]:
    """{"mode", "every", "left" (hours or days; None if unknown), "due",
    "changed_at"} for the settings, its Info and the bell."""
    if row is None or row.mode == "off":
        return {
            "mode": "off",
            "every": None,
            "left": None,
            "due": False,
            "changed_at": None,
        }
    now = now or utcnow()
    left: float | None
    if row.mode == "days":
        left = row.every - (now - _aware(row.changed_at)) / timedelta(days=1)
        left = math.ceil(left) if left > 0 else math.floor(left)
    else:
        hours = runtime(device)
        if hours is None:
            left = None  # the thermostat has not reported its run time
        else:
            used = hours - (row.runtime_at_change or 0.0)
            used = hours if used < 0 else used  # its own counter was reset
            left = round(row.every - used)
    return {
        "mode": row.mode,
        "every": row.every,
        "left": left,
        "due": left is not None and left <= 0,
        "changed_at": _aware(row.changed_at).isoformat(),
    }


def save(db: Session, device: Device, mode: str, every: int | None) -> dict[str, Any]:
    if mode not in MODES:
        raise FilterError("choose off, run hours or days")
    row = db.get(FilterReminder, device.id)
    if mode == "off":
        if row is not None:
            row.mode = "off"
            row.notified = False
        db.commit()
        return status(device, row)
    every = DEFAULTS[mode] if every is None else every
    low, high = LIMITS[mode]
    if not low <= every <= high:
        unit = "run hours" if mode == "hours" else "days"
        raise FilterError(f"between {low} and {high} {unit}")
    if row is None:
        row = FilterReminder(device_id=device.id)
        db.add(row)
    if row.mode != mode or row.changed_at is None:  # counting starts now
        row.changed_at = utcnow()
        row.runtime_at_change = runtime(device)
        row.notified = False
    row.mode, row.every = mode, every
    db.commit()
    return status(device, row)


def changed(db: Session, device: Device) -> dict[str, Any]:
    """Changed Filter: counting starts again."""
    row = db.get(FilterReminder, device.id)
    if row is None or row.mode == "off":
        raise FilterError("this thermostat has no filter reminder")
    row.changed_at = utcnow()
    row.runtime_at_change = runtime(device)
    row.notified = False
    db.commit()
    return status(device, row)


def for_device(db: Session, device: Device) -> dict[str, Any]:
    return status(device, db.get(FilterReminder, device.id))


def due(
    db: Session, home_id: str
) -> list[tuple[Device, FilterReminder, dict[str, Any]]]:
    rows = db.execute(
        select(Device, FilterReminder)
        .join(FilterReminder, FilterReminder.device_id == Device.id)
        .where(Device.home_id == home_id, FilterReminder.mode != "off")
    ).all()
    found = []
    for device, row in rows:
        shown = status(device, row)
        if shown["due"]:
            found.append((device, row, shown))
    return found


def notices(db: Session, home_id: str) -> list[dict[str, Any]]:
    """The bell's standing items: one per thermostat whose filter is due."""
    return [
        {
            "id": f"filter-{device.id}",
            "kind": "filter",
            "title": f"{device.name}: change the air filter",
            "body": (
                f"Due after {shown['every']} run hours."
                if shown["mode"] == "hours"
                else f"Due every {shown['every']} days."
            ),
            "at": (
                _aware(row.changed_at) + timedelta(days=row.every)
                if row.mode == "days"
                else utcnow()
            ).isoformat(),
            "new": not row.notified,
            "sticky": True,
            "device_id": device.id,
        }
        for device, row, shown in due(db, home_id)
    ]
