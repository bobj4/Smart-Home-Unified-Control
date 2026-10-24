"""Set safety limits from the command line (owner's machine only).

Run from backend/:
  ../.venv/Scripts/python.exe -m scripts.set_safety_limits thermostat 60 80 F
  ../.venv/Scripts/python.exe -m scripts.set_safety_limits water_heater 110 120 F --default 120
  ../.venv/Scripts/python.exe -m scripts.set_safety_limits --recommended

If there is more than one home, add --home <home id>. The change is audited.
"""

import argparse
import sys

from sqlalchemy import select

from app import db_config, init_db
from app.models import Home
from app.safety import (
    LIMITED_TYPES,
    LimitsError,
    apply_recommended,
    limits_out,
    set_limits,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("device_type", nargs="?", choices=LIMITED_TYPES)
    parser.add_argument("min_temperature", nargs="?", type=float)
    parser.add_argument("max_temperature", nargs="?", type=float)
    parser.add_argument("unit", nargs="?", choices=("F", "C"))
    parser.add_argument("--default", type=float, help="target for new devices")
    parser.add_argument(
        "--recommended", action="store_true", help="recommended limits for all types"
    )
    parser.add_argument("--home", help="home id (needed only with several homes)")
    parser.add_argument("--disable", action="store_true", help="turn control off")
    args = parser.parse_args(argv)

    init_db()
    with db_config.SessionLocal() as db:
        homes = list(db.scalars(select(Home)))
        if args.home:
            homes = [h for h in homes if h.id == args.home]
        if len(homes) != 1:
            print("ERROR: give --home with one of these ids:")
            for home in db.scalars(select(Home)):
                print(f"  {home.id}  {home.name}")
            return 1
        if args.recommended:
            apply_recommended(db, homes[0].id, user_id=None, ip_address="cli")
            print(f"Recommended limits saved for {homes[0].name}.")
            return 0
        if None in (
            args.device_type,
            args.min_temperature,
            args.max_temperature,
            args.unit,
        ):
            parser.error("give device_type min max unit, or --recommended")
        try:
            limits = set_limits(
                db,
                home_id=homes[0].id,
                device_type=args.device_type,
                unit=args.unit,
                min_temperature=args.min_temperature,
                max_temperature=args.max_temperature,
                enabled=not args.disable,
                default_target=args.default,
                user_id=None,
                ip_address="cli",
            )
        except LimitsError as error:
            print(f"ERROR: {error}")
            return 1
        print(f"Saved for {homes[0].name}: {limits_out(limits)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
