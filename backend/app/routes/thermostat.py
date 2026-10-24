"""Thermostat schedules (read-only for now): GET .../devices/{id}/schedule.

SEC-11: the caller must be a member of the home in the path.
"""

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.authorization import require_role
from app.cync_home import CyncUnavailable
from app.db_config import get_db
from app.dependencies import current_user
from app.models import Device, User
from app.thermostat_schedule import read_schedule

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
    device = db.scalars(
        select(Device).where(Device.id == device_id, Device.home_id == home_id)
    ).first()
    if device is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found")
    if device.integration != "cync":
        raise HTTPException(409, "schedules are read from Cync thermostats only")
    try:
        return read_schedule(db, device, refresh)
    except CyncUnavailable as error:
        raise HTTPException(error.status_code, error.reason) from None
