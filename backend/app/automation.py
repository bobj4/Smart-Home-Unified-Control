"""Schedules and Scenes, run by this server (not a device's own schedule,
which its own buttons still set).

A scene is a list of steps run together: a command to a device, or to a
group (its lights and plugs). A schedule runs a scene and/or its own steps
at a time of day, or at sunrise or sunset with an offset, on chosen
weekdays, in the home's time zone (Admin > Schedules and Scenes, where its
location for the sun, who may edit, and a pause switch are set too).

A step is checked when saved (the device or group is in the home and the
command fits, each step seeing the state the earlier ones leave) and again
when it runs, through the same path as a command from the app
(apply_command: limits, integrations off, the audit log). One failing step
does not stop the others.

The scheduler wakes every TICK_SECONDS, runs what is due, and works out
each schedule's next run. A run missed by more than MISSED_GRACE (the
server was off) is skipped, not run late.
"""

import asyncio
import json
import logging
import re
from datetime import UTC, date, datetime, time, timedelta, tzinfo
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError, available_timezones

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import sun
from app.audit import record_event
from app.authorization import require_role
from app.db_config import SessionLocal
from app.groups import GROUP_COMMANDS, members
from app.models import (
    Device,
    DeviceGroup,
    Role,
    Scene,
    Schedule,
    ScheduleSettings,
    utcnow,
)

log = logging.getLogger(__name__)
TICK_SECONDS = 20
MISSED_GRACE = timedelta(minutes=15)
MAX_STEPS = 40
EDITORS = {"admin": Role.ADMIN, "operator": Role.OPERATOR, "member": Role.MEMBER}
TIME = re.compile(r"^([01]\d|2[0-3]):([0-5]\d)$")
SUN_KINDS = ("sunrise", "sunset")


class AutomationError(Exception):
    def __init__(self, status_code: int, reason: str) -> None:
        self.status_code = status_code
        self.reason = reason


# ------------------------------------------------------------ settings


def settings_for(db: Session, home_id: str) -> ScheduleSettings:
    row = db.get(ScheduleSettings, home_id)
    if row is None:
        row = ScheduleSettings(home_id=home_id, time_zone="UTC", editors="admin")
        db.add(row)
        db.flush()
    return row


def zone(name: str) -> tzinfo:
    if name == "UTC":
        return UTC
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError):
        return UTC


def valid_zone(name: str) -> bool:
    return name == "UTC" or name in available_timezones()


def settings_out(row: ScheduleSettings) -> dict[str, Any]:
    """The settings, and today's sunrise and sunset there (local time, to
    check the location), when the location is set."""
    sun_today = None
    if row.latitude is not None and row.longitude is not None:
        tz = zone(row.time_zone)
        rise, sets = sun.times(
            utcnow().astimezone(tz).date(), row.latitude, row.longitude
        )
        sun_today = {
            "sunrise": rise.astimezone(tz).isoformat() if rise else None,
            "sunset": sets.astimezone(tz).isoformat() if sets else None,
        }
    return {
        "time_zone": row.time_zone,
        "latitude": row.latitude,
        "longitude": row.longitude,
        "editors": row.editors,
        "paused": bool(row.paused),
        "sun_today": sun_today,
    }


def save_settings(
    db: Session, home_id: str, changes: dict[str, Any]
) -> ScheduleSettings:
    row = settings_for(db, home_id)
    if "time_zone" in changes:
        if not valid_zone(str(changes["time_zone"])):
            raise AutomationError(422, "not a time zone this server knows")
        row.time_zone = str(changes["time_zone"])
    for key in ("latitude", "longitude"):
        if key in changes:
            setattr(row, key, changes[key])
    if (row.latitude is None) != (row.longitude is None):
        raise AutomationError(422, "give both latitude and longitude, or neither")
    if "editors" in changes:
        row.editors = str(changes["editors"])
    if "paused" in changes:
        row.paused = bool(changes["paused"])
    db.flush()
    for schedule in db.scalars(select(Schedule).where(Schedule.home_id == home_id)):
        schedule.next_run_at = next_run(schedule, row, utcnow())
    db.commit()
    return row


def require_editor(db: Session, user_id: str, home_id: str) -> None:
    """Making and changing scenes and schedules: the role the admins chose."""
    minimum = EDITORS.get(settings_for(db, home_id).editors, Role.ADMIN)
    require_role(db, user_id, home_id, minimum)


# ------------------------------------------------------------ steps


def _device_command(command: str, payload: dict[str, Any]) -> Any:
    from app.routes.devices import DeviceCommand  # the app's own command shape

    return DeviceCommand(command=command, payload=payload)


