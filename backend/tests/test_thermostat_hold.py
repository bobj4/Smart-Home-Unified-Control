"""Thermostat hold button: follow the schedule, temporary hold, permanent
hold. Written by the reviewer. Do not edit, skip, mark or delete these tests.
If one looks wrong, stop and report the test name and its full failure output
instead of changing it. Cync is faked (see test_thermostat.py)."""

import json

from playwright.sync_api import expect

from app.integrations import cync_thermostat as t
from app.models import Device
from app.safety import apply_recommended
from tests import test_cync as _cync
from tests import test_thermostat as _thermostat
from tests import test_ui as _ui

fake, secrets_key = _thermostat.fake, _thermostat.secrets_key
thermostat = _thermostat.thermostat
card, ui_login = _ui.card, _ui.ui_login
CLOUD_ID = _thermostat.CLOUD_ID


def state(db, device_id):
    db.expire_all()
    return json.loads(db.get(Device, device_id).state)


def test_hold_commands(client, db, owner, csrf, thermostat):
    def send(**payload):
        return _cync.command(
            client, csrf, owner.home_id, thermostat.id, "set_hold", **payload
        )

    assert state(db, thermostat.id)["hold"] == "permanent"
    for hold, code in (("schedule", 0), ("temporary", 2), ("permanent", 1)):
        assert send(hold=hold).status_code == 200, hold
        assert thermostat.writes[-1] == (CLOUD_ID, [(t.HOLD_SET, code)])
        assert state(db, thermostat.id)["hold"] == hold
    assert send(hold="forever").status_code == 422
    assert send(hold="schedule", extra=1).status_code == 422


def test_unconfirmed_hold_changes_nothing(client, db, owner, csrf, thermostat):
    thermostat.answer[t.RUN_MODE] = 1  # the thermostat stays on permanent hold
    r = _cync.command(
        client, csrf, owner.home_id, thermostat.id, "set_hold", hold="temporary"
    )
    assert r.status_code == 502
    assert state(db, thermostat.id)["hold"] == "permanent"


def test_demo_thermostat_has_no_hold(client, db, owner, make_device, login, csrf):
    hall = make_device(owner.home_id, device_type="thermostat", name="Hall")
    apply_recommended(db, owner.home_id, None, None)
    assert login(client, owner).status_code == 200
    r = _cync.command(client, csrf, owner.home_id, hall, "set_hold", hold="schedule")
    assert r.status_code == 422


def test_ui_hold_button_cycles(open_page, db, owner, make_device):
    hall = make_device(owner.home_id, device_type="thermostat", name="Hallway")
    apply_recommended(db, owner.home_id, None, None)
    report = t.thermostat_state(t.parse_probe_reply(_thermostat.FULL_REPLY))
    db.get(Device, hall).state = json.dumps(report)  # permanent hold
    db.commit()
    page = open_page()
    ui_login(page, owner)

    def press(expected_now, expected_next):
        button = card(page, "Hallway").get_by_test_id("thermo-hold")
        expect(button).to_have_text(expected_now)
        with page.expect_request(
            lambda r: r.method == "POST" and r.url.endswith("/command")
        ) as request:
            button.click()
        assert request.value.post_data_json == {
            "command": "set_hold",
            "payload": {"hold": expected_next},
        }
        expect(page.get_by_test_id("status")).to_have_attribute("data-kind", "success")

    press("Permanent hold", "schedule")
    press("Following schedule", "temporary")
    press("Temporary hold", "permanent")
    expect(card(page, "Hallway").get_by_test_id("thermo-hold")).to_have_text(
        "Permanent hold"
    )
