"""Homes the caller belongs to, and more of them (Admin > Home).

  GET    /api/v1/homes                      my homes, in my order
  POST   /api/v1/homes                      add a home (admins of a home):
                                            I become its admin
  PUT    /api/v1/homes/{id}/icon-image      a picture of one's own (admins)
  DELETE /api/v1/homes/{id}/icon-image      back to the built-in icon
  PUT    /api/v1/account/home-order         the order of my homes (the top
                                            one opens first on a first login)
  PUT    /api/v1/account/last-home          the home I last viewed (opened
                                            first next time)

Name, address and built-in icon: PATCH /api/v1/admin/homes/{id} (admin.py).
"""

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.audit import record_event
from app.authorization import require_role
from app.db_config import get_db
from app.dependencies import client_ip, current_user, require_csrf
from app.home_icons import ICONS, IconError, check_picture
from app.models import Home, HomeMembership, Role, User
from app.safety import apply_recommended

router = APIRouter(prefix="/api/v1", tags=["homes"])


def home_out(home: Home, role: str | None = None) -> dict[str, Any]:
    out: dict[str, Any] = {
        "id": home.id,
        "name": home.name,
        "address": home.address,
        "icon": home.icon or "house",
        "icon_image": home.icon_image,
    }
    if role is not None:
        out["role"] = role
    return out


def my_homes(db: Session, user_id: str) -> list[tuple[Home, str]]:
    """(home, my role) in my order: position, then name."""
    rows = db.execute(
        select(Home, HomeMembership.role)
        .join(HomeMembership, HomeMembership.home_id == Home.id)
        .where(HomeMembership.user_id == user_id)
        .order_by(HomeMembership.position, Home.name)
    )
    return [(home, role) for home, role in rows]


@router.get("/homes")
def list_homes(
    user: User = Depends(current_user), db: Session = Depends(get_db)
) -> list[dict[str, Any]]:
    return [home_out(h, role) for h, role in my_homes(db, user.id)]


class NewHome(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=100)
    address: str | None = Field(default=None, max_length=300)
    icon: str | None = Field(default=None, max_length=20)


@router.post(
    "/homes", status_code=status.HTTP_201_CREATED, dependencies=[Depends(require_csrf)]
)
def add_home(
    body: NewHome,
    request: Request,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Add a home. Admins of a home may add more; the one who adds it is its
    admin, and it goes to the bottom of their list."""
    admin_of = db.scalars(
        select(HomeMembership.id).where(
            HomeMembership.user_id == user.id, HomeMembership.role == Role.ADMIN.value
        )
    ).first()
    if admin_of is None and not user.is_superuser:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only an admin can add a home")
    name = body.name.strip()
    if not name:
        raise HTTPException(422, "Enter a name")
    if body.icon and body.icon not in ICONS:
        raise HTTPException(422, "choose one of the icons")
    last = db.scalar(
        select(func.max(HomeMembership.position)).where(
            HomeMembership.user_id == user.id
        )
    )
    home = Home(
        name=name,
        address=(body.address or "").strip() or None,
        icon=body.icon or None,
    )
    db.add(home)
    db.flush()
    db.add(
        HomeMembership(
            user_id=user.id,
            home_id=home.id,
            role=Role.ADMIN.value,
            position=(last or 0) + 1,
        )
    )
    db.commit()
    ip = client_ip(request)
    apply_recommended(db, home.id, user_id=user.id, ip_address=ip)
    record_event(
        db,
        "home_created",
        user_id=user.id,
        home_id=home.id,
        ip_address=ip,
        details={"name": home.name},
    )
    return home_out(home, Role.ADMIN.value)


class Picture(BaseModel):
    model_config = ConfigDict(extra="forbid")
    data_url: str = Field(max_length=140_000)


def _admin_home(db: Session, user: User, home_id: str) -> Home:
    require_role(db, user.id, home_id, Role.ADMIN)
    home = db.get(Home, home_id)
    if home is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found")
    return home


@router.put("/homes/{home_id}/icon-image", dependencies=[Depends(require_csrf)])
def set_icon_image(
    home_id: str,
    body: Picture,
    request: Request,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    home = _admin_home(db, user, home_id)
    try:
        home.icon_image = check_picture(body.data_url)
    except IconError as error:
        raise HTTPException(422, str(error)) from None
    db.commit()
    record_event(
        db,
        "home_icon_changed",
        user_id=user.id,
        home_id=home_id,
        ip_address=client_ip(request),
        details={"picture": True},
    )
    return home_out(home)


@router.delete("/homes/{home_id}/icon-image", dependencies=[Depends(require_csrf)])
def remove_icon_image(
    home_id: str,
    request: Request,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    home = _admin_home(db, user, home_id)
    home.icon_image = None
    db.commit()
    record_event(
        db,
        "home_icon_changed",
        user_id=user.id,
        home_id=home_id,
        ip_address=client_ip(request),
        details={"picture": False},
    )
    return home_out(home)


class HomeOrder(BaseModel):
    model_config = ConfigDict(extra="forbid")
    home_ids: list[str] = Field(min_length=1, max_length=200)


@router.put("/account/home-order", dependencies=[Depends(require_csrf)])
def set_home_order(
    body: HomeOrder, user: User = Depends(current_user), db: Session = Depends(get_db)
) -> list[dict[str, Any]]:
    """My homes top to bottom (any I leave out keep their place after)."""
    rows = {
        m.home_id: m
        for m in db.scalars(
            select(HomeMembership).where(HomeMembership.user_id == user.id)
        )
    }
    if any(home_id not in rows for home_id in body.home_ids):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found")
    order = list(dict.fromkeys(body.home_ids))
    rest = sorted(
        (m for home_id, m in rows.items() if home_id not in order),
        key=lambda m: m.position,
    )
    for position, membership in enumerate([rows[h] for h in order] + rest):
        membership.position = position
    db.commit()
    return [home_out(h, role) for h, role in my_homes(db, user.id)]


class LastHome(BaseModel):
    model_config = ConfigDict(extra="forbid")
    home_id: str = Field(min_length=1, max_length=36)


@router.put("/account/last-home", dependencies=[Depends(require_csrf)])
def set_last_home(
    body: LastHome, user: User = Depends(current_user), db: Session = Depends(get_db)
) -> dict[str, str]:
    member = db.scalars(
        select(HomeMembership.id).where(
            HomeMembership.user_id == user.id, HomeMembership.home_id == body.home_id
        )
    ).first()
    if member is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found")
    user.last_home_id = body.home_id
    db.commit()
    return {"home_id": body.home_id}
