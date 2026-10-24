"""Rheem EcoNet in the web app, tested in a real browser.

Written by the reviewer (Rheem phase). Do not edit, skip, mark or delete these
tests. If one looks wrong, stop and report the test name and its full failure
output instead of changing it. EcoNet is faked (FakeEconet in test_rheem.py).
"""

import re

from playwright.sync_api import expect

from tests import test_rheem as _rheem
from tests import test_ui as _ui

# EcoNet fakes from test_rheem.py (pytest finds fixtures by name here).
econet = _rheem.econet
secrets_key = _rheem.secrets_key

EMAIL, PASSWORD, SERIAL = _rheem.EMAIL, _rheem.PASSWORD, _rheem.SERIAL
card, go_settings, recommended_limits, ui_login = (
    _ui.card,
    _ui.go_settings,
    _ui.recommended_limits,
    _ui.ui_login,
)


def rheem_row(section):
    return section.locator(
        '[data-testid="integration-row"][data-integration="rheem_econet"]'
    )


def test_ui_rheem_owner_connects_account_and_controls_heater(
    open_page, db, owner, econet, secrets_key
):
    recommended_limits(db, owner.home_id)  # water heater 110-120 F
    page = open_page()
    ui_login(page, owner)
    section = go_settings(page, "integrations")
    expect(section.get_by_test_id("rheem-account")).to_have_count(
        0
    )  # off: no account panel
    rheem_row(section).get_by_test_id("integration-toggle").check()
    expect(page.get_by_test_id("status")).to_have_attribute("data-kind", "success")

    panel = page.get_by_test_id("rheem-account")
    expect(panel).to_be_visible()
    expect(panel.get_by_test_id("rheem-configured")).to_contain_text(
        "No EcoNet account"
    )
    panel.get_by_test_id("rheem-email").fill(EMAIL)
    panel.get_by_test_id("rheem-password").fill("not the password")
    panel.get_by_test_id("rheem-save").click()
    expect(page.get_by_test_id("status")).to_have_attribute("data-kind", "error")
    expect(panel.get_by_test_id("rheem-password")).to_have_value("")

    panel.get_by_test_id("rheem-email").fill(EMAIL)
    panel.get_by_test_id("rheem-password").fill(PASSWORD)
    panel.get_by_test_id("rheem-save").click()
    expect(page.get_by_test_id("status")).to_have_attribute("data-kind", "success")
    panel = page.get_by_test_id("rheem-account")
    expect(panel.get_by_test_id("rheem-configured")).to_contain_text(EMAIL)
    expect(panel.get_by_test_id("rheem-password")).to_have_value("")
    assert PASSWORD not in page.content()

    panel.get_by_test_id("rheem-sync").click()
    expect(page.get_by_test_id("status")).to_have_attribute("data-kind", "success")
    expect(page.get_by_test_id("status")).to_contain_text("1 new")

    page.get_by_test_id("nav-devices").click()
    heater = card(page, "Garage water heater")
    expect(heater).to_have_attribute("data-device-type", "water_heater")
    expect(heater.get_by_test_id("target-temp")).to_have_text(
        re.compile(r"120\s*°\s*F")
    )
    expect(heater.get_by_test_id("temp-up")).to_be_disabled()  # at the safety maximum
    heater.get_by_test_id("temp-down").click()
    expect(
        card(page, "Garage water heater").get_by_test_id("target-temp")
    ).to_have_text(re.compile(r"119"))
    assert econet.set_points == [(SERIAL, 119)]


def test_ui_rheem_owner_removes_login(open_page, owner, econet, secrets_key):
    page = open_page()
    ui_login(page, owner)
    section = go_settings(page, "integrations")
    rheem_row(section).get_by_test_id("integration-toggle").check()
    panel = page.get_by_test_id("rheem-account")
    panel.get_by_test_id("rheem-email").fill(EMAIL)
    panel.get_by_test_id("rheem-password").fill(PASSWORD)
    panel.get_by_test_id("rheem-save").click()
    expect(page.get_by_test_id("rheem-configured")).to_contain_text(EMAIL)
    page.get_by_test_id("rheem-forget").click()
    expect(page.get_by_test_id("status")).to_have_attribute("data-kind", "success")
    expect(page.get_by_test_id("rheem-configured")).to_contain_text("No EcoNet account")
    expect(page.get_by_test_id("rheem-forget")).to_have_count(0)


def test_ui_rheem_admin_finds_heaters_but_never_sees_login(
    open_page, new_client, owner, make_user, econet, secrets_key, login, csrf
):
    owner_client = new_client()
    assert login(owner_client, owner).status_code == 200
    base = f"/api/v1/homes/{owner.home_id}/integrations/rheem_econet"
    assert (
        owner_client.put(
            base[: -len("/rheem_econet")] + "/rheem_econet",
            json={"enabled": True},
            headers=csrf(owner_client),
        ).status_code
        == 200
    )
    assert (
        owner_client.put(
            f"{base}/account",
            json={"email": EMAIL, "password": PASSWORD},
            headers=csrf(owner_client),
        ).status_code
        == 200
    )

    admin = make_user(owner.home_id, role="operator")
    page = open_page()
    ui_login(page, admin)
    go_settings(page, "integrations")
    panel = page.get_by_test_id("rheem-account")
    expect(panel.get_by_test_id("rheem-sync")).to_be_visible()
    expect(panel.get_by_test_id("rheem-email")).to_have_count(0)
    expect(panel.get_by_test_id("rheem-configured")).to_have_count(0)
    panel.get_by_test_id("rheem-sync").click()
    expect(page.get_by_test_id("status")).to_have_attribute("data-kind", "success")


def test_ui_rheem_hidden_from_members(open_page, owner, make_user, econet, secrets_key):
    member = make_user(owner.home_id, role="member")
    page = open_page()
    ui_login(page, member)
    go_settings(page, "account")
    expect(page.get_by_test_id("settings-nav-integrations")).to_have_count(0)
    expect(page.get_by_test_id("rheem-account")).to_have_count(0)
