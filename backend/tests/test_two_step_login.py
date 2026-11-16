"""Login on two screens: name and password, then, only for accounts with
two-factor on, the code (with "Remember this device")."""

from playwright.sync_api import expect

from app.models import AuditEvent, User
from tests import test_ui as _ui

LOGIN = "/api/v1/auth/login"


def test_code_missing_is_flagged_only_with_the_right_password(client, db, owner):
    r = client.post(LOGIN, json={"email": owner.email, "password": owner.password})
    assert r.status_code == 401 and r.json()["code_required"] is True
    assert "session_token" not in r.headers.get("set-cookie", "")
    wrong = client.post(LOGIN, json={"email": owner.email, "password": "not it"})
    assert wrong.status_code == 401 and "code_required" not in wrong.json()
    # Asking for the code is not a failed login (lockouts do not count it).
    assert db.query(AuditEvent).filter_by(event_type="login_failure").count() == 1


def test_ui_two_screens(open_page, owner):
    page = open_page()
    expect(page.get_by_test_id("login-step1")).to_be_visible()
    expect(page.get_by_test_id("login-code")).to_be_hidden()
    expect(page.get_by_test_id("login-remember-device")).to_be_hidden()
    _ui.submit_login(page, owner.email, owner.password)
    expect(page.get_by_test_id("login-step2")).to_be_visible()
    expect(page.get_by_test_id("login-step1")).to_be_hidden()
    expect(page.get_by_test_id("login-remember-device")).to_be_visible()
    page.get_by_test_id("login-code").fill(
        "000000" if owner.totp.now() != "000000" else "111111"
    )
    page.get_by_test_id("login-code-submit").click()
    expect(page.get_by_test_id("login-error")).to_contain_text("That code did not work")
    page.get_by_test_id("login-back").click()
    expect(page.get_by_test_id("login-step1")).to_be_visible()
    _ui.ui_login(page, owner)


def test_ui_no_second_screen_without_two_factor(open_page, db, owner):
    user = db.get(User, owner.id)
    user.is_totp_enabled, user.totp_secret = False, None
    db.commit()
    page = open_page()
    _ui.submit_login(page, owner.email, owner.password)
    expect(page.get_by_test_id("app-shell")).to_be_visible()


def test_ui_wrong_password_stays_on_screen_one(open_page, owner):
    page = open_page()
    _ui.submit_login(page, owner.email, "wrong password")
    expect(page.get_by_test_id("login-error")).to_contain_text("Login failed")
    expect(page.get_by_test_id("login-step2")).to_be_hidden()
