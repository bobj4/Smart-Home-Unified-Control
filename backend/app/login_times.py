"""How long the login page's choices last, and "Remember this device".

Admins set three times in Settings > Admin > Login times (installation-wide,
like the other login rules). Each is a number of days, 0 for "never
expires", or None (left blank) to turn that choice off, which also hides its
checkbox on the login page:
  keep_logged_in_days   a "Keep me logged in" session (default 30)
  remember_me_days      the remembered login name (default 365)
  remember_device_days  an approved device skips the two-factor code
                        (default 0 = never expires). Turned off, approved
                        devices need the code again.

A remembered device is a random token in an HttpOnly, Secure, SameSite=Strict
cookie scoped to /api/v1; the database keeps only its SHA-256. It only
replaces the two-factor code: the password is still needed, and failures
still count towards the login rate limit. It belongs to one user, so another
person logging in on the same browser still needs their own code.
"""

import hashlib
import secrets
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.login_policy import settings
from app.models import SystemSettings, TrustedDevice

DAY = 24 * 60 * 60
DEVICE_COOKIE = "trusted_device"
DEVICE_PATH = "/api/v1"  # login, and My account (to mark "this device")
FOREVER_SECONDS = 10 * 365 * DAY  # "never expires": a cookie needs some max-age
MAX_DAYS = 100_000  # any positive number, within what a date can hold
TIMES = ("keep_logged_in_days", "remember_me_days", "remember_device_days")


def times_out(row: SystemSettings) -> dict[str, int | None]:
    return {
        name: None if getattr(row, name) is None else int(getattr(row, name))
        for name in TIMES
    }


def _seconds(days: int | None) -> int | None:
    """None: turned off. 0: never expires."""
    if days is None:
        return None
    return int(days) * DAY if days else FOREVER_SECONDS


def keep_seconds(db: Session) -> int | None:
    return _seconds(settings(db).keep_logged_in_days)


def remember_me_seconds(db: Session) -> int | None:
    return _seconds(settings(db).remember_me_days)


def device_cookie_seconds(db: Session) -> int | None:
    return _seconds(settings(db).remember_device_days)


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _as_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value


def expires_at(db: Session, device: TrustedDevice) -> datetime | None:
    days = settings(db).remember_device_days
    if not days:  # 0: never; None: the feature is off (trusted() refuses)
        return None
    return _as_utc(device.created_at) + timedelta(days=int(days))


def device_name(user_agent: str | None) -> str:
    """A readable name such as "Chrome on Windows" (never the raw header)."""
    ua = (user_agent or "").lower()
    browser = next(
        (
            name
            for key, name in (
                ("edg/", "Edge"),
                ("opr/", "Opera"),
                ("firefox/", "Firefox"),
                ("chrome/", "Chrome"),
                ("crios/", "Chrome"),
                ("safari/", "Safari"),
            )
            if key in ua
        ),
        "Browser",
    )
    system = next(
        (
            name
            for key, name in (
                ("iphone", "iPhone"),
                ("ipad", "iPad"),
                ("android", "Android"),
                ("windows", "Windows"),
                ("mac os", "Mac"),
                ("cros", "ChromeOS"),
                ("linux", "Linux"),
            )
            if key in ua
        ),
        "unknown system",
    )
    return f"{browser} on {system}"


NAME_MAX = 60


def clean_name(name: str | None) -> str | None:
    """A device name the person typed: trimmed, one line, at most NAME_MAX."""
    text = " ".join((name or "").split())[:NAME_MAX]
    return text or None


def remember(
    db: Session,
    user_id: str,
    user_agent: str | None,
    ip: str | None,
    name: str | None = None,
) -> str:
    """Approve this browser for the user; returns the cookie's token. `name`
    is what the person called it ("Kitchen tablet"); without one, the
    browser and system ("Chrome on Windows")."""
    token = secrets.token_urlsafe(32)
    db.add(
        TrustedDevice(
            user_id=user_id,
            token_hash=_hash(token),
            name=clean_name(name) or device_name(user_agent),
            ip_address=ip,
        )
    )
    db.commit()
    return token


def trusted(db: Session, user_id: str, token: str | None) -> TrustedDevice | None:
    """The user's approved device for this cookie, if still valid. An
    expired one is deleted."""
    if not token or len(token) > 100:
        return None
    device = db.scalars(
        select(TrustedDevice).where(TrustedDevice.token_hash == _hash(token))
    ).first()
    if device is None or device.user_id != user_id:
        return None
    if settings(db).remember_device_days is None:
        return None  # turned off: every device needs the code again
    ends = expires_at(db, device)
    if ends is not None and datetime.now(UTC) >= ends:
        db.delete(device)
        db.commit()
        return None
    return device


def is_current(device: TrustedDevice, token: str | None) -> bool:
    return bool(token) and device.token_hash == _hash(str(token))


def forget_all(db: Session, user_id: str) -> int:
    """Remove every approved device of a user (password change, new
    authenticator, account turned off). The caller commits."""
    result = db.execute(delete(TrustedDevice).where(TrustedDevice.user_id == user_id))
    return int(getattr(result, "rowcount", 0) or 0)


def device_out(
    db: Session, device: TrustedDevice, token: str | None = None
) -> dict[str, Any]:
    ends = expires_at(db, device)
    return {
        "id": device.id,
        "name": device.name,
        "ip_address": device.ip_address,
        "created_at": _as_utc(device.created_at).isoformat(),
        "last_used_at": _as_utc(device.last_used_at).isoformat()
        if device.last_used_at
        else None,
        "expires_at": ends.isoformat() if ends else None,
        "current": is_current(device, token),
    }
