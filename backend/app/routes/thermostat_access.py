"""Settings > Safety Settings: who may change thermostat installer settings
(system type, furnace, power wires, thresholds, calibration...). Anyone in
the home can see it; only admins change it. SEC-11: callers must be members
of the home in the path."""

from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from app.audit import record_event
from app.authorization import _RANK, require_role
from app.db_config import get_db
from app.dependencies import client_ip, current_user, require_csrf
from app.models import Home, Role, User

router = APIRouter(
    prefix="/api/v1/homes/{home_id}/thermostat-access", tags=["thermostat"]
)


class Access(BaseModel):
    model_config = ConfigDict(extra="forbid")
    installer_role: Literal["admin", "operator", "member"]


def installer_role(db: Session, home_id: str) -> Role:
    home = db.get(Home, home_id)
    try:
        return Role(home.thermostat_installer_role if home else "admin")
    except ValueError:
        return Role.ADMIN


def may_change_installer(db: Session, user: User, home_id: str) -> bool:
    """Whether the caller's role reaches the home's installer setting."""
    membership = require_role(db, user.id, home_id)
    try:
        return _RANK[Role(membership.role)] >= _RANK[installer_role(db, home_id)]
    except ValueError:
        return False


@router.get("")
def get_access(
    home_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)
) -> dict[str, Any]:
    require_role(db, user.id, home_id)
    return {
        "installer_role": installer_role(db, home_id).value,
        "you_may": may_change_installer(db, user, home_id),
    }


@router.put("", dependencies=[Depends(require_csrf)])
def set_access(
    home_id: str,
    body: Access,
    request: Request,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    require_role(db, user.id, home_id, Role.ADMIN)
    home = db.get(Home, home_id)
    if home is None:  # require_role found the membership, so this is a race
        raise HTTPException(404, "Not found")
    home.thermostat_installer_role = body.installer_role
    db.commit()
    record_event(
        db,
        "thermostat_access_changed",
        user_id=user.id,
        home_id=home_id,
        ip_address=client_ip(request),
        details={"installer_role": body.installer_role},
    )
    return get_access(home_id, user, db)
