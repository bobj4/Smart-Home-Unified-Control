"""Water heater tile: status, power, mode, home/away, schedule and usage.
Written by the reviewer. Do not edit, skip, mark or delete these tests. If one
looks wrong, stop and report the test name and its full failure output
instead of changing it. Rheem is faked (FakeEconet in test_rheem.py).
"""

import json

from playwright.sync_api import expect

from app.models import Device
from tests import test_rheem as _rheem
from tests import test_ui as _ui

econet, secrets_key = _rheem.econet, _rheem.secrets_key
card, ui_login = _ui.card, _ui.ui_login


def command(client, csrf, home_id, device_id, name, **payload):
    return client.post(
        f"/api/v1/homes/{home_id}/devices/{device_id}/command",
        json={"command": name, "payload": payload},
        headers=csrf(client),
    )


def state(db, device_id):
    db.expire_all()
    return json.loads(db.get(Device, device_id).state)


def test_rheem_heater_controls(client, db, owner, login, csrf, econet, secrets_key):
    econet.heaters = [
        _rheem.heater(
            modes=("energy_saving", "high_demand", "vacation", "off"),
            away=False,
            schedule="Schedule overridden",
            energy_today=1.25,
            energy_unit="KWH",
            water_today=31.0,
        )
    ]
    _rheem.ready(client, csrf, login, owner)
    assert _rheem.sync(client, csrf, owner.home_id).status_code == 200
    (device,) = _rheem.rheem_devices(db, owner.home_id)
    home, did = owner.home_id, device.id
    s = state(db, did)
    assert (s["status"], s["energy_today"], s["water_today"]) == ("heating", 1.25, 31.0)

    assert command(client, csrf, home, did, "turn_off").status_code == 200
    assert (state(db, did)["status"], state(db, did)["mode"]) == ("off", "off")
    assert command(client, csrf, home, did, "turn_on").status_code == 200
    assert state(db, did)["mode"] == "energy_saving"  # back to the mode it had
    assert (
        command(client, csrf, home, did, "set_mode", mode="high_demand").status_code
        == 200
    )
    assert command(client, csrf, home, did, "set_mode", mode="turbo").status_code == 422
    assert command(client, csrf, home, did, "set_away", away=True).status_code == 200
    assert command(client, csrf, home, did, "set_away", away="yes").status_code == 422
    assert command(client, csrf, home, did, "resume_schedule").status_code == 200
    s = state(db, did)
    assert (s["schedule"], s["away"]) == ("Following Schedule", False)
    serial = _rheem.SERIAL
    assert econet.commands == [
        ("mode", serial, "off"),
        ("mode", serial, "energy_saving"),
        ("mode", serial, "high_demand"),
        ("away", serial, True),
        ("resume", serial),
    ]


def test_demo_heater_without_features(client, db, owner, make_device, login, csrf):
    tank = make_device(owner.home_id, device_type="water_heater", name="Tank")
    assert login(client, owner).status_code == 200
    assert command(client, csrf, owner.home_id, tank, "turn_off").status_code == 200
    assert state(db, tank)["status"] == "off"
    assert (
        command(client, csrf, owner.home_id, tank, "set_away", away=True).status_code
        == 422
    )
    assert (
        command(client, csrf, owner.home_id, tank, "resume_schedule").status_code == 422
    )


def test_ui_heater_tile(open_page, db, owner, make_device):
    tank = make_device(owner.home_id, device_type="water_heater", name="Tank")
    d = db.get(Device, tank)
    d.state = json.dumps(
        {
            "target_temperature": 120,
            "unit": "F",
            "status": "idle",
            "enabled": True,
            "mode": "energy_saving",
            "modes": ["energy_saving", "high_demand", "off"],
            "away": False,
            "schedule": "Schedule overridden",
            "energy_today": 0.8,
            "energy_unit": "KWH",
            "water_today": 12,
        }
    )
    db.commit()
    page = open_page()
    ui_login(page, owner)
    tile = card(page, "Tank")
    expect(tile.get_by_test_id("heater-status")).to_have_text("Idle")
    order = tile.evaluate(
        """t => ['heater-status', 'heater-schedule', 'heater-usage',
        'heater-settings-open', 'heater-power'].map(id =>
        [...t.querySelectorAll('[data-testid]')].findIndex(n => n.dataset.testid === id))"""
    )
    assert (
        order == sorted(order) and -1 not in order
    )  # status, schedule, usage, settings, power
    expect(tile.get_by_test_id("heater-usage")).to_contain_text("0.80 kWh today")
    tile.get_by_test_id("heater-power").click()
    expect(card(page, "Tank").get_by_test_id("heater-status")).to_have_text("Off")
    card(page, "Tank").get_by_test_id("heater-power").click()
    expect(card(page, "Tank").get_by_test_id("heater-status")).not_to_have_text("Off")
    card(page, "Tank").get_by_test_id("heater-away").click()
    expect(card(page, "Tank").get_by_test_id("heater-away")).to_have_text("Away")
    card(page, "Tank").get_by_test_id("heater-settings-open").click()
    panel = page.get_by_test_id("heater-panel")
    panel.get_by_test_id("heater-mode").select_option("high_demand")
    expect(page.get_by_test_id("status")).to_have_attribute("data-kind", "success")
    assert json.loads(db.get(Device, tank).state)["mode"] == "high_demand" or (
        db.expire_all()
        or json.loads(db.get(Device, tank).state)["mode"] == "high_demand"
    )
