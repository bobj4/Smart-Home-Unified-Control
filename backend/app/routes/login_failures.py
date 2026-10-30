"""Settings > Admin > Login rules: what happens after repeated failed logins.

  GET/PUT /api/v1/admin/login-failures   {action, limit, lockout_minutes}

Admins only. Numbers: any positive number, or 0 for lockout_minutes (locked
until the password is reset); null (blank) turns that part off.
"""

from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, StrictInt
from sqlalchemy.orm import Session

from app.audit import record_event
from app.db_config import get_db
from app.dependencies import client_ip, current_user, require_csrf
from app.login_failures import MAX_NUMBER, rules_out
from app.login_policy import settings
from app.models import User
from app.routes.login_times import require_admin

router = APIRouter(prefix="/api/v1/admin", tags=["login rules"])


class FailureRules(BaseModel):
    model_config = ConfigDict(extra="forbid")
    action: Literal["none", "lockout", "lockdown"]
    limit: StrictInt | None  # failures in a row; null = off
    lockout_minutes: StrictInt | None  # 0 = until the password is reset


@router.get("/login-failures")
def get_rules(
    user: User = Depends(current_user), db: Session = Depends(get_db)
) -> dict[str, Any]:
    require_admin(db, user)
    return rules_out(settings(db))


@router.put("/login-failures", dependencies=[Depends(require_csrf)])
def set_rules(
    body: FailureRules,
    request: Request,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    require_admin(db, user)
    if body.limit is not None and not 1 <= body.limit <= MAX_NUMBER:
        raise HTTPException(422, "Failures: a positive number, or blank for off")
    if body.lockout_minutes is not None and not 0 <= body.lockout_minutes <= MAX_NUMBER:
        raise HTTPException(
            422,
            "Lockout minutes: a number (0 = until the password is reset), or blank for off",
        )
    row = settings(db)
    before = rules_out(row)
    row.login_failure_action = body.action
    row.login_failure_limit = body.limit
    row.login_lockout_minutes = body.lockout_minutes
    db.commit()
    record_event(
        db,
        "login_failure_rules_changed",
        user_id=user.id,
        ip_address=client_ip(request),
        details={"before": before, "after": rules_out(row)},
    )
    return rules_out(row)
