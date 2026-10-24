"""Database backups.

    python scripts/backup.py              make a backup now
    python scripts/backup.py --list       list backups, newest first
    python scripts/backup.py --restore FILE
                                          replace the database with FILE
                                          (stop the server first)

Backups go to backend/backups (or BACKUP_DIR); the newest BACKUP_KEEP (14)
are kept. The server also makes one every BACKUP_HOURS (24; 0 = never).
Keep SECRETS_KEY safe too: saved logins in a backup are encrypted with it.
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import backup  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Database backups.")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--list", action="store_true", help="list backups")
    group.add_argument("--restore", metavar="FILE", help="restore this backup")
    args = parser.parse_args()
    try:
        if args.list:
            found = backup.list_backups()
            for path in found:
                print(f"{path}  ({path.stat().st_size // 1024} KB)")
            if not found:
                print(f"No backups in {backup.backup_dir()}")
        elif args.restore:
            answer = input(
                "Stop the server first. Replace the database with this backup? [y/N] "
            )
            if answer.strip().lower() != "y":
                print("Nothing changed.")
                return 1
            saved = backup.restore(Path(args.restore))
            print(f"Restored. The previous database was kept as {saved}")
        else:
            print(f"Backed up to {backup.make_backup()}")
    except backup.BackupError as error:
        print(f"Failed: {error}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
