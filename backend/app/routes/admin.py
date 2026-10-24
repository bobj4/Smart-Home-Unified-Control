"""Admin settings: login rules (owners), renaming a home, creating users
without an enrollment code, and password recovery codes."""

import hashlib
import json
import secrets
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict, Field, StrictBool
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.audit import record_event
from app.auth import generate_recovery_codes, hash_password
from app.authorization import require_role
from app.db_config import get_db
from app.dependencies import client_ip, current_user, require_csrf
from app.login_policy import check_password, normalize_login, settings, settings_out
from app.login_times import forget_all
from app.mailer import configured
from app.models import GUEST_ROLE, Home, HomeMembership, PasswordReset, Role, User
from app.models import Session as SessionModel
from app.rate_limiter import check_login_allowed, record_login_failure
from app.sessions import as_utc

public_router = APIRouter(prefix="/api/v1", tags=["admin"])
router = APIRouter(prefix="/api/v1", tags=["admin"])

RESET_LIFETIME = timedelta(hours=24)
_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"


def _hash(code: str) -> str:
    return hashlib.sha256(
        "".join(c for c in code.upper() if c.isalnum()).encode()
    ).hexdigest()


def _require_owner_somewhere(db: Session, user: User) -> None:
    owner = db.scalars(
        select(HomeMembership).where(
            HomeMembership.user_id == user.id, HomeMembership.role == Role.ADMIN.value
        )
    ).first()
    if owner is None:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only an admin can change this")


# ------------------------------------------------------------ login rules


class PasswordRules(BaseModel):
    model_config = ConfigDict(extra="forbid")
    min_length: int = Field(ge=0, le=16)  # 0 = no minimum
    upper: StrictBool
    lower: StrictBool
    digit: StrictBool
    special: StrictBool


class LoginPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")
    require_email: StrictBool
    allow_recovery: StrictBool
    password: PasswordRules


@public_router.get("/login-options")
def login_options(db: Session = Depends(get_db)) -> dict[str, Any]:
    """What the login, enrollment and recovery pages need to show. No secrets."""
    row = settings(db)
    return {
        **settings_out(row),
        "email_recovery": row.allow_recovery and configured(row),
    }


@router.get("/admin/login-policy")
def get_policy(
    user: User = Depends(current_user), db: Session = Depends(get_db)
) -> dict[str, Any]:
    _require_owner_somewhere(db, user)
    return settings_out(settings(db))


@router.put("/admin/login-policy", dependencies=[Depends(require_csrf)])
def set_policy(
    body: LoginPolicy,
    request: Request,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    _require_owner_somewhere(db, user)
    row = settings(db)
    row.require_email = body.require_email
    row.allow_recovery = body.allow_recovery
    row.password_min_length = body.password.min_length
    row.password_upper = body.password.upper
    row.password_lower = body.password.lower
    row.password_digit = body.password.digit
    row.password_special = body.password.special
    if not body.allow_recovery:  # unused codes stop working at once
        db.execute(delete(PasswordReset).where(PasswordReset.used_at.is_(None)))
    db.commit()
    record_event(
        db,
        "login_policy_changed",
        user_id=user.id,
        ip_address=client_ip(request),
        details=settings_out(row),
    )
    return settings_out(row)


# ------------------------------------------------------------ home name


class HomeName(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=100)


@router.patch("/homes/{home_id}", dependencies=[Depends(require_csrf)])
def rename_home(
    home_id: str,
    body: HomeName,
    request: Request,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> dict[str, str]:
    require_role(db, user.id, home_id, Role.ADMIN)
    home = db.get(Home, home_id)
    if home is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found")
    old, home.name = home.name, body.name.strip()
    if not home.name:
        raise HTTPException(422, "Enter a name")
    db.commit()
    record_event(
        db,
        "home_renamed",
        user_id=user.id,
        home_id=home_id,
        ip_address=client_ip(request),
        details={"old": old, "new": home.name},
    )
    return {"id": home.id, "name": home.name}


# ------------------------------------------------------------ users without a code


class NewUser(BaseModel):
    model_config = ConfigDict(extra="forbid")
    login: str = Field(min_length=3, max_length=255)
    name: str | None = Field(default=None, max_length=100)
    role: Literal["admin", "operator", "member", "guest"]
    password: str = Field(default="", max_length=1024)  # "" if the rules allow it


@router.post(
    "/homes/{home_id}/members",
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_csrf)],
)
def create_user(
    home_id: str,
    body: NewUser,
    request: Request,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> dict[str, str]:
    """Create an account directly, with a password the owner passes on.
    Two-factor login starts off; the person can turn it on in My account."""
    require_role(db, user.id, home_id, Role.ADMIN)
    login = normalize_login(db, body.login)
    if db.scalars(select(User).where(func.lower(User.email) == login)).first():
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "That login already has an account; add it with an enrollment code instead",
        )
    check_password(db, body.password)
    created = User(
        email=login,
        name=(body.name or "").strip() or None,
        hashed_password=hash_password(body.password),
        is_active=True,
        is_totp_enabled=False,
        recovery_codes=json.dumps([hashed for _, hashed in generate_recovery_codes()]),
    )
    db.add(created)
    db.flush()
    db.add(HomeMembership(user_id=created.id, home_id=home_id, role=body.role))
    db.commit()
    record_event(
        db,
        "member_created",
        user_id=user.id,
        home_id=home_id,
        ip_address=client_ip(request),
        details={"member_id": created.id, "login": login, "role": body.role},
    )
    return {"user_id": created.id, "login": login, "role": body.role}


