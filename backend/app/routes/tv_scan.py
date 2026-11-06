"""Find TVs on the home network (Settings > Integrations > Find TVs).
Operators and up; the search only looks, it adds nothing."""

import ipaddress
import json
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.audit import record_event
from app.authorization import require_role
from app.db_config import get_db
from app.dependencies import client_ip, current_user, require_csrf
from app.features import integration_enabled
from app.models import Device, Role, User
from app.tv_scan import ScanError, network_for, scan

router = APIRouter(prefix="/api/v1/homes/{home_id}", tags=["tvs"])
INTEGRATIONS = {"samsung": "samsung_tv", "roku": "roku_tv", "lg": "lg_tv"}


class ScanIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    network: str | None = Field(default=None, max_length=43)


@router.post("/tv-scan", dependencies=[Depends(require_csrf)])
def find_tvs(
    home_id: str,
    body: ScanIn,
    request: Request,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    require_role(db, user.id, home_id, Role.OPERATOR)
    ip = client_ip(request)
    try:
        client = ip if ip and ipaddress.ip_address(ip).is_private else None
    except ValueError:  # not an address (a test client, a proxy's name)
        client = None
    try:
        net = network_for(body.network, client)
    except ScanError as error:
        raise HTTPException(422, str(error)) from None
    record_event(
        db,
        "tv_scan",
        user_id=user.id,
        home_id=home_id,
        ip_address=ip,
        details={"network": str(net)},
    )
    known = {
        str(d.external_id)
        if d.integration != "kasa"
        else json.loads(d.capabilities or "{}").get("host")
        for d in db.scalars(select(Device).where(Device.home_id == home_id))
    }
    found = scan(net)
    for tv in found:
        integration = INTEGRATIONS[tv["brand"]]
        tv["integration"] = integration
        tv["enabled"] = integration_enabled(db, home_id, integration)
        tv["added"] = tv["host"] in known
    return {"network": str(net), "tvs": found}
