"""Lights (brightness, white temperature, colour) and plugs: API and browser.

Written by the reviewer (lights phase). Do not edit, skip, mark or delete
these tests. If one looks wrong, stop and report the test name and its full
failure output instead of changing it.
"""

import json
import re

from playwright.sync_api import expect

from app.models import Device
from tests import test_ui as _ui

card, ui_login = _ui.card, _ui.ui_login


def command(client, csrf, home_id, device_id, name, **payload):
    return client.post(
        f"/api/v1/homes/{home_id}/devices/{device_id}/command",
        json={"command": name, "payload": payload},
        headers=csrf(client),
    )


def stored(db, device_id):
    db.expire_all()
    return json.loads(db.get(Device, device_id).state)


def test_light_commands(client, db, owner, make_device, login, csrf):
    lamp = make_device(owner.home_id, name="Lamp")
    assert login(client, owner).status_code == 200
    home = owner.home_id

    r = command(client, csrf, home, lamp, "turn_on")
    assert r.status_code == 200
    assert r.json()["state"] == {
        "on": True,
        "brightness": 100,
        "color_mode": "temp",
        "color_temp": 2700,
        "color": "#ffffff",
    }
    assert (
        command(client, csrf, home, lamp, "set_brightness", brightness=40).json()[
            "state"
        ]["brightness"]
        == 40
    )
    command(client, csrf, home, lamp, "turn_off")
    state = command(client, csrf, home, lamp, "set_color_temp", kelvin=4000).json()[
        "state"
    ]
    assert (state["on"], state["color_mode"], state["color_temp"]) == (
        True,
        "temp",
        4000,
    )
    state = command(client, csrf, home, lamp, "set_color", color="#FF8800").json()[
        "state"
    ]
    assert (state["on"], state["color_mode"], state["color"]) == (
        True,
        "rgb",
        "#ff8800",
    )
    assert state["color_temp"] == 4000  # kept for switching back to white
    assert stored(db, lamp) == state


def test_light_commands_are_validated(client, db, owner, make_device, login, csrf):
    lamp = make_device(owner.home_id, name="Lamp")
    assert login(client, owner).status_code == 200
    home = owner.home_id
    command(client, csrf, home, lamp, "turn_on")
    before = stored(db, lamp)
    bad = [
        ("set_brightness", {"brightness": 101}),
        ("set_brightness", {"brightness": 50.5}),
        ("set_brightness", {"brightness": "50"}),
        ("set_color_temp", {"kelvin": 1500}),
        ("set_color_temp", {"kelvin": 7000}),
        ("set_color_temp", {"kelvin": True}),
        ("set_color", {"color": "orange"}),
        ("set_color", {"color": "#ff88"}),
        ("set_color", {"color": "#gg0000"}),
        ("set_color", {"color": "#ff8800", "kelvin": 3000}),
        ("set_color", {}),
        ("volume_up", {}),
    ]
    for name, payload in bad:
        assert command(client, csrf, home, lamp, name, **payload).status_code == 422, (
            name,
            payload,
        )
    assert stored(db, lamp) == before


def test_plug_is_on_off_only(client, db, owner, login, csrf):
    assert login(client, owner).status_code == 200
    home = owner.home_id
    r = client.post(
        f"/api/v1/homes/{home}/devices",
        json={
            "name": "Coffee maker",
            "type": "plug",
            "integration": "simulated",
            "room": "Kitchen",
        },
        headers=csrf(client),
    )
    assert r.status_code == 201, r.text
    plug = r.json()["id"]
    assert command(client, csrf, home, plug, "turn_on").json()["state"] == {"on": True}
    assert command(client, csrf, home, plug, "turn_off").json()["state"] == {
        "on": False
    }
    for name, payload in (
        ("set_brightness", {"brightness": 50}),
        ("set_color", {"color": "#ff0000"}),
    ):
        assert command(client, csrf, home, plug, name, **payload).status_code == 422


# ------------------------------------------------------------ browser


def test_ui_light_settings_window(open_page, db, owner, make_device):
    lamp = make_device(owner.home_id, name="Reading lamp")
    page = open_page()
    ui_login(page, owner)
    c = card(page, "Reading lamp")
    expect(c.get_by_test_id("light-brightness")).to_have_count(
        0
    )  # not on the card itself
    c.get_by_test_id("power-toggle").click()
    expect(card(page, "Reading lamp").get_by_test_id("power-toggle")).to_have_attribute(
        "aria-pressed", "true"
    )

    card(page, "Reading lamp").get_by_test_id("light-settings-open").click()
    panel = page.get_by_test_id("light-panel")
    expect(panel).to_be_visible()
    expect(panel).to_contain_text("Reading lamp")

    panel.get_by_test_id("light-brightness").fill("35")
    expect(panel).to_contain_text("Brightness 35%")
    assert stored(db, lamp)["brightness"] == 35
    panel.get_by_test_id("light-temp").fill("5000")
    expect(panel).to_contain_text("5000 K")
    assert stored(db, lamp)["color_temp"] == 5000
    panel.get_by_test_id("light-color").fill("#3366ff")
    expect(page.get_by_test_id("status")).to_have_attribute("data-kind", "success")
    expect(panel.get_by_test_id("light-color")).to_have_value("#3366ff")
    state = stored(db, lamp)
    assert (state["color_mode"], state["color"]) == ("rgb", "#3366ff")
    swatch = panel.get_by_test_id("light-swatch").evaluate(
        "e => e.style.getPropertyValue('--light')"
    )
    assert swatch.lower() == "#3366ff"

    page.keyboard.press("Escape")
    expect(page.get_by_test_id("light-panel")).to_have_count(0)
    expect(card(page, "Reading lamp")).to_have_attribute(
        "style", re.compile("--light: #3366ff", re.I)
    )  # the card shows the light's colour


def test_ui_plug_toggle(open_page, db, owner, make_device):
    plug = make_device(owner.home_id, device_type="plug", name="Fan plug")
    page = open_page()
    ui_login(page, owner)
    c = card(page, "Fan plug")
    expect(c).to_contain_text("Plug")
    expect(c.get_by_test_id("light-settings-open")).to_have_count(0)
    c.get_by_test_id("power-toggle").click()
    expect(card(page, "Fan plug").get_by_test_id("power-toggle")).to_have_attribute(
        "aria-pressed", "true"
    )
    assert stored(db, plug) == {"on": True}


def test_ui_light_controls_disabled_when_offline(open_page, db, owner, make_device):
    lamp = make_device(owner.home_id, name="Porch lamp")
    db.get(Device, lamp).online = False
    db.commit()
    page = open_page()
    ui_login(page, owner)
    expect(
        card(page, "Porch lamp").get_by_test_id("light-settings-open")
    ).to_be_disabled()
