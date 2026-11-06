"""What happens after repeated failed logins (Settings > Admin > Failed
logins), set like the login times: each a number, blank = off.

  lockout after     this many failures in a row block the account for
                    lockout minutes, or, with 0 minutes, until its password
                    is reset (by an admin, a reset code, or reset-login)
  lockdown after    this many failures in a row turn the account off until
                    an admin turns it on again (Settings > Admin > Users)

Both can be on: for example a 15-minute lockout after 5, and a lockdown after
20. The count keeps going through a lockout (guesses during one are refused
without counting) and starts again after a correct login.

Failures count only for accounts that exist; the answer stays the same
generic one, so it reveals nothing. A locked account learns why only after
giving the right password.
"""

from datetime import UTC, datetime, timedelta

from sqlalchemy import event, func, select
from sqlalchemy.orm import Session

from app.audit import record_event
from app.login_policy import settings
from app.models import Session as SessionModel
from app.models import SystemSettings, User

MAX_NUMBER = 100_000
# "Until the password is reset": a date that never comes.
UNTIL_RESET = datetime(9999, 1, 1, tzinfo=UTC)


def rules_out(row: SystemSettings) -> dict[str, int | None]:
    return {
        "lockout_after": row.login_lockout_after,
        "lockout_minutes": row.login_lockout_minutes,
        "lockdown_after": row.login_lockdown_after,
    }


def _as_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value


def locked_until(user: User) -> datetime | None:
    """When the lockout ends (UNTIL_RESET: at a password reset), if locked."""
    if user.locked_until is None:
        return None
    ends = _as_utc(user.locked_until)
    return ends if ends > datetime.now(UTC) else None


def locked_message(ends: datetime) -> str:
    if ends >= UNTIL_RESET:
        return "This account is locked after too many failed logins. Ask an admin to reset its password."
    minutes = max(1, int((ends - datetime.now(UTC)).total_seconds() // 60) + 1)
    return f"This account is locked after too many failed logins. Try again in {minutes} minute{'s' if minutes != 1 else ''}, or ask an admin to reset its password."


def succeeded(db: Session, user: User) -> None:
    """A correct login: the count starts again. The caller commits."""
    user.failed_logins = 0
    user.locked_until = None


def failed(db: Session, login_name: str, ip: str | None) -> None:
    """Count a failed login for the account with this name, if there is one,
    and lock it or turn it off when the admin's rule says so."""
    user = db.scalars(
        select(User).where(func.lower(User.email) == login_name.strip().lower())
    ).first()
    if user is None or not user.is_active:
        return
    row = settings(db)
    lockout_after, lockdown_after = row.login_lockout_after, row.login_lockdown_after
    if row.login_lockout_minutes is None:
        lockout_after = None  # lockouts are off
    if not lockout_after and not lockdown_after:
        return
    if locked_until(user) is not None:
        return  # already locked: guesses do not extend it
    user.failed_logins = int(user.failed_logins or 0) + 1
    count = user.failed_logins
    if lockdown_after and count >= lockdown_after:
        user.is_active = False
        user.failed_logins = 0
        db.query(SessionModel).filter(SessionModel.user_id == user.id).delete()
        db.commit()
        record_event(
            db,
            "account_locked_down",
            user_id=user.id,
            ip_address=ip,
            details={"failures": count},
        )
        return
    if lockout_after and count % lockout_after == 0:
        minutes = int(row.login_lockout_minutes or 0)
        user.locked_until = (
            UNTIL_RESET
            if minutes == 0
            else datetime.now(UTC) + timedelta(minutes=minutes)
        )
        db.commit()
        record_event(
            db,
            "account_locked",
            user_id=user.id,
            ip_address=ip,
            details={"failures": count, "minutes": minutes},
        )
        return
    db.commit()


@event.listens_for(User.hashed_password, "set")
def _password_set(target: User, value: object, old: object, initiator: object) -> None:
    """A new password (from any path) ends a lockout."""
    target.locked_until = None
    target.failed_logins = 0


@event.listens_for(User.is_active, "set")
def _turned_on(target: User, value: object, old: object, initiator: object) -> None:
    """An admin turning the account on again starts the count afresh."""
    if value:
        target.failed_logins = 0
        target.locked_until = None