def check_steps(
    db: Session, home_id: str, steps: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """The steps, checked (see the module notes); raises AutomationError."""
    from app.routes.devices import CommandRejected, _new_state

    if len(steps) > MAX_STEPS:
        raise AutomationError(422, f"at most {MAX_STEPS} steps")
    states: dict[str, dict[str, Any]] = {}  # device id -> state after its steps
    out = []
    for number, step in enumerate(steps, start=1):
        kind, target = step.get("kind"), str(step.get("id", ""))
        command, payload = str(step.get("command", "")), step.get("payload") or {}
        if not isinstance(payload, dict):
            raise AutomationError(422, f"step {number}: payload must be an object")
        if kind == "group":
            group = db.get(DeviceGroup, target)
            if group is None or group.home_id != home_id:
                raise AutomationError(422, f"step {number}: no such group in this home")
            if command not in GROUP_COMMANDS:
                raise AutomationError(
                    422,
                    f"step {number}: groups take on, off, brightness, white and color",
                )
        elif kind == "device":
            device = db.get(Device, target)
            if device is None or device.home_id != home_id:
                raise AutomationError(
                    422, f"step {number}: no such device in this home"
                )
            try:
                cmd = _device_command(command, payload)
            except ValueError:
                raise AutomationError(422, f"step {number}: not a command") from None
            saved = device.state
            try:
                if device.id in states:
                    device.state = json.dumps(states[device.id])
                states[device.id] = _new_state(db, device, cmd)
            except CommandRejected as rejected:
                raise AutomationError(
                    422, f"step {number} ({device.name}): {rejected.reason}"
                ) from None
            finally:
                device.state = saved
        else:
            raise AutomationError(422, f"step {number}: a device or a group")
        out.append({"kind": kind, "id": target, "command": command, "payload": payload})
    return out


def run_steps(
    db: Session,
    home_id: str,
    steps: list[dict[str, Any]],
    user_id: str | None,
    why: str,
) -> dict[str, Any]:
    """Run each step; {"done": n, "failed": [{"name", "reason"}]}."""
    from app.routes.devices import CommandRejected, apply_command

    audit = {"user_id": user_id, "home_id": home_id, "ip_address": None}
    done, failed = 0, []
    for step in steps:
        cmd = _device_command(step["command"], step.get("payload") or {})
        if step["kind"] == "group":
            group = db.get(DeviceGroup, step["id"])
            if group is None or group.home_id != home_id:
                failed.append({"name": "a removed group", "reason": "no longer here"})
                continue
            targets = [
                d
                for d in members(db, group)
                if d.type == "light"
                or (d.type == "plug" and step["command"] in ("turn_on", "turn_off"))
            ]
        else:
            device = db.get(Device, step["id"])
            if device is None or device.home_id != home_id:
                failed.append({"name": "a removed device", "reason": "no longer here"})
                continue
            targets = [device]
        for device in targets:
            try:
                apply_command(db, device, cmd, audit)
                done += 1
            except CommandRejected as rejected:
                db.rollback()
                failed.append({"name": device.name, "reason": rejected.reason})
    record_event(
        db,
        "automation_run",
        user_id=user_id,
        home_id=home_id,
        details={"what": why, "done": done, "failed": len(failed)},
    )
    return {"done": done, "failed": failed}


def summary(result: dict[str, Any]) -> str:
    failed = result["failed"]
    if not failed:
        return f"Done ({result['done']} {'command' if result['done'] == 1 else 'commands'})"
    first = failed[0]
    more = f" and {len(failed) - 1} more" if len(failed) > 1 else ""
    return f"{result['done']} done; {first['name']}: {first['reason']}{more}"[:500]


# ------------------------------------------------------------ scenes


def scene_out(scene: Scene) -> dict[str, Any]:
    return {
        "id": scene.id,
        "name": scene.name,
        "steps": json.loads(scene.steps or "[]"),
    }


def run_scene(
    db: Session, scene: Scene, user_id: str | None, why: str
) -> dict[str, Any]:
    return run_steps(db, scene.home_id, json.loads(scene.steps or "[]"), user_id, why)


# ------------------------------------------------------------ schedules


def check_trigger(trigger: dict[str, Any]) -> dict[str, Any]:
    kind = trigger.get("kind")
    if kind == "time":
        at = str(trigger.get("at", ""))
        if not TIME.match(at):
            raise AutomationError(422, 'the time must look like "07:30" (24-hour)')
        return {"kind": "time", "at": at}
    if kind in SUN_KINDS:
        offset = trigger.get("offset", 0)
        if (
            not isinstance(offset, int)
            or isinstance(offset, bool)
            or not -240 <= offset <= 240
        ):
            raise AutomationError(422, "the offset is minutes, from -240 to 240")
        return {"kind": kind, "offset": offset}
    raise AutomationError(422, "run at a time, at sunrise or at sunset")


def check_days(days: list[Any]) -> list[int]:
    found = sorted({d for d in days if isinstance(d, int) and not isinstance(d, bool)})
    if not found or any(not 0 <= d <= 6 for d in found):
        raise AutomationError(422, "pick at least one day")
    return found


def _when(
    trigger: dict[str, Any], day: date, row: ScheduleSettings, tz: tzinfo
) -> datetime | None:
    if trigger["kind"] == "time":
        hour, minute = (int(x) for x in trigger["at"].split(":"))
        local = datetime.combine(day, time(hour, minute), tzinfo=tz)
        return local.astimezone(UTC)
    if row.latitude is None or row.longitude is None:
        return None
    rise, sets = sun.times(day, row.latitude, row.longitude)
    event = rise if trigger["kind"] == "sunrise" else sets
    if event is None:
        return None
    return event + timedelta(minutes=int(trigger.get("offset", 0)))


def next_run(
    schedule: Schedule, row: ScheduleSettings, after: datetime
) -> datetime | None:
    """The first run after `after` (UTC), or None (off, or the sun needs the
    home's location)."""
    if not schedule.enabled:
        return None
    trigger = json.loads(schedule.trigger)
    days = set(json.loads(schedule.days or "[]"))
    tz = zone(row.time_zone)
    first = after.astimezone(tz).date() - timedelta(days=1)
    for offset in range(10):
        day = first + timedelta(days=offset)
        if day.weekday() not in days:
            continue
        when = _when(trigger, day, row, tz)
        if when is not None and when > after:
            return when
    return None


def schedule_out(schedule: Schedule, row: ScheduleSettings) -> dict[str, Any]:
    tz = zone(row.time_zone)
    trigger = json.loads(schedule.trigger)

    def local(value: datetime | None) -> str | None:
        if value is None:
            return None
        aware = value if value.tzinfo else value.replace(tzinfo=UTC)
        return aware.astimezone(tz).isoformat()

    waiting = None
    if schedule.enabled and schedule.next_run_at is None:
        waiting = (
            "needs the home's location (Admin > Schedules and Scenes)"
            if trigger["kind"] in SUN_KINDS and row.latitude is None
            else "no run in the coming days"
        )
    return {
        "id": schedule.id,
        "name": schedule.name,
        "enabled": bool(schedule.enabled),
        "trigger": trigger,
        "days": json.loads(schedule.days or "[]"),
        "scene_id": schedule.scene_id,
        "steps": json.loads(schedule.steps or "[]"),
        "next_run_at": local(schedule.next_run_at),
        "last_run_at": local(schedule.last_run_at),
        "last_result": schedule.last_result,
        "waiting": waiting,
        "paused": bool(row.paused),
    }


def run_schedule(
    db: Session, schedule: Schedule, user_id: str | None, why: str
) -> dict[str, Any]:
    steps: list[dict[str, Any]] = []
    if schedule.scene_id:
        scene = db.get(Scene, schedule.scene_id)
        if scene is not None:
            steps += json.loads(scene.steps or "[]")
    steps += json.loads(schedule.steps or "[]")
    return run_steps(db, schedule.home_id, steps, user_id, why)


def run_due(db: Session, now: datetime | None = None) -> int:
    """Run every schedule that is due; returns how many ran."""
    now = now or utcnow()
    ran = 0
    due = list(
        db.scalars(
            select(Schedule).where(
                Schedule.enabled.is_(True), Schedule.next_run_at <= now
            )
        )
    )
    for schedule in due:
        row = settings_for(db, schedule.home_id)
        planned = schedule.next_run_at
        if planned is not None and planned.tzinfo is None:
            planned = planned.replace(tzinfo=UTC)
        if row.paused:
            schedule.last_result = "Skipped: schedules are paused"
        elif planned is not None and now - planned > MISSED_GRACE:
            schedule.last_result = "Missed: the server was not running then"
        else:
            result = run_schedule(
                db, schedule, schedule.created_by, f"schedule {schedule.name}"
            )
            schedule.last_run_at = now
            schedule.last_result = summary(result)
            ran += 1
        schedule.next_run_at = next_run(schedule, row, max(now, planned or now))
        db.commit()
    return ran


def _tick() -> None:
    with SessionLocal() as db:
        try:
            run_due(db)
        except Exception:  # one bad pass must not stop the scheduler
            db.rollback()
            log.exception("schedules: a pass failed")


async def run_forever() -> None:
    """The scheduler, started with the app."""
    while True:
        await asyncio.sleep(TICK_SECONDS)
        await asyncio.to_thread(_tick)


def home_scene(db: Session, home_id: str, scene_id: str) -> Scene:
    scene = db.get(Scene, scene_id)
    if scene is None or scene.home_id != home_id:
        raise HTTPException(404, "Not found")
    return scene


def home_schedule(db: Session, home_id: str, schedule_id: str) -> Schedule:
    schedule = db.get(Schedule, schedule_id)
    if schedule is None or schedule.home_id != home_id:
        raise HTTPException(404, "Not found")
    return schedule
