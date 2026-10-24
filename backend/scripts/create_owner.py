"""Create the first owner account, their home, and their TOTP secret.

Run from backend/:  ../.venv/Scripts/python.exe -m scripts.create_owner

Refuses to run if an owner already exists. Prints the TOTP key and the
recovery codes once; only hashes of the recovery codes are stored (SEC-06).
"""

import json
import sys

from sqlalchemy import select

from app import db_config, init_db
from app.auth import (
    generate_recovery_codes,
    generate_totp_provisioning_uri,
    generate_totp_secret,
    hash_password,
)
from app.models import Home, HomeMembership, Role, User
from app.safety import apply_recommended

MIN_PASSWORD_LENGTH = 12


def main() -> int:
    init_db()
    with db_config.SessionLocal() as db:
        if db.scalars(select(User).where(User.is_superuser.is_(True))).first():
            print(
                "ERROR: An owner already exists. This script only creates the first one."
            )
            return 1

    email = input("Owner email address: ").strip()
    if not email or "@" not in email:
        print("ERROR: Invalid email address.")
        return 1
    password = input("Password (at least 12 characters): ").strip()
    if len(password) < MIN_PASSWORD_LENGTH:
        print(f"ERROR: Password must be at least {MIN_PASSWORD_LENGTH} characters.")
        return 1

    totp_secret = generate_totp_secret()
    codes = generate_recovery_codes()

    with db_config.SessionLocal() as db:
        owner = User(
            email=email,
            hashed_password=hash_password(password),
            name=email.split("@")[0],
            is_active=True,
            is_superuser=True,
            totp_secret=totp_secret,
            is_totp_enabled=True,
            recovery_codes=json.dumps([hashed for _, hashed in codes]),
        )
        home = Home(name="Home")
        db.add_all([owner, home])
        db.flush()
        db.add(HomeMembership(user_id=owner.id, home_id=home.id, role=Role.ADMIN.value))
        db.commit()
        apply_recommended(db, home.id, user_id=owner.id, ip_address="cli")

    print()
    print("Owner created. Shown once only; save these now:")
    print()
    print("Add this account to your authenticator app:")
    print(f"  {generate_totp_provisioning_uri(email, totp_secret)}")
    print(f"  Key (manual entry): {totp_secret}")
    print()
    print("Recovery codes (each works once if you lose the authenticator):")
    for i, (plain, _) in enumerate(codes, 1):
        print(f"  {i:2d}. {plain}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
