"""Remote doors (garage doors) on a page of their own, like the thermostats:
the Doors link shows only while the home has a door from an integration
that is on, and each person can keep the doors only on that page."""

from playwright.sync_api import expect

from app import features
from app.models import Device
from tests import test_ui as _ui


def test_api_doors_apart(client, owner, login, csrf):
    assert login(client, owner).status_code == 200
    url = f"/api/v1/homes/{owner.home_id}/layout"
    assert client.get(url).json()["doors_apart"] is False
    r = client.put(url, json={"doors_apart": True}, headers=csrf(client))
    assert r.status_code == 200 and r.json()["doors_apart"] is True
    assert r.json()["thermostats_apart"] is False
    assert client.get(f"{url}?screen=phone").json()["doors_apart"] is False
    bad = client.put(url, json={"doors_apart": "yes"}, headers=csrf(client))
    assert bad.status_code == 422


def _home(db, owner, make_device):
    make_device(owner.home_id, name="Lamp")
    door_id = make_device(owner.home_id, device_type="garage_door", name="Garage")
    db.get(Device, door_id).integration = "ratgdo"
    db.commit()


def test_ui_doors_page(open_page, db, owner, make_device):
    _home(db, owner, make_device)
    features.set_integration(db, owner.home_id, "ratgdo", True, None, None)
    page = open_page()
    _ui.ui_login(page, owner)
    link = page.get_by_test_id("nav-doors")
    expect(link).to_be_visible()
    expect(page.get_by_test_id("nav-thermostats")).to_be_hidden()
    expect(_ui.card(page, "Garage")).to_be_visible()  # still on Devices
    link.click()
    expect(page.get_by_test_id("doors-page")).to_be_visible()
    expect(_ui.card(page, "Garage")).to_be_visible()
    expect(_ui.card(page, "Lamp")).to_have_count(0)
    expect(link).to_have_class("nav-link active")
    expect(page.get_by_test_id("nav-devices")).not_to_have_class("nav-link active")

    page.get_by_test_id("nav-devices").click()
    page.get_by_test_id("layout-open").click()
    expect(page.get_by_test_id("layout-thermostats-apart")).to_have_count(0)
    page.get_by_test_id("layout-doors-apart").check()
    page.get_by_test_id("layout-save").click()
    expect(_ui.card(page, "Garage")).to_have_count(0)  # only on its own page now
    expect(_ui.card(page, "Lamp")).to_be_visible()
    page.reload()
    expect(page.get_by_test_id("app-shell")).to_be_visible()
    expect(_ui.card(page, "Lamp")).to_be_visible()
    expect(_ui.card(page, "Garage")).to_have_count(0)
    link.click()
    expect(_ui.card(page, "Garage")).to_be_visible()


def test_ui_no_doors_link_while_the_integration_is_off(
    open_page, db, owner, make_device
):
    _home(db, owner, make_device)
    features.set_integration(db, owner.home_id, "ratgdo", False, None, None)
    page = open_page()
    _ui.ui_login(page, owner)
    expect(_ui.card(page, "Lamp")).to_be_visible()
    expect(page.get_by_test_id("nav-doors")).to_be_hidden()
