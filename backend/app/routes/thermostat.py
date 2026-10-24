"""Thermostat schedules: GET .../devices/{id}/schedule reads them, PUT
.../schedule/{kind} writes one schedule for chosen days.

SEC-11: the caller must be a member of the home in the path.
SEC-40 to SEC-42: scheduled set points stay within the safety limits, and
writing is refused until limits are configured; every write is audited.
"""

from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.audit import record_event
from app.authorization import require_role
from app.cync_home import CyncUnavailable
from app.db_config import get_db
from app.dependencies import client_ip, current_user, require_csrf
from app.models import Device, User
from app.routes.devices import CommandRejected, _device_bounds, _limits
from app.thermostat_schedule import read_schedule, write_schedule

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
