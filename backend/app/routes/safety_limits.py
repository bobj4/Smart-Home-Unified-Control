"""View and change a home's safety limits. Changing them is owner-only."""

from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.authorization import require_role
from app.db_config import get_db
from app.dependencies import client_ip, current_user, require_csrf
from app.models import DeviceSafetyLimits, Role, User
from app.safety import LimitsError, apply_recommended, limits_out, set_limits

router = APIRouter(prefix="/api/v1/homes/{home_id}/safety-limits", tags=["safety"])


class LimitsIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    unit: Literal["F", "C"]
    min_temperature: float
    max_temperature: float
    default_target: float | None = None
    enabled: bool = True


@router.get("")
def list_limits(
    home_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)
) -> list[dict[str, Any]]:
    require_role(db, user.id, home_id)
    rows = db.scalars(
        select(DeviceSafetyLimits)
        .where(DeviceSafetyLimits.home_id == home_id)
        .order_by(DeviceSafetyLimits.device_type)
    )
    return [limits_out(r) for r in rows]


@router.put("/{device_type}", dependencies=[Depends(require_csrf)])
def update_limits(
    home_id: str,
    device_type: Literal["thermostat", "water_heater"],
    body: LimitsIn,
    request: Request,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    require_role(db, user.id, home_id, Role.ADMIN)
    try:
        limits = set_limits(
            db,
            home_id=home_id,
            device_type=device_type,
            unit=body.unit,
            min_temperature=body.min_temperature,
            max_temperature=body.max_temperature,
            enabled=body.enabled,
            default_target=body.default_target,
            user_id=user.id,
            ip_address=client_ip(request),
        )
    except LimitsError as error:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(error)) from None
    return limits_out(limits)


@router.post("/recommended", dependencies=[Depends(require_csrf)])
def use_recommended(
    home_id: str,
    request: Request,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> list[dict[str, Any]]:
    """Replace every limit with the recommended values and default targets."""
    require_role(db, user.id, home_id, Role.ADMIN)
    apply_recommended(db, home_id, user.id, client_ip(request))
    return list_limits(home_id, user, db)
