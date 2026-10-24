"""First start: with no accounts at all, create the default account
(username "admin", password "admin") and its home, and turn off the email
requirement so usernames work. Change that password straight away."""

import json

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import generate_recovery_codes, hash_password
from app.login_policy import settings
from app.models import Home, HomeMembership, Role, User
from app.safety import apply_recommended

DEFAULT_LOGIN = "admin"
# The documented first-start password; the admin is told to change it.
DEFAULT_PASSWORD = "admin"  # nosec B105


def ensure_default_admin(db: Session) -> bool:
    """Returns True if the default account was created now."""
    if db.scalars(select(User.id)).first() is not None:
        return False
    settings(db).require_email = False
    user = User(
        email=DEFAULT_LOGIN,
        hashed_password=hash_password(DEFAULT_PASSWORD),
        name="Admin",
        is_active=True,
        is_superuser=True,
        is_totp_enabled=False,
        recovery_codes=json.dumps([hashed for _, hashed in generate_recovery_codes()]),
    )
    home = Home(name="Home")
    db.add_all([user, home])
    db.flush()
    db.add(HomeMembership(user_id=user.id, home_id=home.id, role=Role.ADMIN.value))
    db.commit()
    apply_recommended(db, home.id, user_id=user.id, ip_address="first-start")
    return True