# ------------------------------------------------------------ recovery


@router.post(
    "/homes/{home_id}/members/{user_id}/reset-code",
    dependencies=[Depends(require_csrf)],
)
def create_reset_code(
    home_id: str,
    user_id: str,
    request: Request,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> dict[str, str]:
    """A one-time code for a member who forgot their password (24 hours)."""
    require_role(db, user.id, home_id, Role.ADMIN)
    if not settings(db).allow_recovery:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Account recovery is turned off (Settings > Admin)",
        )
    if user_id == user.id:
        raise HTTPException(
            status.HTTP_409_CONFLICT, "Use My account to change your own password"
        )
    membership = db.scalars(
        select(HomeMembership).where(
            HomeMembership.home_id == home_id, HomeMembership.user_id == user_id
        )
    ).first()
    if membership is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found")
    if membership.role == Role.ADMIN.value:
        raise HTTPException(
            status.HTTP_409_CONFLICT, "Another admin's account cannot be reset here"
        )
    raw = "".join(secrets.choice(_ALPHABET) for _ in range(16))
    code = "-".join(raw[i : i + 4] for i in range(0, 16, 4))
    reset = PasswordReset(
        user_id=user_id,
        code_hash=_hash(code),
        created_by=user.id,
        expires_at=datetime.now(UTC) + RESET_LIFETIME,
    )
    db.add(reset)
    db.commit()
    record_event(
        db,
        "reset_code_created",
        user_id=user.id,
        home_id=home_id,
        ip_address=client_ip(request),
        details={"member_id": user_id},
    )
    return {"reset_code": code, "expires_at": as_utc(reset.expires_at).isoformat()}


class NewPassword(BaseModel):
    model_config = ConfigDict(extra="forbid")
    password: str = Field(default="", max_length=1024)


@router.post(
    "/homes/{home_id}/members/{user_id}/password",
    dependencies=[Depends(require_csrf)],
)
def set_member_password(
    home_id: str,
    user_id: str,
    body: NewPassword,
    request: Request,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> dict[str, str]:
    """Admins set a new password for a member or operator (not for another
    admin, nor an owner). The person's sessions end."""
    require_role(db, user.id, home_id, Role.ADMIN)
    if user_id == user.id:
        raise HTTPException(
            status.HTTP_409_CONFLICT, "Use My account to change your own password"
        )
    membership = db.scalars(
        select(HomeMembership).where(
            HomeMembership.home_id == home_id, HomeMembership.user_id == user_id
        )
    ).first()
    target = db.get(User, user_id)
    if membership is None or target is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found")
    if membership.role not in (Role.MEMBER.value, Role.OPERATOR.value, GUEST_ROLE):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, "Admins' passwords can only be changed by them"
        )
    check_password(db, body.password)
    target.hashed_password = hash_password(body.password)
    db.execute(delete(SessionModel).where(SessionModel.user_id == user_id))
    forget_all(db, user_id)
    db.commit()
    record_event(
        db,
        "member_password_set",
        user_id=user.id,
        home_id=home_id,
        ip_address=client_ip(request),
        details={"member_id": user_id},
    )
    return {"status": "ok"}


class Recover(BaseModel):
    model_config = ConfigDict(extra="forbid")
    login: str = Field(min_length=3, max_length=255)
    code: str = Field(min_length=4, max_length=40)
    new_password: str = Field(min_length=1, max_length=1024)


@public_router.post("/recover")
def recover(
    body: Recover, request: Request, db: Session = Depends(get_db)
) -> dict[str, str]:
    """Set a new password with a reset code. Two-factor login is turned off
    (it can be set up again in My account) and every session ends."""
    if not settings(db).allow_recovery:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found")
    ip = client_ip(request)
    login = body.login.strip().lower()
    check_login_allowed("recovery", ip)
    target = db.scalars(select(User).where(func.lower(User.email) == login)).first()
    reset = None
    if target is not None:
        reset = db.scalars(
            select(PasswordReset).where(
                PasswordReset.code_hash == _hash(body.code),
                PasswordReset.user_id == target.id,
            )
        ).first()
    if (
        target is None
        or reset is None
        or reset.used_at is not None
        or as_utc(reset.expires_at) <= datetime.now(UTC)
    ):
        record_login_failure("recovery", ip)
        raise HTTPException(status.HTTP_404_NOT_FOUND, "That code is not valid")
    check_password(db, body.new_password)
    target.hashed_password = hash_password(body.new_password)
    target.is_totp_enabled = False
    target.totp_secret = None
    target.pending_totp_secret = None
    target.totp_last_step = None
    reset.used_at = datetime.now(UTC)
    db.execute(delete(SessionModel).where(SessionModel.user_id == target.id))
    forget_all(db, target.id)
    db.commit()
    record_event(db, "password_recovered", user_id=target.id, ip_address=ip)
    return {"detail": "Password changed. Log in with the new password."}
