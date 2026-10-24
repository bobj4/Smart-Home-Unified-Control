"""Database backups: making, checking, keeping and restoring them.

Written by the reviewer (backups phase). Do not edit, skip, mark or delete
these tests. If one looks wrong, stop and report the test name and its full
failure output instead of changing it.
"""

import os
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

from app import backup
from app.models import User

BACKEND = Path(__file__).resolve().parent.parent


def users_in(path):
    with sqlite3.connect(path) as conn:
        return {row[0] for row in conn.execute("SELECT email FROM users")}


def test_backup_is_a_checked_copy(db, owner, tmp_path):
    path = backup.make_backup(tmp_path, keep=5)
    assert path.parent == tmp_path
    assert path.name.startswith("smart_home-") and path.suffix == ".db"
    assert owner.email in users_in(path)
    assert not list(tmp_path.glob("*.partial"))
    assert backup.list_backups(tmp_path) == [path]


def test_only_the_newest_are_kept(db, owner, tmp_path):
    made = [backup.make_backup(tmp_path, keep=3) for _ in range(5)]
    assert backup.list_backups(tmp_path) == list(reversed(made[-3:]))


def test_restore_replaces_and_keeps_the_previous(db, owner, make_user, tmp_path):
    saved = backup.make_backup(tmp_path, keep=5)
    copy = tmp_path / "live.db"
    copy.write_bytes(saved.read_bytes())
    with sqlite3.connect(copy) as conn:
        conn.execute("DELETE FROM users")
    previous = backup.restore(saved, target=copy)
    assert owner.email in users_in(copy)
    assert previous.name == "live.db.before-restore"
    assert users_in(previous) == set()


def test_bad_backups_are_refused(tmp_path):
    junk = tmp_path / "smart_home-junk.db"
    junk.write_bytes(b"not a database at all" * 100)
    target = tmp_path / "live.db"
    target.write_bytes(b"keep me")
    with pytest.raises(backup.BackupError):
        backup.restore(junk, target=target)
    with pytest.raises(backup.BackupError):
        backup.restore(tmp_path / "missing.db", target=target)
    empty = tmp_path / "empty.db"
    sqlite3.connect(empty).close()
    with pytest.raises(backup.BackupError, match="not a usable database"):
        backup.restore(empty, target=target)
    assert target.read_bytes() == b"keep me"


def test_only_sqlite_files():
    with pytest.raises(backup.BackupError):
        backup.database_path("postgresql://u@localhost/db")
    with pytest.raises(backup.BackupError):
        backup.database_path("sqlite:///:memory:")
    assert backup.database_path("sqlite:///./x.db") == (Path.cwd() / "x.db")


def test_backup_script(db, owner, tmp_path, monkeypatch):

    env = {**os.environ, "BACKUP_DIR": str(tmp_path)}
    run = [sys.executable, str(BACKEND / "scripts" / "backup.py")]
    done = subprocess.run(run, env=env, capture_output=True, text=True, timeout=60)
    assert done.returncode == 0, done.stdout + done.stderr
    assert "Backed up to" in done.stdout
    (made,) = backup.list_backups(tmp_path)
    listed = subprocess.run(
        [*run, "--list"], env=env, capture_output=True, text=True, timeout=60
    )
    assert str(made) in listed.stdout
    refused = subprocess.run(
        [*run, "--restore", str(made)],
        env=env,
        input="n\n",
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert refused.returncode == 1 and "Nothing changed" in refused.stdout
    assert db.query(User).filter_by(email=owner.email).count() == 1
