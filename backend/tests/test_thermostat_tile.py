"""Thermostat tile: the sensors' average in the dial, the set points the
current mode uses under the mode, only values the thermostat reports, and an
Info window without what the tile already shows. Written by the reviewer. Do
not edit, skip, mark or delete these tests. If one looks wrong, stop and
report the test name and its full failure output instead of changing it."""

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


def info_text(page, tile):
    tile.get_by_test_id("thermo-info-open").click()
    panel = page.get_by_test_id("thermo-panel")
    expect(panel.locator("h2")).to_have_text("Hallway info")
    text = panel.inner_text()
    panel.get_by_test_id("thermo-close").click()
    return text


def setup(open_page, db, owner, make_device):
    hall = make_device(owner.home_id, device_type="thermostat", name="Hallway")
    apply_recommended(db, owner.home_id, None, None)
    page = open_page()
    ui_login(page, owner)
    return page, hall


def test_ui_tile_layout(open_page, db, owner, make_device):
    page, hall = setup(open_page, db, owner, make_device)
    tile = show(page, db, hall, report(cool_setpoint=75.0))
    expect(tile.get_by_test_id("thermo-temp")).to_have_text("67.5 °F")
    expect(tile.get_by_test_id("thermo-temp-label")).to_have_text("average")
    expect(tile.get_by_test_id("target-temp")).to_have_count(0)  # no target dial
    # The set points sit under the mode.
    order = tile.evaluate(
        """t => ['thermo-temp', 'thermo-mode', 'thermo-heat', 'temp-limits']
        .map(id => [...t.querySelectorAll('[data-testid]')]
        .findIndex(n => n.dataset.testid === id))"""
    )
    assert order == sorted(order) and -1 not in order, order
    text = info_text(page, tile)
    for shown_on_tile in ("Mode", "Heat to", "Cool to", "Humidity", "Fan", "Inside"):
        assert shown_on_tile not in text, shown_on_tile
    assert "V1.2.136" in text and "984 h" in text
    assert "hold" not in text  # the hold button is on the tile


def test_ui_set_points_follow_the_mode(open_page, db, owner, make_device):
    page, hall = setup(open_page, db, owner, make_device)
    tile = show(page, db, hall, report(cool_setpoint=75.0))  # Heat
    expect(tile.get_by_test_id("thermo-heat-value")).to_have_text("Heat to 68 °F")
    expect(tile.get_by_test_id("thermo-cool")).to_have_count(0)

    tile = show(page, db, hall, report(mode="auto", cool_setpoint=75.0))
    expect(tile.get_by_test_id("thermo-heat-value")).to_have_text("Heat to 68 °F")
    expect(tile.get_by_test_id("thermo-cool-value")).to_have_text("Cool to 75 °F")

    tile = show(page, db, hall, report(mode="cool", cool_setpoint=75.0))
    expect(tile.get_by_test_id("thermo-cool-value")).to_have_text("Cool to 75 °F")
    expect(tile.get_by_test_id("thermo-heat")).to_have_count(0)

    for mode in ("off", "eco"):
        tile = show(page, db, hall, report(mode=mode, status="off"))
        expect(tile.get_by_test_id("thermo-heat")).to_have_count(0)
        expect(tile.get_by_test_id("thermo-cool")).to_have_count(0)
        expect(tile.get_by_test_id("temp-limits")).to_have_count(0)
        expect(tile.get_by_test_id("thermo-temp")).to_have_text("67.5 °F")


def test_ui_set_point_buttons_send_commands(open_page, db, owner, make_device):
    page, hall = setup(open_page, db, owner, make_device)
    show(page, db, hall, report(mode="auto", cool_setpoint=75.0))

    def click(testid):
        with page.expect_request(
            lambda r: r.method == "POST" and r.url.endswith("/command")
        ) as request:
            card(page, "Hallway").get_by_test_id(testid).click()
        expect(page.get_by_test_id("status")).to_have_attribute("data-kind", "success")
        return request.value.post_data_json

    assert click("thermo-cool-up") == {
        "command": "set_cool_temperature",
        "payload": {"temperature": 76},
    }
    assert click("thermo-heat-down") == {
        "command": "set_temperature",
        "payload": {"temperature": 67},
    }
    db.expire_all()
    state = json.loads(db.get(Device, hall).state)
    assert (state["heat_setpoint"], state["cool_setpoint"]) == (67, 76)


def test_ui_hides_values_not_reported(open_page, db, owner, make_device):
    page, hall = setup(open_page, db, owner, make_device)
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
    expect(tile.get_by_test_id("thermo-humidity")).to_have_count(0)
    expect(tile.get_by_test_id("thermo-fan")).to_have_count(0)
    expect(tile.get_by_test_id("thermo-sensors")).to_have_count(0)
    text = info_text(page, tile)
    assert "reports nothing more" in text and "not reported" not in text
