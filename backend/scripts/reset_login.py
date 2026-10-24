"""Reset a locked-out account from the server itself (needs access to this
machine, so it is not an internet-facing way in).

Run from backend/ with the app server stopped:
  ../.venv/Scripts/python.exe -m scripts.reset_login

Sets a new password, turns two-factor login off, and ends the account's
sessions. Set up an authenticator again afterwards in Settings > My account.
"""

import sys
from getpass import getpass

from sqlalchemy import delete, func, select

from app import db_config, init_db, login_policy
from app.audit import record_event
from app.auth import hash_password
from app.models import Session as SessionModel
from app.models import User


def main() -> int:
    init_db()
    email = input("Email of the account to reset: ").strip().lower()
    with db_config.SessionLocal() as db:
        user = db.scalars(select(User).where(func.lower(User.email) == email)).first()
        if user is None:
            print("ERROR: no account with that email. Accounts:")
            for row in db.scalars(select(User).order_by(User.email)):
                print(f"  {row.email}")
            return 1
        rules = login_policy.settings(db)
        password = getpass(
            f"New password (at least {rules.password_min_length} characters): "
        )
        problems = login_policy.password_problems(rules, password)
        if problems:
            print(
                "ERROR: the password needs "
                + ", ".join(problems)
                + "; nothing changed."
            )
            return 1
        if getpass("Repeat it: ") != password:
            print("ERROR: the passwords do not match; nothing changed.")
            return 1
        user.hashed_password = hash_password(password)
        user.is_totp_enabled = False
        user.totp_secret = None
        user.pending_totp_secret = None
        user.totp_last_step = None
        db.execute(delete(SessionModel).where(SessionModel.user_id == user.id))
        db.commit()
        record_event(db, "login_reset_on_server", user_id=user.id, ip_address="cli")
    print("Done. Log in with the email and the new password (no code needed),")
    print("then set up an authenticator again in Settings > My account.")
    print(
        "If a home requires two-factor login, you must set it up before using that home."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
