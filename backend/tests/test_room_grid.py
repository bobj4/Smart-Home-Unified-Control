"""Rooms side by side on larger screens: the number of columns and each
room's width are set in Edit layout; phones always show one column."""

from playwright.sync_api import expect

from app.models import Device
from tests import test_ui as _ui


def test_grid_api(client, owner, login, csrf):
    assert login(client, owner).status_code == 200
    url = f"/api/v1/homes/{owner.home_id}/layout"
    assert client.get(url).json()["grid"] == {"columns": 2, "sizes": {}}
    grid = {"columns": 3, "sizes": {"Kitchen": 2}}
    r = client.put(url, json={"grid": grid}, headers=csrf(client))
    assert r.status_code == 200 and r.json()["grid"] == grid
    for bad in (
        {"columns": 5, "sizes": {}},
        {"columns": 0, "sizes": {}},
        {"columns": 2, "sizes": {"Kitchen": 9}},
        {"columns": 2, "sizes": {"x" * 51: 1}},
    ):
        assert (
            client.put(url, json={"grid": bad}, headers=csrf(client)).status_code == 422
        )


def _rooms(db, owner, make_device):
    for name, room in (
        ("Lamp", "Kitchen"),
        ("Desk light", "Office"),
        ("Nightstand", "Bedroom"),
    ):
        device_id = make_device(owner.home_id, name=name)
        db.get(Device, device_id).room = room
    db.commit()


def box(page, room):
    return page.locator(f'[data-testid="room"][data-room="{room}"]').bounding_box()


def test_ui_side_by_side_and_widths(open_page, db, owner, make_device):
    _rooms(db, owner, make_device)
    page = open_page()
    page.set_viewport_size({"width": 1300, "height": 900})
    _ui.ui_login(page, owner)
    expect(_ui.card(page, "Lamp")).to_be_visible()
    # Two columns by default: Bedroom and Kitchen side by side, Office below.
    assert abs(box(page, "Bedroom")["y"] - box(page, "Kitchen")["y"]) < 2
    assert box(page, "Office")["y"] > box(page, "Kitchen")["y"]

    page.get_by_test_id("layout-open").click()
    page.get_by_test_id("layout-columns").select_option("3")
    row = page.locator('[data-testid="layout-room"][data-room="Kitchen"]')
    row.get_by_test_id("layout-width").select_option("2")
    page.get_by_test_id("layout-save").click()
    expect(page.get_by_test_id("rooms-grid")).to_have_attribute("data-columns", "3")
    kitchen, bedroom = box(page, "Kitchen"), box(page, "Bedroom")
    assert kitchen["width"] > bedroom["width"] * 1.8  # two columns wide

    page.reload()
    expect(page.get_by_test_id("rooms-grid")).to_have_attribute("data-columns", "3")
    page.set_viewport_size({"width": 390, "height": 800})  # a phone: one column
    expect(page.get_by_test_id("rooms-grid")).to_have_attribute("data-columns", "1")
    assert (
        box(page, "Office")["y"] > box(page, "Kitchen")["y"] > box(page, "Bedroom")["y"]
    )
    page.get_by_test_id("layout-open").click()
    expect(page.get_by_test_id("layout-columns")).to_have_count(0)
