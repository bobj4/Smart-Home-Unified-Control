"""Thermostat tile: only the set points the current mode uses, and only the
values the thermostat reports. Written by the reviewer. Do not edit, skip,
mark or delete these tests. If one looks wrong, stop and report the test name
and its full failure output instead of changing it."""

import json

from playwright.sync_api import expect

from app.integrations import cync_thermostat as t
from app.models import Device
from app.safety import apply_recommended
from tests import test_thermostat as _thermostat
from tests import test_ui as _ui

card, ui_login = _ui.card, _ui.ui_login


def report(**changes):
    state = t.thermostat_state(t.parse_probe_reply(_thermostat.FULL_REPLY))
    return {**state, **changes}


def show(page, db, device_id, state):
    db.expire_all()
    db.get(Device, device_id).state = json.dumps(state)
    db.commit()
    page.reload()
    return card(page, "Hallway")


def panel_text(page, tile):
    tile.get_by_test_id("thermo-settings-open").click()
    panel = page.get_by_test_id("thermo-panel")
    text = panel.locator("dl").inner_text()
    panel.get_by_test_id("thermo-close").click()
    return text


def test_ui_tile_shows_the_active_set_points(open_page, db, owner, make_device):
    hall = make_device(owner.home_id, device_type="thermostat", name="Hallway")
    apply_recommended(db, owner.home_id, None, None)
    page = open_page()
    ui_login(page, owner)

    # Heat: only the heating set point.
    tile = show(page, db, hall, report(cool_setpoint=75.0))
    expect(tile.get_by_test_id("target-label")).to_have_text("heat to")
    expect(tile.get_by_test_id("target-temp")).to_have_text("68 °F")
    expect(tile.get_by_test_id("thermo-cool")).to_have_count(0)
    text = panel_text(page, tile)
    assert "Heat to" in text and "Cool to" not in text

    # Auto: heating on the dial and cooling below it.
    tile = show(page, db, hall, report(mode="auto", cool_setpoint=75.0))
    expect(tile.get_by_test_id("target-label")).to_have_text("heat to")
    expect(tile.get_by_test_id("thermo-cool")).to_have_text("Cool to 75 °F")
    text = panel_text(page, tile)
    assert "Heat to" in text and "Cool to" in text

    # Cool: only the cooling set point, on the dial.
    tile = show(
        page, db, hall, report(mode="cool", cool_setpoint=75.0, target_temperature=75.0)
    )
    expect(tile.get_by_test_id("target-label")).to_have_text("cool to")
    expect(tile.get_by_test_id("target-temp")).to_have_text("75 °F")
    expect(tile.get_by_test_id("thermo-cool")).to_have_count(0)
    text = panel_text(page, tile)
    assert "Cool to" in text and "Heat to" not in text

    # Off: no set point at all.
    tile = show(page, db, hall, report(mode="off", status="off"))
    expect(tile.get_by_test_id("thermo-status")).to_have_text("Off")
    expect(tile.get_by_test_id("temp-gauge")).to_have_count(0)
    text = panel_text(page, tile)
    assert "Heat to" not in text and "Cool to" not in text


def test_ui_tile_hides_values_not_reported(open_page, db, owner, make_device):
    hall = make_device(owner.home_id, device_type="thermostat", name="Hallway")
    apply_recommended(db, owner.home_id, None, None)
    page = open_page()
    ui_login(page, owner)
    bare = report(
        humidity=None,
        fan=None,
        sensors=[{"name": "Remote sensor", "temperature": None, "active": True}],
        firmware=None,
        wifi=None,
        hold=None,
        system=None,
        filter_hours=None,
    )
    tile = show(page, db, hall, bare)
    expect(tile.get_by_test_id("thermo-now")).to_have_text("Inside 67.5 °F")
    expect(tile.get_by_test_id("thermo-fan")).to_have_count(0)
    expect(tile.get_by_test_id("thermo-sensors")).to_have_count(0)
    text = panel_text(page, tile)
    for hidden in (
        "Humidity",
        "Fan",
        "Schedule",
        "System",
        "Filter",
        "Firmware",
        "Wi-Fi",
    ):
        assert hidden not in text, hidden
    assert "not reported" not in text
