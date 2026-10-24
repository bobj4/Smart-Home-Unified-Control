"""Login page: "Remember me" (an HttpOnly cookie keeps the login name) and "Keep me
logged in" (a 30-day session that survives closing the browser). Written by
the reviewer. Do not edit, skip, mark or delete these tests."""

import time
from datetime import UTC, datetime, timedelta

from playwright.sync_api import expect

from app.db_config import settings
from app.models import AuditEvent
from app.models import Session as SessionModel
from app.sessions import as_utc
from tests import test_ui as _ui

LOGIN = "/api/v1/auth/login"
ui_login = _ui.ui_login


def body(user, code, **extra):
    return {"email": user.email, "password": user.password, "totp_code": code, **extra}


def cookie_header(response, name):
    return next(
        h for h in response.headers.get_list("set-cookie") if h.startswith(name + "=")
    )


def test_normal_login_ends_with_the_browser(client, db, owner):
    r = client.post(LOGIN, json=body(owner, owner.totp.now()))
    assert r.status_code == 200
    assert "max-age" not in cookie_header(r, "session_token").lower()  # browser session
    session = db.query(SessionModel).one()
    assert session.keep is False
    left = as_utc(session.expires_at) - datetime.now(UTC)
    assert left <= timedelta(seconds=settings.TOTAL_TIMEOUT_SECONDS)
    # 31 idle minutes end it.
    session.last_activity = datetime.now(UTC) - timedelta(minutes=31)
    db.commit()
    assert client.get("/api/v1/account").status_code == 401


def test_keep_logged_in_lasts_30_days(client, db, owner):
    r = client.post(LOGIN, json=body(owner, owner.totp.now(), keep_logged_in=True))
    assert r.status_code == 200
    header = cookie_header(r, "session_token").lower()
    assert f"max-age={30 * 24 * 3600}" in header
    assert "httponly" in header and "secure" in header and "samesite=strict" in header
    session = db.query(SessionModel).one()
    assert session.keep is True
    left = as_utc(session.expires_at) - datetime.now(UTC)
    assert timedelta(days=29, hours=23) < left <= timedelta(days=30)
    # Not ended by being idle, only by its 30 days.
    session.last_activity = datetime.now(UTC) - timedelta(days=3)
    db.commit()
    assert client.get("/api/v1/account").status_code == 200
    db.expire_all()
    session = db.query(SessionModel).one()
    session.expires_at = datetime.now(UTC) - timedelta(seconds=1)
    db.commit()
    assert client.get("/api/v1/account").status_code == 401
    event = db.query(AuditEvent).filter_by(event_type="login_success").one()
    assert '"keep_logged_in": true' in (event.details or "")


def test_keep_logged_in_must_be_a_boolean(client, owner):
    r = client.post(LOGIN, json=body(owner, owner.totp.now(), keep_logged_in="yes"))
    assert r.status_code == 422


def test_logout_ends_a_kept_session(client, db, owner, csrf):
    assert (
        client.post(
            LOGIN, json=body(owner, owner.totp.now(), keep_logged_in=True)
        ).status_code
        == 200
    )
    assert client.post("/api/v1/auth/logout", headers=csrf(client)).status_code == 200
    assert db.query(SessionModel).count() == 0


def test_remember_me_keeps_only_the_login_name(client, owner):
    assert client.get("/api/v1/auth/remembered").json()["login"] == ""
    r = client.post(LOGIN, json=body(owner, owner.totp.now(), remember_me=True))
    assert r.status_code == 200
    header = cookie_header(r, "remembered_login").lower()
    assert "httponly" in header and "secure" in header and "samesite=strict" in header
    assert owner.password.lower() not in header
    assert client.get("/api/v1/auth/remembered").json()["login"] == owner.email
    # Logging out keeps it; logging in without remember me forgets it.
    csrf_token = client.cookies.get("csrf_token")
    client.post("/api/v1/auth/logout", headers={"X-CSRF-Token": csrf_token})
    assert client.get("/api/v1/auth/remembered").json()["login"] == owner.email
    r = client.post(LOGIN, json=body(owner, owner.totp.at(time.time() + 30)))
    assert r.status_code == 200
    assert client.get("/api/v1/auth/remembered").json()["login"] == ""


def test_remember_me_must_be_a_boolean(client, owner):
    r = client.post(LOGIN, json=body(owner, owner.totp.now(), remember_me="yes"))
    assert r.status_code == 422


def test_failed_login_does_not_remember(client, owner):
    bad = {"email": owner.email, "password": "wrong", "remember_me": True}
    assert client.post(LOGIN, json=bad).status_code == 401
    assert client.get("/api/v1/auth/remembered").json()["login"] == ""


def test_ui_remember_me_and_keep_logged_in(open_page, db, owner):
    page = open_page()
    expect(page.get_by_test_id("login-remember")).not_to_be_checked()
    page.get_by_test_id("login-remember").check()
    page.get_by_test_id("login-keep").check()
    ui_login(page, owner)
    session = db.query(SessionModel).one()
    assert session.keep is True
    page.get_by_test_id("logout").click()
    expect(page.get_by_test_id("login-page")).to_be_visible()
    page.reload()
    expect(page.get_by_test_id("login-email")).to_have_value(owner.email)  # remembered
    expect(page.get_by_test_id("login-remember")).to_be_checked()
    expect(page.get_by_test_id("login-password")).to_have_value("")  # never a password
    # Unticking it forgets the name at the next login.
    page.get_by_test_id("login-remember").uncheck()
    ui_login(page, owner, owner.totp.at(time.time() + 30))  # an unused code
    page.get_by_test_id("logout").click()
    expect(page.get_by_test_id("login-page")).to_be_visible()
    page.reload()
    expect(page.get_by_test_id("login-email")).to_have_value("")
