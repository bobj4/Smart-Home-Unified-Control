"""Approved devices get a name of the person's choosing: asked when
"Remember this device" is ticked at login, and changeable in My account."""

import re

from playwright.sync_api import expect

from app.models import AuditEvent, TrustedDevice
from tests import test_ui as _ui

LOGIN = "/api/v1/auth/login"
MINE = "/api/v1/account/trusted-devices"


def remember_login(client, owner, name=None, code=None):
    body = {
        "email": owner.email,
        "password": owner.password,
        "totp_code": code or owner.totp.now(),
        "remember_device": True,
    }
    if name is not None:
        body["device_name"] = name
    return client.post(LOGIN, json=body)


def test_name_given_at_login(client, db, owner):
    assert remember_login(client, owner, "  Kitchen\n tablet ").status_code == 200
    assert db.query(TrustedDevice).one().name == "Kitchen tablet"


def test_without_a_name_the_browser_is_used(client, db, owner):
    assert remember_login(client, owner).status_code == 200
    assert db.query(TrustedDevice).one().name.endswith(" on unknown system")


def test_rename_my_own_only(client, new_client, db, owner, make_user, login, csrf):
    assert remember_login(client, owner, "Old").status_code == 200
    device = db.query(TrustedDevice).one()
    url = f"{MINE}/{device.id}"
    r = client.patch(url, json={"name": "Bedroom laptop"}, headers=csrf(client))
    assert r.status_code == 200 and r.json()["name"] == "Bedroom laptop"
    assert (
        client.patch(url, json={"name": "   "}, headers=csrf(client)).status_code == 422
    )
    assert (
        client.patch(
            url, json={"name": "x", "extra": 1}, headers=csrf(client)
        ).status_code
        == 422
    )
    other = make_user(owner.home_id, role="admin")
    o = new_client()
    assert login(o, other).status_code == 200
    assert o.patch(url, json={"name": "Mine now"}, headers=csrf(o)).status_code == 404
    db.expire_all()
    assert db.get(TrustedDevice, device.id).name == "Bedroom laptop"
    assert db.query(AuditEvent).filter_by(event_type="device_renamed").count() == 1


def test_ui_name_popup_and_rename(open_page, db, owner):
    page = open_page()
    expect(page.get_by_test_id("login-page")).to_be_visible()
    page.get_by_test_id("login-remember-device").check()
    popup = page.get_by_test_id("device-name-popup")
    expect(popup).to_be_visible()
    # Browser and system as this machine reports them ("Chrome on Windows").
    expect(popup.get_by_test_id("device-name-input")).to_have_value(
        re.compile(r"^\w+ on \w+")
    )
    popup.get_by_test_id("device-name-cancel").click()
    expect(page.get_by_test_id("login-remember-device")).not_to_be_checked()
    page.get_by_test_id("login-remember-device").check()
    page.get_by_test_id("device-name-input").fill("Living room tablet")
    page.get_by_test_id("device-name-ok").click()
    expect(popup).to_be_hidden()
    expect(page.get_by_test_id("login-remember-device")).to_be_checked()
    _ui.ui_login(page, owner)
    assert db.query(TrustedDevice).one().name == "Living room tablet"

    _ui.go_settings(page, "account")
    page.get_by_test_id("account-tab-approved").click()
    row = page.get_by_test_id("trusted-device")
    expect(row).to_contain_text("Living room tablet (this device)")
    row.get_by_test_id("trusted-device-rename").click()
    page.get_by_test_id("trusted-device-name").fill("Den tablet")
    page.get_by_test_id("trusted-device-save").click()
    expect(page.get_by_test_id("trusted-device")).to_contain_text(
        "Den tablet (this device)"
    )
    expect(page.get_by_test_id("toast")).to_have_text("Changes Saved")
