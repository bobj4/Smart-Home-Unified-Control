"""Turn integrations (device brands) on or off for a home. Owner only."""

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict, StrictBool
from sqlalchemy.orm import Session

from app.authorization import require_role
from app.db_config import get_db
from app.demo import add_demo_devices, remove_demo_devices
from app.dependencies import client_ip, current_user, require_csrf
from app.features import BY_ID, list_integrations, set_integration
from app.models import Role, User

router = APIRouter(prefix="/api/v1/homes/{home_id}/integrations", tags=["integrations"])


class IntegrationToggle(BaseModel):
    model_config = ConfigDict(extra="forbid")
    enabled: StrictBool


@router.get("")
def get_integrations(
    home_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)
) -> list[dict[str, Any]]:
    require_role(db, user.id, home_id)
    return list_integrations(db, home_id)


@router.put("/{integration_id}", dependencies=[Depends(require_csrf)])
def toggle_integration(
    home_id: str,
    integration_id: str,
    body: IntegrationToggle,
    request: Request,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    require_role(db, user.id, home_id, Role.ADMIN)
    if integration_id not in BY_ID:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Unknown integration")
    result = set_integration(
        db, home_id, integration_id, body.enabled, user.id, client_ip(request)
    )
    if integration_id == "simulated":  # demo devices come and go with it
        if body.enabled:
            add_demo_devices(db, home_id)
        else:
            remove_demo_devices(db, home_id)
    return result
