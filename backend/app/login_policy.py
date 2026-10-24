"""Installation-wide login rules: password requirements, email or username
as the login name, and whether owners may issue recovery codes."""

import re
from typing import Any

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.models import SystemSettings

MIN_ALLOWED_LENGTH = 8  # the shortest minimum an owner can choose
MAX_PASSWORD_LENGTH = 1024
EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
USERNAME = re.compile(r"^[A-Za-z0-9._-]{3,64}$")
SPECIAL = re.compile(r"[^A-Za-z0-9]")


def settings(db: Session) -> SystemSettings:
    row = db.get(SystemSettings, 1)
    if row is None:
        row = SystemSettings(id=1)
        db.add(row)
        db.commit()
    return row


def settings_out(row: SystemSettings) -> dict[str, Any]:
    return {
        "require_email": row.require_email,
        "allow_recovery": row.allow_recovery,
        "password": {
            "min_length": row.password_min_length,
            "upper": row.password_upper,
            "lower": row.password_lower,
            "digit": row.password_digit,
            "special": row.password_special,
        },
    }


def password_problems(row: SystemSettings, password: str) -> list[str]:
    problems = []
    if len(password) < row.password_min_length:
        problems.append(f"at least {row.password_min_length} characters")
    if len(password) > MAX_PASSWORD_LENGTH:
        problems.append(f"at most {MAX_PASSWORD_LENGTH} characters")
    if row.password_upper and not re.search(r"[A-Z]", password):
        problems.append("an uppercase letter")
    if row.password_lower and not re.search(r"[a-z]", password):
        problems.append("a lowercase letter")
    if row.password_digit and not re.search(r"[0-9]", password):
        problems.append("a number")
    if row.password_special and not SPECIAL.search(password):
        problems.append("a special character")
    return problems


def check_password(db: Session, password: str) -> None:
    """Raise 422 naming every rule the password breaks."""
    problems = password_problems(settings(db), password)
    if problems:
        raise HTTPException(422, "Password needs " + ", ".join(problems))


def normalize_login(db: Session, login: str) -> str:
    """The login name to store: an email, or (if allowed) a username."""
    value = login.strip()
    if EMAIL.match(value):
        return value.lower()
    if settings(db).require_email:
        raise HTTPException(422, "Enter an email address")
    if not USERNAME.match(value):
        raise HTTPException(
            422, "Usernames are 3-64 letters, numbers, dots, dashes or underscores"
        )
    return value.lower()
