"""Schedules and Scenes in the browser: the stacked tab after Thermostats,
making and running a scene, a sunset schedule waiting for the home's
location, the admin settings, and guests allowed to run scenes."""

import json
import time

from playwright.sync_api import expect

from app.models import Device
from tests import test_ui as _ui


def test_ui_scene_schedule_and_settings(open_page, db, owner, make_device):
    lamp = make_device(owner.home_id, name="Porch light")
    page = open_page()
    _ui.ui_login(page, owner)
    tab = page.get_by_test_id("nav-schedules")
    expect(tab).to_be_visible()
    assert tab.locator("span").all_text_contents() == ["Schedules", "& Scenes"]
    order = page.locator("nav .nav-link").evaluate_all(
        "links => links.map(l => l.dataset.testid)"
    )
    assert (
        order.index("nav-thermostats")
        < order.index("nav-schedules")
        < order.index("nav-cameras")
    )
    tab.click()
    expect(page.get_by_test_id("scenes-empty")).to_be_visible()
    # A scene: the porch light at 30%.
    page.get_by_test_id("scene-new").click()
    editor = page.get_by_test_id("scene-editor")
    editor.get_by_test_id("scene-name").fill("Evening")
    editor.get_by_test_id("step-command").select_option("set_brightness")
    editor.get_by_test_id("step-value").fill("30")
    editor.get_by_test_id("scene-editor-save").click()
    expect(page.get_by_test_id("status")).to_contain_text("Evening saved")
    card = page.get_by_test_id("scene-card")
    expect(card).to_contain_text("1 step")
    card.get_by_test_id("scene-run").click()
    expect(page.get_by_test_id("status")).to_contain_text("Evening ran (1 done)")
    db.expire_all()
    assert json.loads(db.get(Device, lamp).state)["brightness"] == 30
    # A schedule: weekdays, 15 minutes before sunset, running the scene.
    page.get_by_test_id("schedule-new").click()
    editor = page.get_by_test_id("schedule-editor")
    editor.get_by_test_id("schedule-name").fill("Porch at dusk")
    editor.get_by_test_id("schedule-kind").select_option("sunset")
    editor.get_by_test_id("schedule-offset").fill("15")
    editor.get_by_test_id("schedule-offset-side").select_option("before")
    editor.get_by_test_id("schedule-day-5").uncheck()
    editor.get_by_test_id("schedule-day-6").uncheck()
    expect(editor.get_by_test_id("schedule-sun-note")).to_be_visible()
    editor.get_by_test_id("schedule-scene").select_option(label="Evening")
    editor.get_by_test_id("schedule-editor-save").click()
    row = page.get_by_test_id("schedule-row")
    expect(row.get_by_test_id("schedule-when")).to_have_text(
        "Weekdays, 15 min before sunset"
    )
    expect(row.get_by_test_id("schedule-next")).to_contain_text("location")
    # Admin > Schedules and Scenes: time zone and location.
    panel = _ui.go_settings(page, "admin").get_by_test_id("schedule-settings")
    panel.get_by_test_id("schedule-zone").select_option("America/New_York")
    panel.get_by_test_id("schedule-location").fill("40.7128, -74.0060")
    panel.get_by_test_id("schedule-settings-save").click()
    expect(page.get_by_test_id("status")).to_contain_text("Schedule settings saved")
    expect(page.get_by_test_id("schedule-sun-today")).to_contain_text("sunset")
    panel = page.get_by_test_id("schedule-settings")
    panel.get_by_test_id("schedule-location").fill("north")
    panel.get_by_test_id("schedule-settings-save").click()
    expect(page.get_by_test_id("schedule-settings-note")).to_contain_text("latitude")
    page.get_by_test_id("nav-schedules").click()
    expect(page.get_by_test_id("schedule-next")).to_contain_text("Next:")


def test_ui_phone_width_keeps_the_tab_legible(open_page, owner):
    page = open_page()
    page.set_viewport_size({"width": 390, "height": 800})
    _ui.ui_login(page, owner)
    tab = page.get_by_test_id("nav-schedules")
    expect(tab).to_be_visible()
    box = tab.bounding_box()
    assert box["width"] < 110  # stacked: two short lines, not one long one
    size = tab.evaluate("t => parseFloat(getComputedStyle(t).fontSize)")
    assert size >= 12


def test_ui_guests_see_scenes_only_when_allowed(
    open_page, client, new_client, db, owner, make_user, login, csrf, make_device
):
    lamp = make_device(owner.home_id)
    guest = make_user(owner.home_id, role="guest")
    assert login(client, owner).status_code == 200
    client.post(
        f"/api/v1/homes/{owner.home_id}/automation/scenes",
        json={
            "name": "Lamp on",
            "steps": [{"kind": "device", "id": lamp, "command": "turn_on"}],
        },
        headers=csrf(client),
    )
    page = open_page()
    _ui.ui_login(page, guest)
    expect(page.get_by_test_id("nav-devices")).to_be_visible()
    expect(page.get_by_test_id("nav-schedules")).to_be_hidden()
    access = {
        "light_power": False,
        "light_settings": False,
        "cameras": False,
        "water_heater": False,
        "show_blocked": False,
        "scenes": True,
        "thermostat_ids": [],
    }
    client.put(
        f"/api/v1/homes/{owner.home_id}/members/{guest.id}/guest-access",
        json=access,
        headers=csrf(client),
    )
    page.reload()
    page.get_by_test_id("nav-schedules").click()
    expect(page.get_by_test_id("scene-new")).to_have_count(0)
    page.get_by_test_id("scene-run").click()
    expect(page.get_by_test_id("status")).to_contain_text("Lamp on")
    time.sleep(0.2)
    db.expire_all()
    assert json.loads(db.get(Device, lamp).state)["on"] is True


def test_ui_location_from_the_homes_address(open_page, db, owner, monkeypatch):
    from app import geocode
    from app.models import Home

    monkeypatch.setattr(
        geocode,
        "get",
        lambda url, params: {
            "result": {
                "addressMatches": [{"coordinates": {"x": -74.006, "y": 40.7128}}]
            }
        },
    )
    db.get(Home, owner.home_id).address = "1 Main St, New York"
    db.commit()
    page = open_page()
    _ui.ui_login(page, owner)
    panel = _ui.go_settings(page, "admin").get_by_test_id("schedule-settings")
    panel.get_by_test_id("schedule-locate").click()
    expect(page.get_by_test_id("status")).to_contain_text("from the home's address")
    panel = page.get_by_test_id("schedule-settings")
    expect(panel.get_by_test_id("schedule-location")).to_have_value("40.713, -74.006")
    expect(panel.get_by_test_id("schedule-location-source")).to_contain_text("follows")
