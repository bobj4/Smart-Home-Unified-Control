"""Thermostat schedules: GET .../devices/{id}/schedule reads them, PUT
.../schedule/{kind} writes one schedule for chosen days. Its own settings:
GET .../devices/{id}/settings, PUT to change the yes/no ones.

SEC-11: the caller must be a member of the home in the path.
SEC-40 to SEC-42: scheduled set points stay within the safety limits, and
writing is refused until limits are configured; every write is audited.
"""

from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictFloat, StrictInt
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.audit import record_event
from app.authorization import require_role
from app.cync_home import CyncUnavailable
from app.db_config import get_db
from app.dependencies import client_ip, current_user, require_csrf
from app.models import Device, User
from app.routes.devices import CommandRejected, _device_bounds, _limits
from app.routes.thermostat_access import may_change_installer
from app.thermostat_schedule import read_schedule, write_schedule
from app.thermostat_settings import INSTALLER, read_settings, write_settings

Day = Literal["mon", "tue", "wed", "thu", "fri", "sat", "sun"]


class Period(BaseModel):
    model_config = ConfigDict(extra="forbid")

    time: str = Field(pattern=r"^([01][0-9]|2[0-3]):[0-5][0-9]$")
    heat: float | None = None
    cool: float | None = None
    read: Literal["thermostat", "all", "sensor"] | None = None
    pin: str | None = Field(default=None, pattern=r"^[0-9]{6}$")


class ScheduleDays(BaseModel):
    model_config = ConfigDict(extra="forbid")

    days: list[Day] = Field(min_length=1, max_length=7)
    periods: list[Period] = Field(max_length=10)


class SettingChanges(BaseModel):
    model_config = ConfigDict(extra="forbid")

    early_on: StrictBool | None = None
    celsius: StrictBool | None = None
    auto_dst: StrictBool | None = None
    dehumidify: StrictBool | None = None
    heat_pump_changeover: StrictBool | None = None
    # Ranges are checked in thermostat_settings (LIMITS).
    dehumidify_to: StrictInt | None = None
    min_fan_runtime: StrictInt | None = None
    temperature_offset: StrictFloat | StrictInt | None = None
    humidity_offset: StrictFloat | StrictInt | None = None
    auto_deadband: StrictFloat | StrictInt | None = None
    furnace_type: StrictInt | None = None
    system_type: StrictInt | None = None
    power_wires: StrictInt | None = None
    # Stage thresholds, degrees (thermostat_settings.STAGE_OFFSETS)
    heat_stage1_begin: StrictFloat | StrictInt | None = None
    heat_stage2_begin: StrictFloat | StrictInt | None = None
    heat_stage2_end: StrictFloat | StrictInt | None = None
    heat_stage3_begin: StrictFloat | StrictInt | None = None
    heat_stage3_end: StrictFloat | StrictInt | None = None
    heat_stage4_begin: StrictFloat | StrictInt | None = None
    heat_stage4_end: StrictFloat | StrictInt | None = None
    emergency_stage3_begin: StrictFloat | StrictInt | None = None
    emergency_stage4_begin: StrictFloat | StrictInt | None = None
    emergency_stage4_end: StrictFloat | StrictInt | None = None
    cool_stage1_begin: StrictFloat | StrictInt | None = None
    cool_stage2_begin: StrictFloat | StrictInt | None = None
    cool_stage2_end: StrictFloat | StrictInt | None = None


router = APIRouter(prefix="/api/v1/homes/{home_id}/devices", tags=["thermostat"])


@router.get("/{device_id}/schedule")
def thermostat_schedule(
    home_id: str,
    device_id: str,
    refresh: bool = Query(False),
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    require_role(db, user.id, home_id)
    device = _thermostat(db, home_id, device_id)
    try:
        return read_schedule(db, device, refresh)
    except CyncUnavailable as error:
        raise HTTPException(error.status_code, error.reason) from None


def _thermostat(db: Session, home_id: str, device_id: str) -> Device:
    device = db.scalars(
        select(Device).where(Device.id == device_id, Device.home_id == home_id)
    ).first()
    if device is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found")
    if device.integration != "cync" or device.type != "thermostat":
        raise HTTPException(409, "schedules are read from Cync thermostats only")
    return device


@router.put("/{device_id}/schedule/{kind}", dependencies=[Depends(require_csrf)])
def save_thermostat_schedule(
    home_id: str,
    device_id: str,
    kind: Literal["heat", "cool", "auto", "sensors"],
    body: ScheduleDays,
    request: Request,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Give the chosen days of one schedule these periods (an empty list
    clears them). The thermostat reads them back before this succeeds."""
    require_role(db, user.id, home_id)
    device = _thermostat(db, home_id, device_id)
    try:
        bounds = _device_bounds(device, _limits(db, device))
    except CommandRejected as error:
        raise HTTPException(error.status_code, error.reason) from None
    periods = [p.model_dump(exclude_none=True) for p in body.periods]
    days: list[str] = list(dict.fromkeys(body.days))
    details = {"device_id": device.id, "schedule": kind, "days": days}
    try:
        result = write_schedule(db, device, kind, days, periods, bounds)
    except CyncUnavailable as error:
        record_event(
            db,
            "thermostat_schedule_failed",
            user_id=user.id,
            home_id=home_id,
            ip_address=client_ip(request),
            details={**details, "reason": error.reason},
        )
        raise HTTPException(error.status_code, error.reason) from None
    record_event(
        db,
        "thermostat_schedule_saved",
        user_id=user.id,
        home_id=home_id,
        ip_address=client_ip(request),
        details={**details, "periods": len(periods)},
    )
    return result


@router.get("/{device_id}/settings")
def thermostat_settings(
    home_id: str,
    device_id: str,
    refresh: bool = Query(False),
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    require_role(db, user.id, home_id)
    device = _thermostat(db, home_id, device_id)
    try:
        result = read_settings(db, device, refresh)
    except CyncUnavailable as error:
        raise HTTPException(error.status_code, error.reason) from None
    return {**result, "installer_allowed": may_change_installer(db, user, home_id)}


@router.put("/{device_id}/settings", dependencies=[Depends(require_csrf)])
def save_thermostat_settings(
    home_id: str,
    device_id: str,
    body: SettingChanges,
    request: Request,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Change the thermostat's own settings. The thermostat reads them back
    before this succeeds."""
    require_role(db, user.id, home_id)
    device = _thermostat(db, home_id, device_id)
    changes = body.model_dump(exclude_none=True)
    if not changes:
        raise HTTPException(422, "Send a setting to change")
    # How the equipment is set up: the role chosen in Safety Settings.
    if INSTALLER.intersection(changes) and not may_change_installer(db, user, home_id):
        raise HTTPException(
            403, "Only people allowed in Settings > Safety Settings can change this"
        )
    details = {"device_id": device.id, "changes": changes}
    try:
        result = write_settings(db, device, changes)
    except CyncUnavailable as error:
        record_event(
            db,
            "thermostat_settings_failed",
            user_id=user.id,
            home_id=home_id,
            ip_address=client_ip(request),
            details={**details, "reason": error.reason},
        )
        raise HTTPException(error.status_code, error.reason) from None
    record_event(
        db,
        "thermostat_settings_saved",
        user_id=user.id,
        home_id=home_id,
        ip_address=client_ip(request),
        details=details,
    )
    return {**result, "installer_allowed": may_change_installer(db, user, home_id)}
