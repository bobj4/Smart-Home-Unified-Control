"""Password hashing, TOTP and recovery codes.

SEC-01: Argon2id password hashing.
SEC-06: Single-use recovery codes, stored as Argon2id hashes.
SEC-07: A TOTP code is accepted at most once (time step must increase).
"""

import hmac
import json
import secrets
from datetime import UTC, datetime

import pyotp
import segno
from argon2 import PasswordHasher, Type
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError
from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import User

ph = PasswordHasher(
    type=Type.ID,
    time_cost=2,
    memory_cost=65536,
    parallelism=4,
    hash_len=32,
    salt_len=16,
)

# Verified against when the account does not exist, so an unknown email costs
# the same time as a wrong password (H4).
_DUMMY_HASH = ph.hash(secrets.token_urlsafe(16))

RECOVERY_CODE_COUNT = 10


def hash_password(password: str) -> str:
    return ph.hash(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    try:
        return ph.verify(hashed_password, plain_password)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def authenticate_user(db: Session, email: str, password: str) -> User | None:
    """Return the active user if the password matches, else None.

    Always runs one Argon2 verification, whether or not the account exists.
    """
    # Login names are matched without regard to case (Email@x.com = email@x.com).
    user = db.scalars(
        select(User).where(func.lower(User.email) == email.lower())
    ).first()
    if user is None:
        verify_password(password, _DUMMY_HASH)
        return None
    if not verify_password(password, user.hashed_password) or not user.is_active:
        return None
    return user


def generate_totp_secret() -> str:
    return pyotp.random_base32()


def verify_totp_code(
    code: str,
    totp_secret: str,
    last_step: int | None = None,
    valid_window: int = 1,
) -> int | None:
    """Return the time step the code belongs to, or None if it is not valid.

    Accepts the current step and `valid_window` steps either side. A code whose
    step is not greater than `last_step` (already used, or older) is refused.
    """
    if len(code) != 6 or not code.isdigit():
        return None
    totp = pyotp.TOTP(totp_secret)
    current = totp.timecode(datetime.now(UTC))
    for step in range(current + valid_window, current - valid_window - 1, -1):
        if hmac.compare_digest(code, totp.generate_otp(step)):
            if last_step is not None and step <= last_step:
                return None
            return step
    return None


def generate_recovery_codes() -> list[tuple[str, str]]:
    """Return RECOVERY_CODE_COUNT (plain_code, argon2_hash) pairs.

    Plain codes are 8 random digits; show them once and store only the hashes.
    """
    codes = []
    for _ in range(RECOVERY_CODE_COUNT):
        plain = f"{secrets.randbelow(100_000_000):08d}"
        codes.append((plain, ph.hash(plain)))
    return codes


def verify_recovery_code(code: str, db: Session, user_id: str) -> bool:
    """Check a recovery code and mark it used. The caller commits.

    Raises HTTPException(404) if the user does not exist.
    """
    user = db.get(User, str(user_id))
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    if not user.recovery_codes:
        return False
    stored: list[str | None] = json.loads(user.recovery_codes)
    for i, stored_hash in enumerate(stored):
        if stored_hash is None:
            continue
        try:
            ph.verify(stored_hash, code)
        except (VerifyMismatchError, VerificationError, InvalidHashError):
            continue
        stored[i] = None
        user.recovery_codes = json.dumps(stored)
        db.flush()
        return True
    return False


def generate_totp_provisioning_uri(
    email: str, totp_secret: str, issuer: str = "SmartHome"
) -> str:
    return pyotp.TOTP(totp_secret).provisioning_uri(name=email, issuer_name=issuer)


def totp_qr_svg(otpauth_uri: str) -> str:
    """The provisioning URI as a QR code: an SVG data URI for an <img> src.
    Black on white, so it scans in dark mode too."""
    return segno.make(otpauth_uri, error="m").svg_data_uri(
        scale=4, border=2, dark="#000000", light="#ffffff"
    )
