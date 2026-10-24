"""Household members, and one-time enrollment codes for adding them."""

import hashlib
import json
import secrets
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import delete, func, select
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
from app.authorization import require_role
from app.db_config import get_db
from app.dependencies import client_ip, current_user, require_csrf
from app.login_policy import check_password, normalize_login
from app.login_times import forget_all
from app.models import Enrollment, HomeMembership, Role, User
from app.models import Session as SessionModel
from app.rate_limiter import check_login_allowed, record_login_failure
from app.sessions import as_utc

router = APIRouter(prefix="/api/v1/homes/{home_id}/members", tags=["members"])
enroll_router = APIRouter(prefix="/api/v1/enroll", tags=["enroll"])

ENROLLMENT_LIFETIME = timedelta(hours=24)
_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # no 0/O, 1/I


def _new_code() -> str:
    raw = "".join(secrets.choice(_ALPHABET) for _ in range(16))
    return "-".join(raw[i : i + 4] for i in range(0, 16, 4))


def _hash_code(code: str) -> str:
    # Case, spaces and dashes do not matter: "abcd efgh..." matches "ABCD-EFGH-...".
    normalized = "".join(c for c in code.upper() if c.isalnum())
    return hashlib.sha256(normalized.encode()).hexdigest()


class EnrollmentCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    email: str = Field(min_length=3, max_length=255)  # email, or a username if allowed
    name: str | None = Field(default=None, max_length=100)
    role: Literal["admin", "operator", "member"]


class RoleChange(BaseModel):
    model_config = ConfigDict(extra="forbid")
    role: Literal["admin", "operator", "member"]


def _membership(db: Session, home_id: str, user_id: str) -> HomeMembership:
    membership = db.scalars(
        select(HomeMembership).where(
            HomeMembership.home_id == home_id, HomeMembership.user_id == user_id
        )
    ).first()
    if membership is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found")
    return membership


@router.get("")
def list_members(
    home_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)
) -> list[dict[str, Any]]:
    require_role(db, user.id, home_id, Role.ADMIN)
    rows = db.execute(
        select(User, HomeMembership.role)
        .join(HomeMembership, HomeMembership.user_id == User.id)
        .where(HomeMembership.home_id == home_id)
        .order_by(User.email)
    )
    return [
        {
            "user_id": u.id,
            "email": u.email,
            "name": u.name,
            "role": role,
        }
        for u, role in rows
    ]


@router.patch("/{user_id}", dependencies=[Depends(require_csrf)])
def change_role(
    home_id: str,
    user_id: str,
    body: RoleChange,
    request: Request,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> dict[str, str]:
    require_role(db, user.id, home_id, Role.ADMIN)
    if user_id == user.id:
        raise HTTPException(status.HTTP_409_CONFLICT, "You cannot change your own role")
    membership = _membership(db, home_id, user_id)
    old = membership.role
    membership.role = body.role
    db.commit()
    record_event(
        db,
        "member_role_changed",
        user_id=user.id,
        home_id=home_id,
        ip_address=client_ip(request),
        details={"member_id": user_id, "old": old, "new": body.role},
    )
    return {"user_id": user_id, "role": body.role}


@router.delete("/{user_id}", dependencies=[Depends(require_csrf)])
def remove_member(
    home_id: str,
    user_id: str,
    request: Request,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> dict[str, str]:
    require_role(db, user.id, home_id, Role.ADMIN)
    if user_id == user.id:
        raise HTTPException(status.HTTP_409_CONFLICT, "You cannot remove yourself")
    db.delete(_membership(db, home_id, user_id))
    db.flush()
    remaining = db.scalar(
        select(func.count())
        .select_from(HomeMembership)
        .where(HomeMembership.user_id == user_id)
    )
    if not remaining:
        # In no home any more: the account is closed and its login freed, so
        # the same email or username can be used again. Kept (deactivated)
        # so the activity log still shows who did what.
        db.execute(delete(SessionModel).where(SessionModel.user_id == user_id))
        forget_all(db, user_id)
        gone = db.get(User, user_id)
        if gone is not None:
            gone.email = f"deleted:{gone.id}"
            gone.is_active = False
            # Not an Argon2 hash, so no password matches it.
            gone.hashed_password = "!"  # nosec B105
    db.commit()
    record_event(
        db,
        "member_removed",
        user_id=user.id,
        home_id=home_id,
        ip_address=client_ip(request),
        details={"member_id": user_id},
    )
    return {"detail": "Member removed"}


@router.post(
    "/enrollments",
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_csrf)],
)
def create_enrollment(
    home_id: str,
    body: EnrollmentCreate,
    request: Request,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> dict[str, str]:
    """Create a one-time code for a new member. The code is returned once."""
    require_role(db, user.id, home_id, Role.ADMIN)
    email = normalize_login(db, body.email)
    existing = db.scalars(select(User).where(func.lower(User.email) == email)).first()
    if (
        existing is not None
        and db.scalars(
            select(HomeMembership).where(
                HomeMembership.home_id == home_id, HomeMembership.user_id == existing.id
            )
        ).first()
    ):
        raise HTTPException(status.HTTP_409_CONFLICT, "Already a member of this home")
    code = _new_code()
    enrollment = Enrollment(
        home_id=home_id,
        email=email,
        name=body.name,
        role=body.role,
        code_hash=_hash_code(code),
        created_by=user.id,
        expires_at=datetime.now(UTC) + ENROLLMENT_LIFETIME,
    )
    db.add(enrollment)
    db.commit()
    record_event(
        db,
        "enrollment_created",
        user_id=user.id,
        home_id=home_id,
        ip_address=client_ip(request),
        details={"enrollment_id": enrollment.id, "email": email, "role": body.role},
    )
    return {
        "id": enrollment.id,
        "enrollment_code": code,
        "expires_at": as_utc(enrollment.expires_at).isoformat(),
    }


@router.get("/enrollments")
def list_enrollments(
    home_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)
) -> list[dict[str, Any]]:
    require_role(db, user.id, home_id, Role.ADMIN)
    now = datetime.now(UTC)
    rows = db.scalars(
        select(Enrollment)
        .where(Enrollment.home_id == home_id, Enrollment.used_at.is_(None))
        .order_by(Enrollment.created_at)
    )
    return [
        {
            "id": e.id,
            "email": e.email,
            "role": e.role,
            "expires_at": as_utc(e.expires_at).isoformat(),
        }
        for e in rows
        if as_utc(e.expires_at) > now
    ]


