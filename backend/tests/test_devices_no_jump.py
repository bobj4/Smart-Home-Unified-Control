"""The Devices page keeps its place when it updates by itself: rooms side
by side keep their heights through a redraw, and an unchanged refresh
leaves the page as it is."""

import json

from playwright.sync_api import expect

from app.models import Device
from tests import test_ui as _ui


def test_live_updates_keep_the_scroll(open_page, db, owner, make_device):
    lamps = []
    for i in range(24):
        lamp = make_device(owner.home_id, name=f"Lamp {i}")
        db.get(Device, lamp).room = f"Room {i % 8}"
        lamps.append(lamp)
    db.commit()
    page = open_page()
    page.set_viewport_size({"width": 390, "height": 700})
    _ui.ui_login(page, owner)
    _ui.card(page, "Lamp 23").wait_for()
    page.evaluate("window.smartHomeApp.refreshMs = 300")
    page.mouse.wheel(0, 900)
    page.wait_for_timeout(500)
    before = page.evaluate("window.scrollY")
    assert before > 300
    card = _ui.card(page, "Lamp 23").element_handle()
    page.wait_for_timeout(6500)  # the 5 s refresh, then several at 0.3 s
    assert page.evaluate("window.scrollY") == before
    assert card.evaluate("c => c.isConnected")  # the page was left as it was
    # A change redraws the page: still in the same place.
    for lamp in lamps[:4]:
        db.get(Device, lamp).state = json.dumps({"on": True})
    db.commit()
    expect(_ui.card(page, "Lamp 0").get_by_test_id("power-toggle")).to_have_attribute(
        "aria-pressed", "true", timeout=10000
    )
    page.wait_for_timeout(600)
    assert abs(page.evaluate("window.scrollY") - before) < 2
