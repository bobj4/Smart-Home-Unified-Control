"""Database backups (SQLite).

Copies are made with SQLite's online backup API, so they are consistent even
while the app is running, and each one is checked with PRAGMA
integrity_check. The server makes one every BACKUP_HOURS; scripts/backup.py
makes one now, lists them, or restores one (with the server stopped).

Saved logins in a backup are encrypted with SECRETS_KEY: keep that key
somewhere safe as well, or a restored database cannot use them.
"""

import asyncio
import logging
import shutil
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy.engine import make_url

from app.db_config import settings

PREFIX = "smart_home-"
log = logging.getLogger(__name__)


class BackupError(Exception):
    """The backup or restore could not be done."""


def database_path(url: str | None = None) -> Path:
    parsed = make_url(url or settings.DATABASE_URL)
    if parsed.get_backend_name() != "sqlite" or not parsed.database:
        raise BackupError("backups are only made for a SQLite database file")
    if parsed.database == ":memory:":
        raise BackupError("an in-memory database cannot be backed up")
    return Path(parsed.database).resolve()


def backup_dir() -> Path:
    if settings.BACKUP_DIR:
        return Path(settings.BACKUP_DIR).resolve()
    return database_path().parent / "backups"


def _check(path: Path) -> None:
    conn = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
    try:
        result = conn.execute("PRAGMA integrity_check").fetchone()
        conn.execute("SELECT count(*) FROM users").fetchone()  # this app's data
    except sqlite3.DatabaseError as error:
        raise BackupError(f"{path.name} is not a usable database: {error}") from None
    finally:
        conn.close()
    if result != ("ok",):
        raise BackupError(f"{path.name} failed the integrity check: {result}")


def list_backups(folder: Path | None = None) -> list[Path]:
    """Newest first."""
    folder = folder or backup_dir()
    return sorted(folder.glob(f"{PREFIX}*.db"), reverse=True)


def make_backup(
    folder: Path | None = None, keep: int | None = None, source: Path | None = None
) -> Path:
    """Write a checked copy; delete the oldest beyond `keep`. Returns its path."""
    source = source or database_path()
    if not source.exists():
        raise BackupError(f"there is no database at {source}")
    folder = folder or backup_dir()
    folder.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S-%f")
    target = folder / f"{PREFIX}{stamp}.db"
    partial = target.with_suffix(".partial")
    src = sqlite3.connect(source)
    dst = sqlite3.connect(partial)
    try:
        src.backup(dst)
    finally:
        dst.close()
        src.close()
    try:
        _check(partial)
    except BackupError:
        partial.unlink(missing_ok=True)
        raise
    partial.replace(target)
    keep = settings.BACKUP_KEEP if keep is None else keep
    for old in list_backups(folder)[max(keep, 1) :]:
        old.unlink()
    return target


def restore(backup: Path, target: Path | None = None) -> Path:
    """Replace the database with `backup` (stop the server first). The current
    database is kept next to it as *.before-restore; returns that path."""
    backup = backup.resolve()
    if not backup.is_file():
        raise BackupError(f"there is no backup at {backup}")
    _check(backup)
    target = target or database_path()
    saved = target.with_name(target.name + ".before-restore")
    if target.exists():
        shutil.copy2(target, saved)
    for extra in ("-wal", "-shm", "-journal"):
        Path(f"{target}{extra}").unlink(missing_ok=True)
    shutil.copy2(backup, target)
    return saved


async def run_forever(every_hours: float) -> None:
    """The background task started with the app (BACKUP_HOURS)."""
    while True:
        await asyncio.sleep(every_hours * 3600)
        try:
            path = await asyncio.to_thread(make_backup)
            log.info("database backed up to %s", path)
        except (BackupError, OSError, sqlite3.Error) as error:
            log.error("database backup failed: %s", error)
