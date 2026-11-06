"""Names and logins (email or username).

  PUT /api/v1/homes/{home_id}/members/{user_id}/info  {"name", "email"}  admins
  GET/PUT /api/v1/admin/self-edit                      {"allowed"}        admins
  PUT /api/v1/account/info  {"name", "email", "password"?}  when allowed

An admin changes a person's login only if they are an admin of every home
that person is in, so one home's admin cannot take over an account used in
another home. Changing your own login needs your password.
"""

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict, Field, StrictBool
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.audit import record_event
from app.authorization import require_role
from app.db_config import get_db
from app.dependencies import client_ip, current_user, require_csrf
from app.login_policy import normalize_login, settings
from app.models import HomeMembership, Role, User
from app.routes.account import _check_password
from app.routes.login_times import require_admin

router = APIRouter(tags=["user info"])


class InfoIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str | None = Field(default=None, max_length=100)
    email: str = Field(min_length=3, max_length=255)


class OwnInfoIn(InfoIn):
    password: str | None = Field(default=None, max_length=1024)


class SelfEdit(BaseModel):
    model_config = ConfigDict(extra="forbid")
    allowed: StrictBool


def _apply(db: Session, target: User, body: InfoIn) -> bool:
    """Set the name and login. Returns whether the login changed."""
    login = normalize_login(db, body.email)
    changed = login != target.email
    if changed:
        taken = db.scalar(
            select(func.count())
            .select_from(User)
            .where(func.lower(User.email) == login, User.id != target.id)
        )
        if taken:
            raise HTTPException(status.HTTP_409_CONFLICT, "That login is already used")
        target.email = login
    target.name = (body.name or "").strip() or None
    return changed


def _info(user: User) -> dict[str, Any]:
    return {"user_id": user.id, "email": user.email, "name": user.name}


@router.put(
    "/api/v1/homes/{home_id}/members/{user_id}/info",
    dependencies=[Depends(require_csrf)],
)
def edit_member_info(
    home_id: str,
    user_id: str,
    body: InfoIn,
    request: Request,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    require_role(db, user.id, home_id, Role.ADMIN)
    target = db.get(User, user_id)
    in_home = db.scalars(
        select(HomeMembership).where(
            HomeMembership.home_id == home_id, HomeMembership.user_id == user_id
        )
    ).first()
    if target is None or in_home is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found")
    if normalize_login(db, body.email) != target.email:
        homes = db.scalars(
            select(HomeMembership.home_id).where(HomeMembership.user_id == user_id)
        ).all()
        for other in homes:
            mine = db.scalars(
                select(HomeMembership).where(
                    HomeMembership.home_id == other, HomeMembership.user_id == user.id
                )
            ).first()
            if mine is None or mine.role != Role.ADMIN.value:
                raise HTTPException(
                    status.HTTP_403_FORBIDDEN,
                    "This person is also in a home you do not run: only they can change their login",
                )
    changed = _apply(db, target, body)
    db.commit()
    record_event(
        db,
        "member_info_changed",
        user_id=user.id,
        home_id=home_id,
        ip_address=client_ip(request),
        details={"member_id": user_id, "login_changed": changed},
    )
    return _info(target)


@router.get("/api/v1/admin/self-edit")
def get_self_edit(
    user: User = Depends(current_user), db: Session = Depends(get_db)
) -> dict[str, bool]:
    require_admin(db, user)
    return {"allowed": bool(settings(db).users_edit_own_info)}


@router.put("/api/v1/admin/self-edit", dependencies=[Depends(require_csrf)])
def set_self_edit(
    body: SelfEdit,
    request: Request,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> dict[str, bool]:
    require_admin(db, user)
    settings(db).users_edit_own_info = body.allowed
    db.commit()
    record_event(
        db,
        "self_edit_changed",
        user_id=user.id,
        ip_address=client_ip(request),
        details={"allowed": body.allowed},
    )
    return {"allowed": body.allowed}


@router.put("/api/v1/account/info", dependencies=[Depends(require_csrf)])
def edit_own_info(
    body: OwnInfoIn,
    request: Request,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    if not settings(db).users_edit_own_info:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, "An admin has not allowed changing your details"
        )
    ip = client_ip(request)
    if normalize_login(db, body.email) != user.email:
        _check_password(db, user, body.password or "", ip)
    changed = _apply(db, user, body)
    db.commit()
    record_event(
        db,
        "own_info_changed",
        user_id=user.id,
        ip_address=ip,
        details={"login_changed": changed},
    )
    return _info(user)
