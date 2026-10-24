"""Verbose logging switch (Settings > Activity log, admins). Installation-
wide, like the login rules; off by default. See app/verbose.py."""

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, ConfigDict, StrictBool
from sqlalchemy.orm import Session

from app.audit import record_event
from app.db_config import get_db
from app.dependencies import client_ip, current_user, require_csrf
from app.login_policy import settings
from app.models import User
from app.routes.login_times import require_admin

router = APIRouter(prefix="/api/v1/admin/verbose-logging", tags=["audit"])


class VerboseSwitch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    enabled: StrictBool


@router.get("")
def get_verbose(
    user: User = Depends(current_user), db: Session = Depends(get_db)
) -> dict[str, bool]:
    require_admin(db, user)
    return {"enabled": settings(db).verbose_logging}


@router.put("", dependencies=[Depends(require_csrf)])
def set_verbose(
    body: VerboseSwitch,
    request: Request,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> dict[str, bool]:
    require_admin(db, user)
    settings(db).verbose_logging = body.enabled
    db.commit()
    record_event(
        db,
        "logging_verbose_on" if body.enabled else "logging_verbose_off",
        user_id=user.id,
        ip_address=client_ip(request),
    )
    return {"enabled": body.enabled}
