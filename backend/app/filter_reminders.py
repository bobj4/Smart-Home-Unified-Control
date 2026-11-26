"""Thermostat air-filter reminders, the Cync thermostat's own: every so many
HVAC run hours (100 to 1500, in hundreds) or every so many months (1 to 12)
since the filter was last changed. Set in the thermostat's installer
settings (written to the thermostat, thermostat_filter.py); the time left
shows in its Info.

When one is due, the bell shows it to everyone in the home (it cannot be
dismissed) until an operator or admin presses Changed Filter, and it is sent
once by email and notification to those who chose "filter" alerts.

The count is the thermostat's: its filter report (state "filter_reset", the
date it was last reset, and "filter_hours", run hours since then), as the
Cync app shows it. Changed Filter resets the thermostat too; when that could
not reach it, the change is counted here from the day it was pressed (and
the run hours it had then) until the thermostat is reset again. A thermostat
that sends no filter report is counted here the same way.
"""

import json
import math
from datetime import UTC, date, datetime, timedelta, tzinfo
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import select
from sqlalchemy.orm import Session, object_session

from app.models import Device, FilterReminder, ScheduleSettings, utcnow

MODES = ("off", "hours", "months")
LIMITS = {"hours": (100, 1500), "months": (1, 12)}  # the Cync app's ranges
STEP = {"hours": 100, "months": 1}
DEFAULTS = {"hours": 500, "months": 3}
UNITS = {"hours": "run hours", "months": "months"}


class FilterError(ValueError):
    """A reminder setting out of range."""


def _aware(when: datetime) -> datetime:
    return when if when.tzinfo else when.replace(tzinfo=UTC)


