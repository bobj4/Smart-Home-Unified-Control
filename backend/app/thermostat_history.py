"""A thermostat's history (its History window), from the readings the app
keeps: every RECORD_SECONDS while its state comes in, and whenever it starts
or stops heating or cooling, or its mode or set points change. Readings are
kept KEEP_DAYS. The thermostat's own energy report is not decoded yet.

Run time is worked out from the readings: the time from a heating (or
cooling) reading to the next reading, at most GAP_SECONDS (a longer gap is
missing data, not running)."""

import time
from collections import defaultdict
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.models import Device, ThermostatReading, utcnow

RECORD_SECONDS = 300
CHANGE_SECONDS = 30  # a change is recorded at once, but not more often than this
GAP_SECONDS = 900
KEEP_DAYS = 31
RUNNING = ("heating", "cooling")

# device id -> (monotonic time of the last reading, what it said)
_last: dict[str, tuple[float, tuple[Any, ...]]] = {}
_pruned: dict[str, float] = {}


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    return float(value)


def record(db: Session, device: Device, state: dict[str, Any]) -> bool:
    """Add a reading if one is due (the caller commits). Returns whether one
    was added."""
    key = (
        state.get("status"),
        state.get("mode"),
        state.get("heat_setpoint"),
        state.get("cool_setpoint"),
    )
    now = time.monotonic()
    last = _last.get(device.id)
    if last is not None:
        since = now - last[0]
        changed = last[1] != key
        if since < (CHANGE_SECONDS if changed else RECORD_SECONDS):
            return False
    _last[device.id] = (now, key)
    humidity = state.get("humidity")
    db.add(
        ThermostatReading(
            device_id=device.id,
            at=utcnow(),
            temperature=_number(state.get("current_temperature")),
            heat_setpoint=_number(state.get("heat_setpoint")),
            cool_setpoint=_number(state.get("cool_setpoint")),
            humidity=humidity
            if isinstance(humidity, int) and not isinstance(humidity, bool)
            else None,
            status=str(state.get("status") or "")[:10] or None,
            mode=str(state.get("mode") or "")[:12] or None,
        )
    )
    if now - _pruned.get(device.id, -1e9) > 3600:  # old readings, hourly
        _pruned[device.id] = now
        cutoff = utcnow() - timedelta(days=KEEP_DAYS)
        db.execute(
            delete(ThermostatReading).where(
                ThermostatReading.device_id == device.id, ThermostatReading.at < cutoff
            )
        )
    return True


def _aware(at: datetime) -> datetime:
    """SQLite gives naive times back; they were stored in UTC."""
    return at if at.tzinfo else at.replace(tzinfo=UTC)


def history(db: Session, device: Device, days: int) -> dict[str, Any]:
    """Readings for the last `days` days: every reading for one day, hourly
    averages for longer; and heating and cooling hours per day (UTC dates,
    which the page shows in local time)."""
    since = utcnow() - timedelta(days=days)
    rows = list(
        db.scalars(
            select(ThermostatReading)
            .where(
                ThermostatReading.device_id == device.id, ThermostatReading.at >= since
            )
            .order_by(ThermostatReading.at)
        )
    )
    run: dict[str, dict[str, float]] = defaultdict(
        lambda: {"heating": 0.0, "cooling": 0.0}
    )
    for row, following in zip(rows, rows[1:] + [None], strict=True):
        if row.status not in RUNNING:
            continue
        end = _aware(following.at) if following else utcnow()
        seconds = min((end - _aware(row.at)).total_seconds(), GAP_SECONDS)
        run[_aware(row.at).date().isoformat()][str(row.status)] += (
            max(seconds, 0) / 3600
        )
    points: list[dict[str, Any]] = []
    if days <= 1:
        points = [_point(_aware(r.at), [r]) for r in rows]
    else:
        hours: dict[datetime, list[ThermostatReading]] = defaultdict(list)
        for r in rows:
            hours[_aware(r.at).replace(minute=0, second=0, microsecond=0)].append(r)
        points = [_point(hour, group) for hour, group in sorted(hours.items())]
    first = db.scalars(
        select(ThermostatReading.at)
        .where(ThermostatReading.device_id == device.id)
        .order_by(ThermostatReading.at)
        .limit(1)
    ).first()
    return {
        "days": days,
        "points": points,
        "run_hours": [
            {"date": date, **{k: round(v, 2) for k, v in hours.items()}}
            for date, hours in sorted(run.items())
        ],
        "since": _aware(first).isoformat() if first else None,
    }


def _point(at: datetime, group: list[ThermostatReading]) -> dict[str, Any]:
    temps = [r.temperature for r in group if r.temperature is not None]
    last = group[-1]
    running = [r.status for r in group if r.status in RUNNING]
    return {
        "at": at.isoformat(),
        "temperature": round(sum(temps) / len(temps), 1) if temps else None,
        "heat": last.heat_setpoint,
        "cool": last.cool_setpoint,
        "humidity": last.humidity,
        "mode": last.mode,
        "status": running[-1] if running else last.status,
    }
