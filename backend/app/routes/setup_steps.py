"""Settings > Admin > Setting up: what is left to do on a new server.

  GET /api/v1/admin/setup?home_id=...   admins

Each step says whether it is done and where it is done. Nothing is changed
here; the steps link to the pages that do it.
"""

import os
from typing import Any

from fastapi import APIRouter, Depends, Request
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.auth import verify_password
from app.bootstrap import DEFAULT_PASSWORD
from app.db_config import get_db
from app.dependencies import current_user
from app.features import integration_enabled
from app.login_policy import settings
from app.mailer import configured
from app.models import Device, Home, HomeMembership, User
from app.routes.login_times import require_admin

router = APIRouter(prefix="/api/v1/admin", tags=["setup"])
BRANDS = ("cync", "samsung_tv", "rheem_econet", "frigate")


def _first_password_kept(user: User) -> bool:
    """Still the first-start password (the default, or the installer's)."""
    candidates = {DEFAULT_PASSWORD, os.environ.get("FIRST_ADMIN_PASSWORD") or ""}
    return any(p and verify_password(p, user.hashed_password) for p in candidates)


@router.get("/setup")
def setup_steps(
    request: Request,
    home_id: str | None = None,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    require_admin(db, user)
    home = None
    if home_id:
        mine = db.scalars(
            select(HomeMembership).where(
                HomeMembership.home_id == home_id, HomeMembership.user_id == user.id
            )
        ).first()
        home = db.get(Home, home_id) if mine else None
    row = settings(db)
    devices = 0
    brands = False
    if home is not None:
        devices = (
            db.scalar(
                select(func.count())
                .select_from(Device)
                .where(Device.home_id == home.id, Device.integration != "simulated")
            )
            or 0
        )
        brands = any(integration_enabled(db, home.id, b) for b in BRANDS)
    people = db.scalar(select(func.count()).select_from(User)) or 0
    secure = request.url.scheme == "https"
    steps = [
        (
            "password",
            "Change the first password",
            not _first_password_kept(user),
            "#/settings/account",
        ),
        (
            "two_factor",
            "Turn on two-factor login for yourself",
            bool(user.is_totp_enabled),
            "#/settings/account",
        ),
        (
            "home_name",
            "Name your home",
            home is not None and home.name != "Home",
            "#/settings/admin",
        ),
        (
            "brands",
            "Turn on your brands (Cync, Samsung TV, ...)",
            brands,
            "#/settings/integrations",
        ),
        ("devices", "Add your devices", devices > 0, "#/settings/integrations"),
        ("people", "Invite the people in your home", people > 1, "#/settings/admin"),
        (
            "https",
            "Open the app over HTTPS (needed to install it on phones)",
            secure,
            "#/settings/admin",
        ),
        (
            "email",
            "Set up email, for password resets",
            configured(row),
            "#/settings/admin",
        ),
    ]
    out = [
        {"id": i, "label": label, "done": done, "href": href}
        for i, label, done, href in steps
    ]
    return {"steps": out, "done": sum(s["done"] for s in out), "total": len(out)}
