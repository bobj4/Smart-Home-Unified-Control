"""Add simulated demo devices to the only home, for trying the web app.
(Turning on Demo devices in Settings > Integrations does the same.)

Run from backend/:  ../.venv/Scripts/python.exe -m scripts.add_demo_devices
"""

import sys

from sqlalchemy import select

from app import db_config, init_db
from app.demo import add_demo_devices
from app.models import Home


def main() -> int:
    init_db()
    with db_config.SessionLocal() as db:
        homes = list(db.scalars(select(Home)))
        if len(homes) != 1:
            print("ERROR: expected exactly one home. Run scripts.create_owner first.")
            return 1
        added = add_demo_devices(db, homes[0].id)
    print(f"Demo devices added: {added}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
