"""The first account's password can come from FIRST_ADMIN_PASSWORD (the
Linux installer sets a random one), instead of the documented "admin". The
password itself never goes in the server's output."""

import sys

import pytest

from app.bootstrap import ensure_default_admin
from app.models import User
from tests.test_admin import password_login

RANDOM = "Kq7mZpR4tWx9bNc3hJd2"


def test_first_admin_with_a_given_password(client, db):
    assert ensure_default_admin(db, RANDOM) is True
    assert db.query(User).one().email == "admin"
    assert password_login(client, "admin", "admin").status_code == 401
    assert password_login(client, "admin", RANDOM).status_code == 200


def test_a_given_password_does_nothing_once_there_are_accounts(client, db, owner):
    assert ensure_default_admin(db, RANDOM) is False
    assert db.query(User).filter_by(email="admin").count() == 0


@pytest.mark.parametrize(
    ("env", "works", "says"),
    [
        (RANDOM, RANDOM, "FIRST_ADMIN_PASSWORD"),
        ("", "admin", 'password "admin"'),
    ],
)
def test_serve_uses_the_setting(client, db, monkeypatch, capsys, env, works, says):
    from scripts import serve

    monkeypatch.setenv("FIRST_ADMIN_PASSWORD", env)
    monkeypatch.setattr(serve.uvicorn, "run", lambda *a, **k: None)
    monkeypatch.setattr(sys, "argv", ["serve.py"])
    assert serve.main() == 0
    out = capsys.readouterr().out
    assert says in out
    assert RANDOM not in out  # never printed
    assert password_login(client, "admin", works).status_code == 200
