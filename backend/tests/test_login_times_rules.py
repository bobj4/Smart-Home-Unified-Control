"""Login times: any number of days, 0 = never expires, blank (null) = off,
which also hides that checkbox on the login page."""

from playwright.sync_api import expect

from app.login_policy import settings
from app.login_times import FOREVER_SECONDS
from app.models import SystemSettings, TrustedDevice
from tests import test_ui as _ui

LOGIN = "/api/v1/auth/login"
TIMES = "/api/v1/admin/login-times"


def set_times(db, keep, remember, device):
    row = settings(db)  # the existing row: a new one would take the defaults
    row.keep_logged_in_days, row.remember_me_days, row.remember_device_days = (
        keep,
        remember,
        device,
    )
    db.commit()


def full_login(client, owner, code=None):
    return client.post(
        LOGIN,
        json={
            "email": owner.email,
            "password": owner.password,
            "totp_code": code or owner.totp.now(),
            "keep_logged_in": True,
            "remember_me": True,
            "remember_device": True,
        },
    )


def cookies(response):
    return {
        h.split("=", 1)[0]: h.lower() for h in response.headers.get_list("set-cookie")
    }


def test_any_number_zero_and_blank_are_accepted(client, owner, login, csrf):
    assert login(client, owner).status_code == 200
    for body in (
        {"keep_logged_in_days": 0, "remember_me_days": 0, "remember_device_days": 0},
        {
            "keep_logged_in_days": 5000,
            "remember_me_days": 1,
            "remember_device_days": 99999,
        },
        {
            "keep_logged_in_days": None,
            "remember_me_days": None,
            "remember_device_days": None,
        },
    ):
        r = client.put(TIMES, json=body, headers=csrf(client))
        assert r.status_code == 200 and r.json() == body
        assert client.get(TIMES).json() == body


def test_zero_never_expires(client, db, owner):
    set_times(db, 0, 0, 0)
    r = full_login(client, owner)
    assert r.status_code == 200
    jar = cookies(r)
    for name in ("session_token", "remembered_login", "trusted_device"):
        assert f"max-age={FOREVER_SECONDS}" in jar[name], name


def test_blank_turns_each_choice_off(client, new_client, db, owner):
    set_times(db, None, None, None)
    r = full_login(client, owner)
    assert r.status_code == 200
    jar = cookies(r)
    assert "max-age" not in jar["session_token"]  # ends with the browser
    assert "trusted_device" not in jar
    assert "max-age" not in jar.get("remembered_login", "max-age=0").replace(
        "max-age=0", ""
    )
    assert db.query(TrustedDevice).count() == 0
    info = new_client().get("/api/v1/auth/remembered").json()
    assert info["keep_days"] is None
    assert info["remember_me"] is False and info["remember_device"] is False


def test_turning_remember_device_off_refuses_approved_devices(
    client, new_client, db, owner
):
    set_times(db, 30, 365, 0)
    assert full_login(client, owner).status_code == 200
    assert db.query(TrustedDevice).count() == 1
    token = client.cookies.get("trusted_device")
    set_times(db, 30, 365, None)
    browser = new_client()
    browser.cookies.set("trusted_device", token, path="/api/v1")
    r = browser.post(LOGIN, json={"email": owner.email, "password": owner.password})
    assert r.status_code == 401  # the code is needed again


def test_ui_hidden_checkboxes_and_descriptions(open_page, db, owner):
    set_times(db, None, 365, None)
    page = open_page()
    expect(page.get_by_test_id("login-page")).to_be_visible()
    expect(page.get_by_test_id("login-keep")).to_be_hidden()
    expect(page.get_by_test_id("login-remember-device")).to_be_hidden()
    expect(page.get_by_test_id("login-remember")).to_be_visible()
    _ui.ui_login(page, owner)
    _ui.go_settings(page, "admin")
    times = page.get_by_test_id("login-times")
    keep = times.get_by_test_id("login-time-keep_logged_in_days")
    expect(keep).to_have_value("")
    expect(times).to_contain_text("0 = until logging out")
    expect(times).to_contain_text("Blank = off")
    warning = times.get_by_test_id("login-times-forever-warning")
    expect(warning).to_be_hidden()
    keep.fill("0")
    expect(warning).to_be_visible()
    times.get_by_test_id("login-time-remember_device_days").fill("0")
    times.get_by_test_id("login-times-save").click()
    expect(page.get_by_test_id("status")).to_contain_text("Login times saved")
    db.expire_all()
    row = db.get(SystemSettings, 1)
    assert (row.keep_logged_in_days, row.remember_device_days) == (0, 0)
    page.get_by_test_id("logout").click()
    expect(page.get_by_test_id("login-keep")).to_be_visible()
    expect(page.get_by_test_id("login-keep-label")).to_have_text("Keep me logged in")
