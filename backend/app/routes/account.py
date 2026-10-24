"""The caller's own account: password, recovery codes, authenticator, sessions.

Every change re-checks the current password (except confirming a new
authenticator, which needs a code from it) and is audited.
"""

import json
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.audit import record_event
from app.auth import (
    generate_recovery_codes,
    generate_totp_provisioning_uri,
    generate_totp_secret,
    hash_password,
    totp_qr_svg,
    verify_password,
    verify_totp_code,
)
from app.db_config import get_db
from app.dependencies import client_ip, current_session, current_user, require_csrf
from app.login_policy import check_password
from app.models import Home, HomeMembership, User
from app.models import Session as SessionModel
from app.rate_limiter import check_login_allowed, record_login_failure
from app.sessions import as_utc

router = APIRouter(prefix="/api/v1/account", tags=["account"])


class PasswordConfirm(BaseModel):
    model_config = ConfigDict(extra="forbid")
    password: str = Field(min_length=1, max_length=1024)


class PasswordChange(BaseModel):
    model_config = ConfigDict(extra="forbid")
    current_password: str = Field(min_length=1, max_length=1024)
    new_password: str = Field(
        min_length=1, max_length=1024
    )  # rules: app/login_policy.py


class Preferences(BaseModel):
    model_config = ConfigDict(extra="forbid")
    theme: Literal["system", "light", "dark"]


class TotpDisable(BaseModel):
    model_config = ConfigDict(extra="forbid")
    password: str = Field(min_length=1, max_length=1024)
    totp_code: str = Field(min_length=6, max_length=6)


class TotpConfirm(BaseModel):
    model_config = ConfigDict(extra="forbid")
    totp_code: str = Field(min_length=6, max_length=6)


def _check_password(db: Session, user: User, password: str, ip: str | None) -> None:
    account = user.email.lower()
    check_login_allowed(account, ip)
    if not verify_password(password, user.hashed_password):
        record_login_failure(account, ip)
        record_event(db, "reauth_failure", user_id=user.id, ip_address=ip)
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Password is incorrect")


@router.get("")
def get_account(
    user: User = Depends(current_user), db: Session = Depends(get_db)
) -> dict[str, Any]:
    rows = db.execute(
        select(Home, HomeMembership.role)
        .join(HomeMembership, HomeMembership.home_id == Home.id)
        .where(HomeMembership.user_id == user.id)
        .order_by(Home.name)
    )
    homes = list(rows)
    return {
        "id": user.id,
        "email": user.email,
        "name": user.name,
        "homes": [{"id": h.id, "name": h.name, "role": role} for h, role in homes],
        "two_factor": bool(user.is_totp_enabled),
        "two_factor_required": any(h.require_two_factor for h, _ in homes),
        "theme": user.theme or "system",
    }


@router.put("/preferences", dependencies=[Depends(require_csrf)])
def set_preferences(
    body: Preferences, user: User = Depends(current_user), db: Session = Depends(get_db)
) -> dict[str, str]:
    user.theme = body.theme
    db.commit()
    return {"theme": user.theme}


