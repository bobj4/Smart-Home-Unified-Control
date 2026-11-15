"""Schedules and Scenes (see app/automation.py). Everyone in the home but
guests sees them and runs scenes; making and changing them takes the role
the admins chose (Admin > Schedules and Scenes, admins by default). A guest
allowed to run scenes sees and runs them through the guest routes."""

import json
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, StrictBool
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import automation
from app.audit import record_event
from app.authorization import require_role
from app.automation import AutomationError
from app.db_config import get_db
from app.dependencies import client_ip, current_user, require_csrf
from app.guest_access import require_guest
from app.models import Role, Scene, Schedule, User, utcnow

router = APIRouter(prefix="/api/v1/homes/{home_id}/automation", tags=["automation"])
guest_router = APIRouter(prefix="/api/v1/homes/{home_id}/guest", tags=["guests"])


class Step(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["device", "group"]
    id: str = Field(min_length=1, max_length=36)
    command: str = Field(min_length=1, max_length=50, pattern=r"^[a-z_]+$")
    payload: dict[str, Any] = Field(default_factory=dict)


class SceneIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=100)
    steps: list[Step] = Field(min_length=1, max_length=automation.MAX_STEPS)


class Trigger(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["time", "sunrise", "sunset"]
    at: str | None = Field(default=None, max_length=5)
    offset: int = Field(default=0, ge=-240, le=240)


class ScheduleIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=100)
    enabled: StrictBool = True
    trigger: Trigger
    days: list[int] = Field(min_length=1, max_length=7)
    scene_id: str | None = Field(default=None, max_length=36)
    steps: list[Step] = Field(default_factory=list, max_length=automation.MAX_STEPS)


class SettingsIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    time_zone: str | None = Field(default=None, max_length=64)
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)
    editors: Literal["admin", "operator", "member"] | None = None
    paused: StrictBool | None = None


def _fail(error: AutomationError) -> HTTPException:
    return HTTPException(error.status_code, error.reason)


def _audit(
    db: Session, request: Request, user: User, home_id: str, kind: str, **details: Any
) -> None:
    record_event(
        db,
        kind,
        user_id=user.id,
        home_id=home_id,
        ip_address=client_ip(request),
        details=details,
    )


def _steps(db: Session, home_id: str, steps: list[Step]) -> list[dict[str, Any]]:
    try:
        return automation.check_steps(db, home_id, [s.model_dump() for s in steps])
    except AutomationError as error:
        raise _fail(error) from None


@router.get("")
def overview(
    home_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)
) -> dict[str, Any]:
    """Scenes, schedules, the settings, and whether the caller may edit."""
    require_role(db, user.id, home_id)
    row = automation.settings_for(db, home_id)
    db.commit()
    try:
        automation.require_editor(db, user.id, home_id)
        can_edit = True
    except HTTPException:
        can_edit = False
    scenes = db.scalars(
        select(Scene).where(Scene.home_id == home_id).order_by(Scene.name)
    )
    schedules = db.scalars(
        select(Schedule).where(Schedule.home_id == home_id).order_by(Schedule.name)
    )
    return {
        "scenes": [automation.scene_out(s) for s in scenes],
        "schedules": [automation.schedule_out(s, row) for s in schedules],
        "settings": automation.settings_out(row),
        "can_edit": can_edit,
    }


# ------------------------------------------------------------ scenes


