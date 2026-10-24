"""Appearance setting, deleting devices from Settings > Integrations, and the
app icons route.

Written by the reviewer. Do not edit, skip, mark or delete these tests. If
one looks wrong, stop and report the test name and its full failure output
instead of changing it.
"""

from playwright.sync_api import expect

from app.models import Device, User
from tests import test_ui as _ui

go_settings, ui_login = _ui.go_settings, _ui.ui_login


def test_theme_preference_api(client, db, owner, login, csrf):
    assert login(client, owner).status_code == 200
    assert client.get("/api/v1/account").json()["theme"] == "system"
    url = "/api/v1/account/preferences"
    assert client.put(url, json={"theme": "dark"}).status_code == 403  # no CSRF
    assert (
        client.put(url, json={"theme": "purple"}, headers=csrf(client)).status_code
        == 422
    )
    r = client.put(url, json={"theme": "dark"}, headers=csrf(client))
    assert r.status_code == 200 and r.json() == {"theme": "dark"}
    assert client.get("/api/v1/account").json()["theme"] == "dark"
    db.expire_all()
    assert db.get(User, owner.id).theme == "dark"


def test_icons_are_served_only_if_present(client):
    assert client.get("/icons/icon-192.png").status_code in (200, 404)  # 404 until made
    assert client.get("/icons/..%2Fpublic%2Findex.html").status_code == 404
    assert client.get("/icons/secret.txt").status_code == 404


def test_deleting_a_tv_removes_its_pairing(
    client, db, owner, make_device, login, csrf, monkeypatch
):
    from cryptography.fernet import Fernet

    from app import credentials

    monkeypatch.setenv("SECRETS_KEY", Fernet.generate_key().decode())
    tv = make_device(owner.home_id, device_type="tv", name="TV")
    device = db.get(Device, tv)
    device.integration = "samsung_tv"
    db.commit()
    credentials.save(
        db, owner.home_id, f"samsung_tv:{tv}", "192.168.1.50", {"token": "t"}
    )
    assert login(client, owner).status_code == 200
    r = client.delete(
        f"/api/v1/homes/{owner.home_id}/devices/{tv}", headers=csrf(client)
    )
    assert r.status_code == 200
    assert credentials.load(db, owner.home_id, f"samsung_tv:{tv}") is None


def test_ui_theme_menu(open_page, owner):
    page = open_page()
    ui_login(page, owner)
    select = go_settings(page, "account").get_by_test_id("theme-select")
    expect(select).to_have_value("system")
    assert page.evaluate("document.documentElement.dataset.theme") is None
    select.select_option("dark")
    expect(page.get_by_test_id("status")).to_have_attribute("data-kind", "success")
    assert page.evaluate("document.documentElement.dataset.theme") == "dark"
    background = page.evaluate("getComputedStyle(document.body).backgroundColor")
    assert background == "rgb(17, 19, 23)"
    page.reload()
    expect(page.get_by_test_id("app-shell")).to_be_visible()
    expect(page.locator("html")).to_have_attribute("data-theme", "dark")
    go_settings(page, "account").get_by_test_id("theme-select").select_option("light")
    expect(page.locator("html")).to_have_attribute("data-theme", "light")
    assert (
        page.evaluate("getComputedStyle(document.body).backgroundColor")
        == "rgb(244, 245, 247)"
    )


def test_ui_delete_device_from_integrations(
    open_page, db, owner, make_user, make_device
):
    lamp = make_device(owner.home_id, name="Old lamp")
    page = open_page()
    ui_login(page, owner)
    section = go_settings(page, "integrations")
    devices = section.locator(
        '[data-testid="integration-devices"][data-integration="simulated"]'
    )
    item = devices.locator(
        f'[data-testid="integration-device"][data-device-id="{lamp}"]'
    )
    expect(item).to_contain_text("Old lamp")
    item.get_by_test_id("integration-device-delete").click()
    db.expire_all()
    assert db.get(Device, lamp) is not None  # asks first
    item.get_by_test_id("integration-device-delete-confirm").click()
    expect(page.get_by_test_id("status")).to_have_attribute("data-kind", "success")
    expect(item).to_have_count(0)
    db.expire_all()
    assert db.get(Device, lamp) is None


def test_ui_members_cannot_delete_devices(open_page, owner, make_user, make_device):
    make_device(owner.home_id, name="Lamp")
    member = make_user(owner.home_id, role="member")
    page = open_page()
    ui_login(page, member)
    go_settings(page, "account")  # members only have My account
    expect(page.get_by_test_id("settings-nav-integrations")).to_have_count(0)