@router.post("/password", dependencies=[Depends(require_csrf)])
def change_password(
    body: PasswordChange,
    request: Request,
    session: SessionModel = Depends(current_session),
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> dict[str, str]:
    """Change the password and end every other session."""
    ip = client_ip(request)
    _check_password(db, user, body.current_password, ip)
    check_password(db, body.new_password)
    user.hashed_password = hash_password(body.new_password)
    db.execute(
        delete(SessionModel).where(
            SessionModel.user_id == user.id, SessionModel.id != session.id
        )
    )
    db.commit()
    record_event(db, "password_changed", user_id=user.id, ip_address=ip)
    return {"detail": "Password changed"}


@router.post("/recovery-codes", dependencies=[Depends(require_csrf)])
def regenerate_recovery_codes(
    body: PasswordConfirm,
    request: Request,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> dict[str, list[str]]:
    """Replace all recovery codes. The new codes are returned once."""
    ip = client_ip(request)
    _check_password(db, user, body.password, ip)
    codes = generate_recovery_codes()
    user.recovery_codes = json.dumps([hashed for _, hashed in codes])
    db.commit()
    record_event(db, "recovery_codes_regenerated", user_id=user.id, ip_address=ip)
    return {"recovery_codes": [plain for plain, _ in codes]}


@router.post("/totp/setup", dependencies=[Depends(require_csrf)])
def start_totp_reset(
    body: PasswordConfirm,
    request: Request,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> dict[str, str]:
    """Offer a new authenticator secret. The old one stays active until a code
    from the new one is confirmed."""
    _check_password(db, user, body.password, client_ip(request))
    secret = generate_totp_secret()
    user.pending_totp_secret = secret
    db.commit()
    uri = generate_totp_provisioning_uri(user.email, secret)
    return {"secret": secret, "otpauth_uri": uri, "qr_svg": totp_qr_svg(uri)}


@router.post("/totp/confirm", dependencies=[Depends(require_csrf)])
def confirm_totp_reset(
    body: TotpConfirm,
    request: Request,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> dict[str, str]:
    if not user.pending_totp_secret:
        raise HTTPException(status.HTTP_409_CONFLICT, "No authenticator reset started")
    step = verify_totp_code(body.totp_code, user.pending_totp_secret)
    if step is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Code does not match")
    user.totp_secret = user.pending_totp_secret
    user.pending_totp_secret = None
    user.totp_last_step = step
    user.is_totp_enabled = True
    db.commit()
    record_event(db, "totp_reset", user_id=user.id, ip_address=client_ip(request))
    return {"detail": "Authenticator replaced"}


@router.post("/totp/disable", dependencies=[Depends(require_csrf)])
def disable_totp(
    body: TotpDisable,
    request: Request,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> dict[str, str]:
    """Turn two-factor login off: needs the password and a current code.
    Refused while any of the caller's homes requires two-factor."""
    ip = client_ip(request)
    if not user.is_totp_enabled or not user.totp_secret:
        raise HTTPException(status.HTTP_409_CONFLICT, "Two-factor login is already off")
    required = db.scalars(
        select(Home)
        .join(HomeMembership, HomeMembership.home_id == Home.id)
        .where(HomeMembership.user_id == user.id, Home.require_two_factor.is_(True))
    ).first()
    if required is not None:
        raise HTTPException(
            status.HTTP_409_CONFLICT, f"{required.name} requires two-factor login"
        )
    _check_password(db, user, body.password, ip)
    step = verify_totp_code(body.totp_code, user.totp_secret, user.totp_last_step)
    if step is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Code does not match")
    user.is_totp_enabled = False
    user.totp_secret = None
    user.pending_totp_secret = None
    user.totp_last_step = None
    db.commit()
    record_event(db, "totp_disabled", user_id=user.id, ip_address=ip)
    return {"detail": "Two-factor login turned off"}


@router.get("/sessions")
def list_sessions(
    session: SessionModel = Depends(current_session), db: Session = Depends(get_db)
) -> list[dict[str, Any]]:
    rows = db.scalars(
        select(SessionModel)
        .where(SessionModel.user_id == session.user_id)
        .order_by(SessionModel.last_activity.desc())
    )
    return [
        {
            "id": s.id,
            "created_at": as_utc(s.created_at).isoformat(),
            "last_activity": as_utc(s.last_activity).isoformat(),
            "ip_address": s.ip_address,
            "current": s.id == session.id,
        }
        for s in rows
    ]


@router.delete("/sessions/{session_id}", dependencies=[Depends(require_csrf)])
def revoke_session(
    session_id: str,
    request: Request,
    session: SessionModel = Depends(current_session),
    db: Session = Depends(get_db),
) -> dict[str, str]:
    target = db.get(SessionModel, session_id)
    if target is None or target.user_id != session.user_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found")
    db.delete(target)
    db.commit()
    record_event(
        db, "session_revoked", user_id=session.user_id, ip_address=client_ip(request)
    )
    return {"detail": "Session ended"}


@router.post("/sessions/revoke-others", dependencies=[Depends(require_csrf)])
def revoke_other_sessions(
    request: Request,
    session: SessionModel = Depends(current_session),
    db: Session = Depends(get_db),
) -> dict[str, str]:
    db.execute(
        delete(SessionModel).where(
            SessionModel.user_id == session.user_id, SessionModel.id != session.id
        )
    )
    db.commit()
    record_event(
        db,
        "sessions_revoked",
        user_id=session.user_id,
        ip_address=client_ip(request),
    )
    return {"detail": "Other sessions ended"}
