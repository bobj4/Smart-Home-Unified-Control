"""A Cync thermostat's own settings (the Settings window under Schedule):
read by name, yes/no ones changed and read back. Nothing talks to Cync."""

import json

import pytest
from playwright.sync_api import expect

from app import features, thermostat_settings
from app.integrations import cync
from app.integrations import cync_thermostat as t
from app.models import AuditEvent, Device
from tests import test_thermostat as _thermostat
from tests import test_ui as _ui

fake, secrets_key = _thermostat.fake, _thermostat.secrets_key
thermostat = _thermostat.thermostat
CLOUD_ID = _thermostat.CLOUD_ID


def test_yes_no_entries_are_one_byte():
    assert t.entry(23, True) == bytes([23, 0x00, 0x01, 0x01])
    assert t.entry(23, False) == bytes([23, 0x00, 0x01, 0x00])
    assert t.entry(9, 1) == bytes([9, 0x40, 0x04, 0, 0, 0, 1])  # ints unchanged


@pytest.fixture
def held(thermostat, monkeypatch):
    """What the thermostat holds, by setting name; it answers reads and keeps
    writes (unless told not to)."""
    stored = {
        "EarlyON_Enable": 0,
        "Temperature_Unit": False,
        "Auto_DST": True,
        "Min_Fan_Runtime": 10,
        "Temperature_Offset": "-1.0F",
        "Auto_Mode_Deadband": "3.0F",
        "Dehumidification_Enable": None,
        "Humidity_Offset": {"odd": 1},
    }
    state = {"keep": True, "writes": []}
    by_index = {i: name for name, i, _ in thermostat_settings.SETTINGS.values()}

    def read(api, loop, cloud_id, names):
        assert cloud_id == CLOUD_ID
        return {name: stored[name] for name in names if name in stored}

    def write(api, loop, cloud_id, entries, names):
        state["writes"].append(entries)
        if state["keep"]:
            for index, value in entries:
                stored[by_index[index]] = int(value)  # as 1/0
        return read(api, loop, cloud_id, names)

    monkeypatch.setattr(cync, "thermostat_settings_on_open", read)
    monkeypatch.setattr(cync, "thermostat_write_settings_on_open", write)
    thermostat_settings._cache.clear()
    return state


def url(owner, thermostat):
    return f"/api/v1/homes/{owner.home_id}/devices/{thermostat.id}/settings"


def test_read_and_change(client, db, owner, csrf, thermostat, held):
    r = client.get(url(owner, thermostat))
    assert r.status_code == 200, r.text
    body = r.json()
    settings = body["settings"]
    assert (settings["early_on"], settings["celsius"], settings["auto_dst"]) == (
        False,
        False,
        True,
    )
    assert settings["min_fan_runtime"] == 10
    assert settings["temperature_offset"] == "-1.0F"
    assert settings["humidity_offset"] is None  # not a plain value: not shown
    assert "heat_pump_changeover" in body["missing"]
    assert body["editable"] == ["early_on", "celsius", "auto_dst"]

    r = client.put(
        url(owner, thermostat), json={"early_on": True}, headers=csrf(client)
    )
    assert r.status_code == 200, r.text
    assert held["writes"] == [[(23, True)]]
    assert r.json()["settings"]["early_on"] is True
    db.expire_all()
    assert (
        db.query(AuditEvent).filter_by(event_type="thermostat_settings_saved").count()
        == 1
    )

    held["keep"] = False  # the thermostat ignores the write
    r = client.put(
        url(owner, thermostat), json={"auto_dst": False}, headers=csrf(client)
    )
    assert r.status_code == 502 and "did not take" in r.json()["detail"]
    db.expire_all()
    assert (
        db.query(AuditEvent).filter_by(event_type="thermostat_settings_failed").count()
        == 1
    )


def test_only_yes_no_settings_change(client, owner, csrf, thermostat, held):
    for body in (
        {},
        {"early_on": "yes"},
        {"early_on": 1},
        {"min_fan_runtime": 5},
        {"temperature_offset": "2.0F"},
    ):
        r = client.put(url(owner, thermostat), json=body, headers=csrf(client))
        assert r.status_code == 422, body
    assert held["writes"] == []


def test_guests_and_other_devices_are_refused(
    client, db, owner, csrf, thermostat, held, make_device, make_user, new_client, login
):
    lamp = make_device(owner.home_id, name="Lamp")
    r = client.get(f"/api/v1/homes/{owner.home_id}/devices/{lamp}/settings")
    assert r.status_code == 409
    guest = make_user(owner.home_id, role="guest")
    g = new_client()
    assert login(g, guest).status_code == 200
    assert g.get(url(owner, thermostat)).status_code == 403


def test_ui_settings_window(open_page, db, owner, monkeypatch):
    report = t.thermostat_state(t.parse_probe_reply(_thermostat.FULL_REPLY))
    hall = Device(
        home_id=owner.home_id,
        integration="cync",
        external_id="77-9",
        type="thermostat",
        name="Hallway",
        room="Lab",
        capabilities=json.dumps({"cloud_id": CLOUD_ID}),
        state=json.dumps(report),
        online=True,
    )
    db.add(hall)
    db.commit()
    features.set_integration(db, owner.home_id, "cync", True, None, None)
    now = {"early_on": False, "celsius": False, "auto_dst": None}
    sent = []

    def answer():
        info = {k: None for k in thermostat_settings.SETTINGS}
        info.update(now, min_fan_runtime=10, temperature_offset="-1.0F")
        return {
            "settings": info,
            "missing": [],
            "editable": ["early_on", "celsius", "auto_dst"],
        }

    def fake_read(db_, device, refresh=False):
        return answer()

    def fake_write(db_, device, changes):
        sent.append(changes)
        now.update(changes)
        return answer()

    monkeypatch.setattr("app.routes.thermostat.read_settings", fake_read)
    monkeypatch.setattr("app.routes.thermostat.write_settings", fake_write)
    page = open_page()
    _ui.ui_login(page, owner)
    tile = _ui.card(page, "Hallway")
    expect(tile.get_by_test_id("thermo-settings-open")).to_be_visible()
    tile.get_by_test_id("thermo-settings-open").click()
    panel = page.get_by_test_id("thermo-settings-panel")
    early = panel.get_by_test_id("thermo-setting-early_on")
    expect(early).not_to_be_checked()
    expect(panel.get_by_test_id("thermo-setting-auto_dst")).to_contain_text(
        "not reported"
    )
    expect(panel.get_by_test_id("thermo-info-min_fan_runtime")).to_have_text("10")
    expect(panel.get_by_test_id("thermo-info-dehumidify")).to_have_text("Not reported")
    early.check()
    expect(page.get_by_test_id("status")).to_contain_text("took the change")
    expect(panel.get_by_test_id("thermo-setting-early_on")).to_be_checked()
    assert sent == [{"early_on": True}]
    panel.get_by_test_id("thermo-settings-close").click()
    expect(panel).to_have_count(0)
