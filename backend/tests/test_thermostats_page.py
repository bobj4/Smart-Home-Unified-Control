"""Thermostats on a page of their own, and optionally only there: the
home's choice, set by admins for everyone and every screen."""

from playwright.sync_api import expect

from app.models import Device
from tests import test_ui as _ui


def _home(db, owner, make_device):
    make_device(owner.home_id, name="Lamp")
    make_device(owner.home_id, device_type="thermostat", name="Hallway")


def test_api_thermostats_apart(client, new_client, owner, make_user, login, csrf):
    assert login(client, owner).status_code == 200
    url = f"/api/v1/homes/{owner.home_id}/layout"
    pages = f"/api/v1/homes/{owner.home_id}/device-pages"
    assert client.get(url).json()["thermostats_apart"] is False
    r = client.put(url, json={"thermostats_apart": True}, headers=csrf(client))
    assert r.status_code == 200 and r.json()["thermostats_apart"] is True
    # The home's: every screen, everyone.
    assert client.get(f"{url}?screen=phone").json()["thermostats_apart"] is True
    bad = client.put(url, json={"thermostats_apart": "yes"}, headers=csrf(client))
    assert bad.status_code == 422
    member = make_user(owner.home_id, role="member")
    them = new_client()
    assert login(them, member).status_code == 200
    assert them.get(url).json()["thermostats_apart"] is True
    assert them.get(pages).json() == {"thermostats_apart": True, "doors_apart": False}
    # Only admins change it; sending what it already is is fine.
    off = {"thermostats_apart": False}
    assert them.put(url, json=off, headers=csrf(them)).status_code == 403
    assert them.put(pages, json=off, headers=csrf(them)).status_code == 403
    same = {"thermostats_apart": True, "room_order": ["Lab"]}
    assert them.put(url, json=same, headers=csrf(them)).status_code == 200
    r = client.put(pages, json=off, headers=csrf(client))
    assert r.json() == {"thermostats_apart": False, "doors_apart": False}
    assert them.get(url).json()["thermostats_apart"] is False


def test_ui_admin_sets_it_for_everyone(open_page, db, owner, make_user, make_device):
    _home(db, owner, make_device)
    page = open_page()
    _ui.ui_login(page, owner)
    section = _ui.go_settings(page, "admin")
    section.get_by_test_id("pages-thermostats-apart").check()
    expect(page.get_by_test_id("status")).to_contain_text(
        "Everyone now sees them only on the Thermostats page"
    )
    member = make_user(owner.home_id, role="member")
    other = open_page()
    _ui.ui_login(other, member)
    expect(_ui.card(other, "Lamp")).to_be_visible()
    expect(_ui.card(other, "Hallway")).to_have_count(0)
    other.get_by_test_id("layout-open").click()
    expect(other.get_by_test_id("layout-thermostats-apart")).to_have_count(0)
    other.get_by_test_id("layout-cancel").click()
    other.get_by_test_id("nav-thermostats").click()
    expect(_ui.card(other, "Hallway")).to_be_visible()


def test_ui_thermostats_page(open_page, db, owner, make_device):
    _home(db, owner, make_device)
    page = open_page()
    _ui.ui_login(page, owner)
    link = page.get_by_test_id("nav-thermostats")
    expect(link).to_be_visible()
    expect(_ui.card(page, "Hallway")).to_be_visible()  # still on Devices
    link.click()
    expect(page.get_by_test_id("thermostats-page")).to_be_visible()
    expect(_ui.card(page, "Hallway")).to_be_visible()
    expect(_ui.card(page, "Lamp")).to_have_count(0)
    expect(link).to_have_class("nav-link active")
    expect(page.get_by_test_id("nav-devices")).not_to_have_class("nav-link active")

    page.get_by_test_id("nav-devices").click()
    expect(_ui.card(page, "Lamp")).to_be_visible()
    page.get_by_test_id("layout-open").click()
    page.get_by_test_id("layout-thermostats-apart").check()
    page.get_by_test_id("layout-save").click()
    expect(_ui.card(page, "Hallway")).to_have_count(0)  # only on its own page now
    expect(_ui.card(page, "Lamp")).to_be_visible()
    page.reload()
    expect(page.get_by_test_id("app-shell")).to_be_visible()
    expect(_ui.card(page, "Lamp")).to_be_visible()
    expect(_ui.card(page, "Hallway")).to_have_count(0)
    link.click()
    expect(_ui.card(page, "Hallway")).to_be_visible()
    page.get_by_test_id("nav-settings").click()
    expect(link).not_to_have_class("nav-link active")


def test_ui_no_link_without_thermostats(open_page, db, owner, make_device):
    make_device(owner.home_id, name="Lamp")
    page = open_page()
    _ui.ui_login(page, owner)
    expect(_ui.card(page, "Lamp")).to_be_visible()
    expect(page.get_by_test_id("nav-thermostats")).to_be_hidden()
    assert db.query(Device).count() == 1


def test_ui_water_heaters_on_the_thermostats_page(open_page, db, owner, make_device):
    make_device(owner.home_id, name="Lamp")
    make_device(owner.home_id, device_type="water_heater", name="Basement heater")
    page = open_page()
    _ui.ui_login(page, owner)
    link = page.get_by_test_id("nav-thermostats")
    expect(link).to_be_visible()  # a water heater alone shows the link
    link.click()
    expect(_ui.card(page, "Basement heater")).to_be_visible()
    expect(_ui.card(page, "Lamp")).to_have_count(0)
    page.get_by_test_id("nav-devices").click()
    page.get_by_test_id("layout-open").click()
    page.get_by_test_id("layout-thermostats-apart").check()
    page.get_by_test_id("layout-save").click()
    expect(_ui.card(page, "Basement heater")).to_have_count(0)
    expect(_ui.card(page, "Lamp")).to_be_visible()


def test_ui_water_heaters_in_the_thermostats_room(open_page, db, owner, make_device):
    heater = make_device(
        owner.home_id, device_type="water_heater", name="Basement heater"
    )
    db.get(Device, heater).room = "Basement"
    make_device(owner.home_id, device_type="thermostat", name="Hallway")
    db.commit()
    page = open_page()
    _ui.ui_login(page, owner)
    room = page.locator('[data-testid="room"][data-room="Thermostats"]')
    expect(
        room.get_by_test_id("device-card").filter(has_text="Basement heater")
    ).to_be_visible()
    expect(
        room.get_by_test_id("device-card").filter(has_text="Hallway")
    ).to_be_visible()
    expect(page.locator('[data-testid="room"][data-room="Basement"]')).to_have_count(0)
