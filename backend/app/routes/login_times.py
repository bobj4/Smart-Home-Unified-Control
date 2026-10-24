"""Login times (admins) and remembered devices.

  GET/PUT /api/v1/admin/login-times             how long login choices last
  GET     /api/v1/account/trusted-devices       my remembered devices
  DELETE  /api/v1/account/trusted-devices/{id}  forget one of mine
  GET     /api/v1/admin/trusted-devices         every remembered device of
                                                the people in my homes
  DELETE  /api/v1/admin/trusted-devices/{id}    forget one of theirs

An admin sees the devices of everyone who shares a home where they are an
admin (SEC-11: never other homes' people).
"""

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict, StrictInt
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.audit import record_event
from app.db_config import get_db
from app.dependencies import client_ip, current_user, require_csrf
from app.login_policy import settings
from app.login_times import DEVICE_COOKIE, LIMITS, device_out, times_out
from app.models import HomeMembership, Role, TrustedDevice, User

router = APIRouter(prefix="/api/v1", tags=["login times"])


class LoginTimes(BaseModel):
    model_config = ConfigDict(extra="forbid")
    keep_logged_in_days: StrictInt
    remember_me_days: StrictInt
    remember_device_days: StrictInt  # 0 = forever


def _admin_homes(db: Session, user: User) -> list[str]:
    return list(
        db.scalars(
            select(HomeMembership.home_id).where(
                HomeMembership.user_id == user.id,
                HomeMembership.role == Role.ADMIN.value,
            )
        ).all()
    )


def require_admin(db: Session, user: User) -> list[str]:
    homes = _admin_homes(db, user)
    if not homes:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only an admin can see this")
    return homes


def _people(db: Session, homes: list[str]) -> dict[str, User]:
    """Everyone in these homes, by id."""
    users = db.scalars(
        select(User)
        .join(HomeMembership, HomeMembership.user_id == User.id)
        .where(HomeMembership.home_id.in_(homes))
    ).all()
    return {u.id: u for u in users}


@router.get("/admin/login-times")
def get_login_times(
    user: User = Depends(current_user), db: Session = Depends(get_db)
) -> dict[str, int]:
    require_admin(db, user)
    return times_out(settings(db))


@router.put("/admin/login-times", dependencies=[Depends(require_csrf)])
def set_login_times(
    body: LoginTimes,
    request: Request,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> dict[str, int]:
    require_admin(db, user)
    values = body.model_dump()
    for name, (low, high) in LIMITS.items():
        if not low <= values[name] <= high:
            raise HTTPException(422, f"{name} must be {low} to {high} days")
    row = settings(db)
    before = times_out(row)
    for name, value in values.items():
        setattr(row, name, value)
    db.commit()
    record_event(
        db,
        "login_times_changed",
        user_id=user.id,
        ip_address=client_ip(request),
        details={"before": before, "after": times_out(row)},
    )
    return times_out(row)


@router.get("/account/trusted-devices")
def my_devices(
    request: Request,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> list[dict[str, Any]]:
    token = request.cookies.get(DEVICE_COOKIE)
    devices = db.scalars(
        select(TrustedDevice)
        .where(TrustedDevice.user_id == user.id)
        .order_by(TrustedDevice.created_at.desc())
    ).all()
    return [device_out(db, d, token) for d in devices]


def _forget(db: Session, device: TrustedDevice, by: User, request: Request) -> None:
    owner = device.user_id
    db.delete(device)
    db.commit()
    record_event(
        db,
        "device_forgotten",
        user_id=by.id,
        ip_address=client_ip(request),
        details={"device_owner": owner, "device": device.name},
    )


@router.delete(
    "/account/trusted-devices/{device_id}", dependencies=[Depends(require_csrf)]
)
def forget_mine(
    device_id: str,
    request: Request,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> dict[str, str]:
    device = db.get(TrustedDevice, device_id)
    if device is None or device.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found")
    _forget(db, device, user, request)
    return {"detail": "Device forgotten"}


@router.get("/admin/trusted-devices")
def all_devices(
    request: Request,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> list[dict[str, Any]]:
    people = _people(db, require_admin(db, user))
    token = request.cookies.get(DEVICE_COOKIE)
    devices = db.scalars(
        select(TrustedDevice)
        .where(TrustedDevice.user_id.in_(list(people)))
        .order_by(TrustedDevice.created_at.desc())
    ).all()
    return [
        {
            **device_out(db, d, token),
            "user_id": d.user_id,
            "user": people[d.user_id].email,
            "user_name": people[d.user_id].name,
        }
        for d in devices
    ]


@router.delete(
    "/admin/trusted-devices/{device_id}", dependencies=[Depends(require_csrf)]
)
def forget_theirs(
    device_id: str,
    request: Request,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> dict[str, str]:
    people = _people(db, require_admin(db, user))
    device = db.get(TrustedDevice, device_id)
    if device is None or device.user_id not in people:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found")
    _forget(db, device, user, request)
    return {"detail": "Device forgotten"}
