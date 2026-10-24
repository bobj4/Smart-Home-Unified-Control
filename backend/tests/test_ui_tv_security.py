"""Two-factor settings and Samsung TVs in the web app, in a real browser.

Written by the reviewer (TV and two-factor phase). Do not edit, skip, mark or
delete these tests. If one looks wrong, stop and report the test name and its
full failure output instead of changing it. TVs are faked (FakeTv in
test_samsung.py).
"""

import re
import time

import pyotp
from playwright.sync_api import expect

from app.models import Home
from tests import test_samsung as _samsung
from tests import test_ui as _ui

# Fakes from test_samsung.py (pytest finds fixtures by name here).
tv = _samsung.tv
secrets_key = _samsung.secrets_key
HOST, TOKEN = _samsung.HOST, _samsung.TOKEN
card, go_settings, ui_login = _ui.card, _ui.go_settings, _ui.ui_login


def code_after(secret, steps):
    return pyotp.TOTP(secret).at(int(time.time()) + 30 * steps)


def api_turn_off(new_client, login, csrf, user):
    c = new_client()
    assert login(c, user).status_code == 200
    r = c.post(
        "/api/v1/account/totp/disable",
        json={"password": user.password, "totp_code": code_after(user.totp_secret, 1)},
        headers=csrf(c),
    )
    assert r.status_code == 200, r.text


# ------------------------------------------------------------ T1: two-factor


def test_ui_two_factor_off_then_login_with_password_only(open_page, owner):
    page = open_page()
    ui_login(page, owner)
    box = go_settings(page, "account").get_by_test_id("two-factor")
    expect(box.get_by_test_id("two-factor-status")).to_contain_text("On")
    box.get_by_test_id("two-factor-password").fill(owner.password)
    box.get_by_test_id("two-factor-code").fill(code_after(owner.totp_secret, 1))
    box.get_by_test_id("two-factor-off").click()
    expect(page.get_by_test_id("status")).to_have_attribute("data-kind", "success")
    expect(box.get_by_test_id("two-factor-status")).to_contain_text("Off")
    expect(box.get_by_test_id("two-factor-off")).to_have_count(0)

    page.get_by_test_id("logout").click()
    page.get_by_test_id("login-email").fill(owner.email)
    page.get_by_test_id("login-password").fill(owner.password)
    page.get_by_test_id("login-submit").click()  # no code
    expect(page.get_by_test_id("app-shell")).to_be_visible()


def test_ui_two_factor_back_on(open_page, new_client, owner, login, csrf):
    api_turn_off(new_client, login, csrf, owner)
    page = open_page()
    page.get_by_test_id("login-email").fill(owner.email)
    page.get_by_test_id("login-password").fill(owner.password)
    page.get_by_test_id("login-submit").click()
    expect(page.get_by_test_id("app-shell")).to_be_visible()
    section = go_settings(page, "account")
    expect(section.get_by_test_id("two-factor-status")).to_contain_text("Off")
    section.get_by_test_id("totp-password").fill(owner.password)
    section.get_by_test_id("totp-start").click()
    secret = re.sub(r"\s", "", section.get_by_test_id("totp-secret").inner_text())
    section.get_by_test_id("totp-code").fill(pyotp.TOTP(secret).now())
    section.get_by_test_id("totp-confirm").click()
    expect(page.get_by_test_id("status")).to_have_attribute("data-kind", "success")
    expect(section.get_by_test_id("two-factor-status")).to_contain_text("On")


def test_ui_owner_requires_two_factor(
    open_page, new_client, db, owner, make_user, login
):
    member = make_user(owner.home_id, role="member")
    page = open_page()
    ui_login(page, owner)
    section = go_settings(page, "admin")
    toggle = section.get_by_test_id("require-2fa-toggle")
    expect(toggle).not_to_be_checked()
    toggle.check()
    expect(page.get_by_test_id("status")).to_have_attribute("data-kind", "success")
    db.expire_all()
    assert db.get(Home, owner.home_id).require_two_factor is True

    member_page = open_page()
    ui_login(member_page, member)
    box = go_settings(member_page, "account").get_by_test_id("two-factor")
    expect(box.get_by_test_id("two-factor-required")).to_be_visible()
    expect(box.get_by_test_id("two-factor-off")).to_have_count(0)
    expect(member_page.get_by_test_id("settings-nav-members")).to_have_count(0)
    expect(member_page.get_by_test_id("require-2fa-toggle")).to_have_count(0)


def test_ui_require_refused_when_owner_has_no_two_factor(
    open_page, new_client, owner, login, csrf
):
    api_turn_off(new_client, login, csrf, owner)
    page = open_page()
    page.get_by_test_id("login-email").fill(owner.email)
    page.get_by_test_id("login-password").fill(owner.password)
    page.get_by_test_id("login-submit").click()
    toggle = go_settings(page, "admin").get_by_test_id("require-2fa-toggle")
    toggle.check()
    expect(page.get_by_test_id("status")).to_have_attribute("data-kind", "error")
    expect(toggle).not_to_be_checked()