def add_months(when: datetime, months: int) -> datetime:
    """The same day so many months on (the month's last day when shorter)."""
    total = when.month - 1 + months
    year, month = when.year + total // 12, total % 12 + 1
    following = datetime(year + month // 12, month % 12 + 1, 1, tzinfo=when.tzinfo)
    last = (following - timedelta(days=1)).day
    return when.replace(year=year, month=month, day=min(when.day, last))


def _state(device: Device) -> dict[str, Any]:
    return dict(json.loads(device.state or "{}"))


def runtime(device: Device) -> float | None:
    value = _state(device).get("filter_hours")
    return float(value) if isinstance(value, int | float) else None


def reset_date(device: Device) -> date | None:
    """The day the thermostat's filter count was last reset, if it says."""
    try:
        return date.fromisoformat(str(_state(device).get("filter_reset") or "")[:10])
    except ValueError:
        return None


def local_zone(device: Device) -> tzinfo:
    """The home's time zone (Settings > Admin > Schedules and Scenes), else
    the server's own: the thermostat reports its reset day in local time."""
    session = object_session(device)
    settings = session.get(ScheduleSettings, device.home_id) if session else None
    if settings is not None and settings.time_zone and settings.time_zone != "UTC":
        try:
            return ZoneInfo(settings.time_zone)
        except (ZoneInfoNotFoundError, ValueError):
            pass
    return datetime.now().astimezone().tzinfo or UTC


def _day_start(day: date, zone: tzinfo) -> datetime:
    return datetime(day.year, day.month, day.day, tzinfo=zone)


def _counted_here(device: Device, row: FilterReminder) -> bool:
    """True when the last change was pressed here after the thermostat's own
    last reset (it could not be reset), or it reports no filter count."""
    reset = reset_date(device)
    if reset is None:
        return True
    return _aware(row.changed_at).astimezone(local_zone(device)).date() > reset


def _start(device: Device, row: FilterReminder) -> datetime:
    reset = reset_date(device)
    if _counted_here(device, row) or reset is None:
        return _aware(row.changed_at)
    return _day_start(reset, local_zone(device))


def due_at(device: Device, row: FilterReminder) -> datetime | None:
    """When a months reminder is due; None for run hours."""
    if row.mode != "months":
        return None
    return add_months(_start(device, row), row.every)


def _hours_used(device: Device, row: FilterReminder) -> float | None:
    hours = runtime(device)
    if hours is None:
        return None
    if not _counted_here(device, row):
        return hours  # the thermostat counts from its own reset
    used = hours - (row.runtime_at_change or 0.0)
    return hours if used < 0 else used  # its counter was reset since


def status(
    device: Device, row: FilterReminder | None, now: datetime | None = None
) -> dict[str, Any]:
    """{"mode", "every", "left" (run hours, or days for months; None if
    unknown), "due", "due_at" (months), "changed_at"} for the settings, its
    Info and the bell."""
    if row is None or row.mode not in LIMITS:
        return {
            "mode": "off",
            "every": None,
            "left": None,
            "due": False,
            "due_at": None,
            "changed_at": None,
        }
    now = now or utcnow()
    left: float | None
    when = due_at(device, row)
    if when is not None:
        left = (when - now) / timedelta(days=1)
        left = math.ceil(left) if left > 0 else math.floor(left)
    else:
        used = _hours_used(device, row)
        left = None if used is None else round(row.every - used)
    return {
        "mode": row.mode,
        "every": row.every,
        "left": left,
        "due": left is not None and left <= 0,
        "due_at": when.isoformat() if when else None,
        "changed_at": _start(device, row).isoformat(),
    }


def check(mode: str, every: int | None) -> int | None:
    """The value to keep for a mode (its default when not given); raises
    FilterError when out of the thermostat's range."""
    if mode not in MODES:
        raise FilterError("choose off, run hours or months")
    if mode == "off":
        return None
    every = DEFAULTS[mode] if every is None else every
    low, high = LIMITS[mode]
    if not low <= every <= high or every % STEP[mode]:
        step = f" in steps of {STEP[mode]}" if STEP[mode] > 1 else ""
        raise FilterError(f"between {low} and {high} {UNITS[mode]}{step}")
    return every


def _row(db: Session, device: Device) -> FilterReminder:
    """The device's reminder, made if missing: counting from the
    thermostat's own reset when it reports one, or from now."""
    row = db.get(FilterReminder, device.id)
    if row is None:
        reset = reset_date(device)
        row = FilterReminder(
            device_id=device.id,
            mode="off",
            every=DEFAULTS["months"],
            changed_at=(_day_start(reset, local_zone(device)) if reset else utcnow()),
            runtime_at_change=None if reset else runtime(device),
            notified=False,
        )
        db.add(row)
    return row


def follow(db: Session, device: Device, mode: str, every: int | None) -> None:
    """Keep what the thermostat holds (read from it); nothing else changes."""
    row = db.get(FilterReminder, device.id)
    if row is None and mode == "off":
        return
    row = _row(db, device)
    if (row.mode, row.every) != (mode, every or row.every):
        row.mode, row.every = mode, every or row.every
        db.commit()


def save(db: Session, device: Device, mode: str, every: int | None) -> dict[str, Any]:
    """Keep a reminder (already written to a Cync thermostat)."""
    kept = check(mode, every)
    row = _row(db, device)
    if mode != row.mode and reset_date(device) is None:
        # Counted here: a new reminder counts from now.
        row.changed_at = utcnow()
        row.runtime_at_change = runtime(device)
        row.notified = False
    row.mode = mode
    if kept is not None:
        row.every = kept
    db.commit()
    return status(device, row)


def changed(db: Session, device: Device) -> dict[str, Any]:
    """Changed Filter: counting starts again (after the thermostat was asked
    to reset its own count, thermostat_filter.reset)."""
    row = db.get(FilterReminder, device.id)
    if row is None or row.mode not in LIMITS:
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
    """The reminders that are due. One no longer due (reset in the Cync
    app, say) may be sent again next time."""
    rows = db.execute(
        select(Device, FilterReminder)
        .join(FilterReminder, FilterReminder.device_id == Device.id)
        .where(Device.home_id == home_id, FilterReminder.mode.in_(tuple(LIMITS)))
    ).all()
    found = []
    for device, row in rows:
        shown = status(device, row)
        if shown["due"]:
            found.append((device, row, shown))
        elif row.notified:
            row.notified = False
            db.commit()
    return found


def every_text(shown: dict[str, Any]) -> str:
    """'after 500 run hours' or 'every 3 months'."""
    if shown["mode"] == "hours":
        return f"after {shown['every']} run hours"
    unit = "month" if shown["every"] == 1 else "months"
    return f"every {shown['every']} {unit}"


def notices(db: Session, home_id: str) -> list[dict[str, Any]]:
    """The bell's standing items: one per thermostat whose filter is due."""
    return [
        {
            "id": f"filter-{device.id}",
            "kind": "filter",
            "title": f"{device.name}: change the air filter",
            "body": f"Due {every_text(shown)}.",
            "at": shown["due_at"] or utcnow().isoformat(),
            "new": not row.notified,
            "sticky": True,
            "device_id": device.id,
        }
        for device, row, shown in due(db, home_id)
    ]
