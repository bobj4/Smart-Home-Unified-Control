"""Rooms on the Devices page fold shut from their heading, remembered per
person; phones keep a layout (order and folded rooms) of their own."""

from playwright.sync_api import expect

from app.models import Device
from tests import test_ui as _ui


def layout_url(home_id):
    return f"/api/v1/homes/{home_id}/layout"


def test_collapsed_and_screens_api(client, owner, login, csrf):
    assert login(client, owner).status_code == 200
    url = layout_url(owner.home_id)
    r = client.put(url, json={"room_order": ["Kitchen", "Lab"]}, headers=csrf(client))
    assert r.json()["room_order"] == ["Kitchen", "Lab"]
    # A phone starts from the wide-screen order until it has its own.
    assert client.get(f"{url}?screen=phone").json()["room_order"] == ["Kitchen", "Lab"]
    r = client.put(
        url, json={"collapsed": ["Lab", "Lab"], "screen": "phone"}, headers=csrf(client)
    )
    assert r.json()["collapsed"] == ["Lab"]
    assert r.json()["room_order"] == ["Kitchen", "Lab"]  # kept from wide
    r = client.put(
        url,
        json={"room_order": ["Lab", "Kitchen"], "screen": "phone"},
        headers=csrf(client),
    )
    assert r.json() == {
        "room_order": ["Lab", "Kitchen"],
        "collapsed": ["Lab"],
        "screen": "phone",
        "thermostats_room": "Thermostats",
    }
    wide = client.get(url).json()
    assert wide["room_order"] == ["Kitchen", "Lab"] and wide["collapsed"] == []
    for bad in (
        {},
        {"collapsed": ["x" * 51]},
        {"collapsed": "Lab"},
        {"room_order": [], "screen": "tablet"},
    ):
        assert client.put(url, json=bad, headers=csrf(client)).status_code == 422
    assert client.get(f"{url}?screen=tv").status_code == 422


def _two_rooms(db, owner, make_device):
    for name, room in (("Lamp", "Kitchen"), ("Desk light", "Office")):
        device_id = make_device(owner.home_id, name=name)
        db.get(Device, device_id).room = room
    db.commit()


def test_ui_fold_a_room_and_keep_it(open_page, db, owner, make_device):
    _two_rooms(db, owner, make_device)
    page = open_page()
    _ui.ui_login(page, owner)
    kitchen = page.locator('[data-testid="room"][data-room="Kitchen"]')
    toggle = kitchen.get_by_test_id("room-toggle")
    expect(toggle).to_have_attribute("aria-expanded", "true")
    expect(_ui.card(page, "Lamp")).to_be_visible()
    toggle.click()
    expect(toggle).to_have_attribute("aria-expanded", "false")
    expect(_ui.card(page, "Lamp")).to_be_hidden()
    expect(_ui.card(page, "Desk light")).to_be_visible()
    expect(kitchen.locator(".room-count")).to_have_text("1")
    page.wait_for_timeout(300)  # the save
    page.reload()
    expect(page.get_by_test_id("app-shell")).to_be_visible()
    expect(_ui.card(page, "Lamp")).to_be_hidden()
    page.locator('[data-testid="room"][data-room="Kitchen"]').get_by_test_id(
        "room-toggle"
    ).click()
    expect(_ui.card(page, "Lamp")).to_be_visible()


def test_ui_phone_has_its_own_layout(open_page, db, owner, make_device):
    _two_rooms(db, owner, make_device)
    page = open_page()
    _ui.ui_login(page, owner)
    page.locator('[data-testid="room"][data-room="Office"]').get_by_test_id(
        "room-toggle"
    ).click()
    expect(_ui.card(page, "Desk light")).to_be_hidden()
    page.wait_for_timeout(300)
    page.set_viewport_size({"width": 390, "height": 800})  # now a phone
    expect(_ui.card(page, "Desk light")).to_be_visible()
    page.set_viewport_size({"width": 1200, "height": 800})
    expect(_ui.card(page, "Desk light")).to_be_hidden()