@router.delete("/enrollments/{enrollment_id}", dependencies=[Depends(require_csrf)])
def cancel_enrollment(
    home_id: str,
    enrollment_id: str,
    request: Request,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> dict[str, str]:
    require_role(db, user.id, home_id, Role.ADMIN)
    enrollment = db.get(Enrollment, enrollment_id)
    if enrollment is None or enrollment.home_id != home_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found")
    db.delete(enrollment)
    db.commit()
    record_event(
        db,
        "enrollment_cancelled",
        user_id=user.id,
        home_id=home_id,
        ip_address=client_ip(request),
        details={"enrollment_id": enrollment_id},
    )
    return {"detail": "Cancelled"}


# ---------------------------------------------------------------- enrollment


class EnrollStart(BaseModel):
    model_config = ConfigDict(extra="forbid")
    code: str = Field(min_length=4, max_length=40)


class EnrollFinish(BaseModel):
    model_config = ConfigDict(extra="forbid")
    code: str = Field(min_length=4, max_length=40)
    password: str = Field(min_length=1, max_length=1024)  # rules: app/login_policy.py
    # Not needed for an existing account with two-factor turned off.
    totp_code: str | None = Field(default=None, min_length=6, max_length=6)


def _valid_enrollment(db: Session, code: str, ip: str | None) -> Enrollment:
    check_login_allowed("enrollment", ip)
    enrollment = db.scalars(
        select(Enrollment).where(Enrollment.code_hash == _hash_code(code))
    ).first()
    if (
        enrollment is None
        or enrollment.used_at is not None
        or as_utc(enrollment.expires_at) <= datetime.now(UTC)
    ):
        record_login_failure("enrollment", ip)
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Invalid or expired code")
    return enrollment


def _existing_user(db: Session, email: str) -> User | None:
    return db.scalars(select(User).where(func.lower(User.email) == email)).first()


@enroll_router.post("/start")
def start_enrollment(
    body: EnrollStart, request: Request, db: Session = Depends(get_db)
) -> dict[str, Any]:
    """Check a code. A new account gets an authenticator secret to scan;
    an existing account confirms with its own password and authenticator."""
    enrollment = _valid_enrollment(db, body.code, client_ip(request))
    if _existing_user(db, enrollment.email) is not None:
        existing = _existing_user(db, enrollment.email)
        return {
            "email": enrollment.email,
            "existing_account": True,
            "two_factor": bool(existing and existing.is_totp_enabled),
        }
    if not enrollment.pending_totp_secret:
        enrollment.pending_totp_secret = generate_totp_secret()
        db.commit()
    secret = enrollment.pending_totp_secret
    uri = generate_totp_provisioning_uri(enrollment.email, secret)
    return {
        "email": enrollment.email,
        "existing_account": False,
        "totp_secret": secret,
        "otpauth_uri": uri,
        "qr_svg": totp_qr_svg(uri),
    }


@enroll_router.post("/finish")
def finish_enrollment(
    body: EnrollFinish, request: Request, db: Session = Depends(get_db)
) -> dict[str, Any]:
    ip = client_ip(request)
    enrollment = _valid_enrollment(db, body.code, ip)
    user = _existing_user(db, enrollment.email)
    recovery: list[str] = []
    if user is not None:
        step = None
        if user.is_totp_enabled and user.totp_secret and body.totp_code:
            step = verify_totp_code(
                body.totp_code, user.totp_secret, user.totp_last_step
            )
        code_ok = step is not None or not user.is_totp_enabled
        if not verify_password(body.password, user.hashed_password) or not code_ok:
            record_login_failure("enrollment", ip)
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Password or code incorrect")
        if step is not None:
            user.totp_last_step = step
    else:
        secret = enrollment.pending_totp_secret
        step = (
            verify_totp_code(body.totp_code, secret)
            if secret and body.totp_code
            else None
        )
        if step is None:
            record_login_failure("enrollment", ip)
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Code does not match")
        check_password(db, body.password)
        codes = generate_recovery_codes()
        recovery = [plain for plain, _ in codes]
        user = User(
            email=enrollment.email,
            name=enrollment.name,
            hashed_password=hash_password(body.password),
            is_active=True,
            totp_secret=secret,
            is_totp_enabled=True,
            totp_last_step=step,
            recovery_codes=json.dumps([hashed for _, hashed in codes]),
        )
        db.add(user)
        db.flush()
    db.add(
        HomeMembership(
            user_id=user.id, home_id=enrollment.home_id, role=enrollment.role
        )
    )
    enrollment.used_at = datetime.now(UTC)
    enrollment.pending_totp_secret = None
    db.commit()
    record_event(
        db,
        "member_added",
        user_id=user.id,
        home_id=enrollment.home_id,
        ip_address=ip,
        details={"role": enrollment.role, "enrollment_id": enrollment.id},
    )
    return {"email": user.email, "recovery_codes": recovery}
