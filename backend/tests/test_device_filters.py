"""Filters on the Devices page (search, type, on only, remembered) and the
admin search in Settings > Devices (name, room, brand, IP or MAC)."""

import json

from playwright.sync_api import expect

from app.models import Device
from tests import test_ui as _ui


def _devices(db, owner, make_device):
    made = {}
    for name, kind, room, on in (
        ("Lamp", "light", "Kitchen", True),
        ("Desk light", "light", "Office", False),
        ("Coffee plug", "plug", "Kitchen", False),
    ):
        made[name] = make_device(owner.home_id, device_type=kind, name=name)
        device = db.get(Device, made[name])
        device.room = room
        device.state = json.dumps({"on": on})
    db.commit()
    return made


def test_ui_filters(open_page, db, owner, make_device):
    _devices(db, owner, make_device)
    page = open_page()
    _ui.ui_login(page, owner)
    filters = page.get_by_test_id("device-filters")
    filters.get_by_test_id("filter-search").fill("kitchen")
    expect(_ui.card(page, "Lamp")).to_be_visible()
    expect(_ui.card(page, "Coffee plug")).to_be_visible()
    expect(_ui.card(page, "Desk light")).to_have_count(0)
    filters.get_by_test_id("filter-type").select_option("plug")
    expect(_ui.card(page, "Lamp")).to_have_count(0)
    expect(_ui.card(page, "Coffee plug")).to_be_visible()
    filters.get_by_test_id("filter-on").check()
    expect(page.get_by_test_id("filter-empty")).to_be_visible()
    # Typing is not interrupted by the page refreshing.
    search = filters.get_by_test_id("filter-search")
    search.click()
    page.wait_for_timeout(5500)
    expect(search).to_be_focused()
    # Remembered after a reload.
    page.wait_for_timeout(800)  # the save
    page.reload()
    expect(page.get_by_test_id("app-shell")).to_be_visible()
    expect(page.get_by_test_id("filter-type")).to_have_value("plug")
    expect(page.get_by_test_id("filter-empty")).to_be_visible()
    page.get_by_test_id("filter-clear").click()
    for name in ("Lamp", "Desk light", "Coffee plug"):
        expect(_ui.card(page, name)).to_be_visible()


def test_ui_admin_device_search(open_page, db, owner, make_device):
    made = _devices(db, owner, make_device)
    device = db.get(Device, made["Desk light"])
    device.capabilities = json.dumps({"ip": "192.168.1.77", "mac": "AA:BB:CC:00:11:22"})
    db.commit()
    page = open_page()
    _ui.ui_login(page, owner)
    _ui.go_settings(page, "devices")
    rows = page.get_by_test_id("device-row")
    search = page.get_by_test_id("device-search")
    for text, visible in (
        ("192.168.1.77", ["Desk light"]),
        ("aa:bb", ["Desk light"]),
        ("kitchen", ["Lamp", "Coffee plug"]),
        ("kitchen plug", ["Coffee plug"]),
        ("nothing", []),
    ):
        search.fill(text)
        expect(rows.filter(visible=True)).to_have_count(len(visible))
        for name in visible:
            expect(
                page.locator(
                    f'[data-device-id="{made[name]}"][data-testid="device-row"]'
                )
            ).to_be_visible()