@router.post("/scenes", status_code=201, dependencies=[Depends(require_csrf)])
def create_scene(
    home_id: str,
    body: SceneIn,
    request: Request,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    automation.require_editor(db, user.id, home_id)
    steps = _steps(db, home_id, body.steps)
    scene = Scene(
        home_id=home_id,
        name=body.name.strip(),
        steps=json.dumps(steps),
        created_by=user.id,
    )
    db.add(scene)
    db.commit()
    _audit(db, request, user, home_id, "scene_created", scene_id=scene.id)
    return automation.scene_out(scene)


@router.put("/scenes/{scene_id}", dependencies=[Depends(require_csrf)])
def change_scene(
    home_id: str,
    scene_id: str,
    body: SceneIn,
    request: Request,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    automation.require_editor(db, user.id, home_id)
    scene = automation.home_scene(db, home_id, scene_id)
    scene.steps = json.dumps(_steps(db, home_id, body.steps))
    scene.name = body.name.strip()
    db.commit()
    _audit(db, request, user, home_id, "scene_changed", scene_id=scene.id)
    return automation.scene_out(scene)


@router.delete("/scenes/{scene_id}", dependencies=[Depends(require_csrf)])
def delete_scene(
    home_id: str,
    scene_id: str,
    request: Request,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> dict[str, str]:
    automation.require_editor(db, user.id, home_id)
    db.delete(automation.home_scene(db, home_id, scene_id))
    db.commit()
    _audit(db, request, user, home_id, "scene_deleted", scene_id=scene_id)
    return {"detail": "Deleted"}


@router.post("/scenes/{scene_id}/run", dependencies=[Depends(require_csrf)])
def run_scene(
    home_id: str,
    scene_id: str,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    require_role(db, user.id, home_id)
    scene = automation.home_scene(db, home_id, scene_id)
    return automation.run_scene(db, scene, user.id, f"scene {scene.name}")


# ------------------------------------------------------------ schedules


def _fill(db: Session, home_id: str, schedule: Schedule, body: ScheduleIn) -> None:
    try:
        trigger = automation.check_trigger(body.trigger.model_dump())
        days = automation.check_days(body.days)
    except AutomationError as error:
        raise _fail(error) from None
    if body.scene_id is not None:
        automation.home_scene(db, home_id, body.scene_id)
    steps = _steps(db, home_id, body.steps)
    if body.scene_id is None and not steps:
        raise HTTPException(422, "pick a scene or add a step")
    schedule.name = body.name.strip()
    schedule.enabled = body.enabled
    schedule.trigger = json.dumps(trigger)
    schedule.days = json.dumps(days)
    schedule.scene_id = body.scene_id
    schedule.steps = json.dumps(steps)
    row = automation.settings_for(db, home_id)
    schedule.next_run_at = automation.next_run(schedule, row, utcnow())


@router.post("/schedules", status_code=201, dependencies=[Depends(require_csrf)])
def create_schedule(
    home_id: str,
    body: ScheduleIn,
    request: Request,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    automation.require_editor(db, user.id, home_id)
    schedule = Schedule(home_id=home_id, created_by=user.id, trigger="{}")
    _fill(db, home_id, schedule, body)
    db.add(schedule)
    db.commit()
    _audit(db, request, user, home_id, "schedule_created", schedule_id=schedule.id)
    return automation.schedule_out(schedule, automation.settings_for(db, home_id))


@router.put("/schedules/{schedule_id}", dependencies=[Depends(require_csrf)])
def change_schedule(
    home_id: str,
    schedule_id: str,
    body: ScheduleIn,
    request: Request,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    automation.require_editor(db, user.id, home_id)
    schedule = automation.home_schedule(db, home_id, schedule_id)
    _fill(db, home_id, schedule, body)
    db.commit()
    _audit(db, request, user, home_id, "schedule_changed", schedule_id=schedule.id)
    return automation.schedule_out(schedule, automation.settings_for(db, home_id))


@router.delete("/schedules/{schedule_id}", dependencies=[Depends(require_csrf)])
def delete_schedule(
    home_id: str,
    schedule_id: str,
    request: Request,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> dict[str, str]:
    automation.require_editor(db, user.id, home_id)
    db.delete(automation.home_schedule(db, home_id, schedule_id))
    db.commit()
    _audit(db, request, user, home_id, "schedule_deleted", schedule_id=schedule_id)
    return {"detail": "Deleted"}


@router.post("/schedules/{schedule_id}/run", dependencies=[Depends(require_csrf)])
def run_schedule_now(
    home_id: str,
    schedule_id: str,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Run it now, to try it (its next run stays as planned)."""
    automation.require_editor(db, user.id, home_id)
    schedule = automation.home_schedule(db, home_id, schedule_id)
    result = automation.run_schedule(db, schedule, user.id, f"schedule {schedule.name}")
    schedule.last_run_at = utcnow()
    schedule.last_result = automation.summary(result)
    db.commit()
    return result


# ------------------------------------------------------------ settings (admins)


@router.put("/settings", dependencies=[Depends(require_csrf)])
def change_settings(
    home_id: str,
    body: SettingsIn,
    request: Request,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    require_role(db, user.id, home_id, Role.ADMIN)
    changes = body.model_dump(exclude_unset=True)
    try:
        row = automation.save_settings(db, home_id, changes)
    except AutomationError as error:
        db.rollback()
        raise _fail(error) from None
    _audit(db, request, user, home_id, "schedule_settings_changed", **changes)
    return automation.settings_out(row)


# ------------------------------------------------------------ guests


@guest_router.get("/scenes")
def guest_scenes(
    home_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)
) -> list[dict[str, Any]]:
    if not require_guest(db, user, home_id).scenes:
        raise HTTPException(403, "Forbidden")
    scenes = db.scalars(
        select(Scene).where(Scene.home_id == home_id).order_by(Scene.name)
    )
    return [{"id": s.id, "name": s.name} for s in scenes]


@guest_router.post("/scenes/{scene_id}/run", dependencies=[Depends(require_csrf)])
def guest_run_scene(
    home_id: str,
    scene_id: str,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """A guest allowed to run scenes runs the whole scene, whatever its
    devices (that is what the permission gives)."""
    if not require_guest(db, user, home_id).scenes:
        raise HTTPException(403, "Forbidden")
    scene = automation.home_scene(db, home_id, scene_id)
    result = automation.run_scene(db, scene, user.id, f"scene {scene.name} (guest)")
    return {"done": result["done"], "failed": len(result["failed"])}