# ------------------------------------------------------------ T2: Samsung TVs


def samsung_row(section):
    return section.locator(
        '[data-testid="integration-row"][data-integration="samsung_tv"]'
    )


def test_ui_samsung_add_pair_control_remove(open_page, owner, tv, secrets_key):
    page = open_page()
    ui_login(page, owner)
    section = go_settings(page, "integrations")
    expect(section.get_by_test_id("samsung-tvs")).to_have_count(0)
    samsung_row(section).get_by_test_id("integration-toggle").check()
    panel = page.get_by_test_id("samsung-tvs")
    expect(panel).to_be_visible()

    panel.get_by_test_id("samsung-name").fill("Living room TV")
    panel.get_by_test_id("samsung-host").fill(HOST)
    panel.get_by_test_id("samsung-add").click()
    expect(page.get_by_test_id("status")).to_have_attribute("data-kind", "success")
    row = panel.get_by_test_id("samsung-tv-row")
    expect(row).to_have_count(1)
    expect(row.get_by_test_id("samsung-paired")).to_contain_text("Not paired")
    row.get_by_test_id("samsung-pair").click()
    expect(page.get_by_test_id("status")).to_have_attribute("data-kind", "success")
    expect(
        panel.get_by_test_id("samsung-tv-row").get_by_test_id("samsung-paired")
    ).to_have_text(re.compile("^Paired"))
    assert tv.paired == [(HOST, "tizen")]

    page.get_by_test_id("nav-devices").click()
    card(page, "Living room TV").get_by_test_id("tv-remote-open").click()
    remote = page.get_by_test_id("tv-remote")
    expect(remote.get_by_test_id("remote-volume-level")).to_have_count(
        0
    )  # no exact volume on real TVs
    remote.get_by_test_id("remote-power").click()
    expect(remote.get_by_test_id("remote-volume-up")).to_be_enabled()
    remote.get_by_test_id("remote-volume-up").click()
    expect(page.get_by_test_id("status")).to_have_attribute("data-kind", "success")
    assert [k for (_, _, _, k) in tv.keys] == [["KEY_POWER"], ["KEY_VOLUP"]]
    remote.get_by_test_id("remote-close").click()

    panel = go_settings(page, "integrations").page.get_by_test_id("samsung-tvs")
    panel.get_by_test_id("samsung-remove").click()
    expect(page.get_by_test_id("status")).to_have_attribute("data-kind", "success")
    expect(panel.get_by_test_id("samsung-tv-row")).to_have_count(0)


def test_ui_samsung_legacy_tv(open_page, owner, tv):
    page = open_page()
    ui_login(page, owner)
    samsung_row(go_settings(page, "integrations")).get_by_test_id(
        "integration-toggle"
    ).check()
    panel = page.get_by_test_id("samsung-tvs")
    panel.get_by_test_id("samsung-name").fill("Old TV")
    panel.get_by_test_id("samsung-host").fill("192.168.1.60")
    panel.get_by_test_id("samsung-legacy").check()
    panel.get_by_test_id("samsung-add").click()
    expect(panel.get_by_test_id("samsung-tv-row")).to_contain_text("legacy")
    panel.get_by_test_id("samsung-tv-row").get_by_test_id("samsung-pair").click()
    expect(page.get_by_test_id("status")).to_have_attribute("data-kind", "success")
    assert tv.paired == [("192.168.1.60", "legacy")]


def test_ui_samsung_bad_address_shows_error(open_page, owner, tv):
    page = open_page()
    ui_login(page, owner)
    samsung_row(go_settings(page, "integrations")).get_by_test_id(
        "integration-toggle"
    ).check()
    panel = page.get_by_test_id("samsung-tvs")
    panel.get_by_test_id("samsung-name").fill("Somewhere TV")
    panel.get_by_test_id("samsung-host").fill("8.8.8.8")
    panel.get_by_test_id("samsung-add").click()
    expect(page.get_by_test_id("status")).to_have_attribute("data-kind", "error")
    expect(panel.get_by_test_id("samsung-tv-row")).to_have_count(0)


def test_ui_samsung_hidden_from_members(
    open_page, new_client, owner, make_user, login, csrf, tv
):
    owner_client = new_client()
    assert login(owner_client, owner).status_code == 200
    _samsung.turn_on(owner_client, csrf, owner.home_id)
    member = make_user(owner.home_id, role="member")
    page = open_page()
    ui_login(page, member)
    go_settings(page, "account")
    expect(page.get_by_test_id("settings-nav-integrations")).to_have_count(0)
    expect(page.get_by_test_id("samsung-tvs")).to_have_count(0)
