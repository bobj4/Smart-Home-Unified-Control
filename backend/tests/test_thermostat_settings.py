"""A Cync thermostat's own settings (the Settings window under Schedule):
read by name, changed and read back. Nothing talks to Cync."""

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
        "Furnace_Type_set": 0,
        "Power_Line": 1,
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
                # yes/no come back as 1/0; text and numbers as written
                stored[by_index[index]] = (
                    int(value) if isinstance(value, bool) else value
                )
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
    assert settings["temperature_offset"] == "-1F"
    assert settings["auto_deadband"] == "3F"
    assert settings["humidity_offset"] is None  # not a plain value: not shown
    assert "heat_pump_changeover" in body["missing"]
    assert "raw" not in body
    assert set(body["editable"]) == (
        set(thermostat_settings.SETTINGS) - {"power_wires"}
    ) | {"system_type"}
    assert body["limits"]["min_fan_runtime"] == [0, 60]

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

    # Numbers: whole ones as numbers, text ones in the form they are kept in.
    r = client.put(
        url(owner, thermostat),
        json={"min_fan_runtime": 15, "temperature_offset": 1.5},
        headers=csrf(client),
    )
    assert r.status_code == 200, r.text
    assert held["writes"][-1] == [(26, 15), (21, "1.5F")]
    assert r.json()["settings"]["temperature_offset"] == "1.5F"
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


def test_system_and_furnace(
    client, db, owner, csrf, thermostat, held, make_user, new_client, login, monkeypatch
):
    r = client.get(url(owner, thermostat))
    settings = r.json()["settings"]
    assert settings["furnace_type"] == 0 and settings["power_wires"] == 1
    assert settings["system_type"] == 3  # the report: 1 stage heat and cool
    assert r.json()["choices"]["system_type"]["4"].startswith("1 Compressor Heat Pump")
    r = client.put(
        url(owner, thermostat), json={"furnace_type": 2}, headers=csrf(client)
    )
    assert r.status_code == 200, r.text
    assert held["writes"][-1] == [(14, 2)]
    assert r.json()["settings"]["furnace_type"] == 2
    assert (
        client.put(
            url(owner, thermostat), json={"furnace_type": 7}, headers=csrf(client)
        ).status_code
        == 422
    )
    # The system type is checked in the thermostat's own report.
    sent = []

    def write(api, loop, cloud_id, entries):
        sent.append(entries)
        points = dict(t.parse_probe_reply(_thermostat.REPLY))
        points[t.HVAC_TYPE] = entries[0][1]
        return points

    monkeypatch.setattr(cync, "thermostat_write_on_open", write)
    r = client.put(
        url(owner, thermostat), json={"system_type": 4}, headers=csrf(client)
    )
    assert r.status_code == 200, r.text
    assert sent == [[(13, 4)]]
    assert r.json()["settings"]["system_type"] == 4
    db.expire_all()
    stored = json.loads(db.get(Device, thermostat.id).state)
    assert "emergency" in stored["modes"]  # a heat pump has emergency heat
    for body in ({"system_type": 10}, {"system_type": 4, "early_on": True}):
        r = client.put(url(owner, thermostat), json=body, headers=csrf(client))
        assert r.status_code == 422, body
    # Installer settings are for admins; members can still use Early On.
    member = make_user(owner.home_id, role="member")
    m = new_client()
    assert login(m, member).status_code == 200
    assert (
        m.put(
            url(owner, thermostat), json={"furnace_type": 0}, headers=csrf(m)
        ).status_code
        == 403
    )
    assert (
        m.put(
            url(owner, thermostat), json={"early_on": True}, headers=csrf(m)
        ).status_code
        == 200
    )


def test_refused_values_write_nothing(client, owner, csrf, thermostat, held):
    for body in (
        {},
        {"early_on": "yes"},
        {"early_on": 1},
        {"min_fan_runtime": 61},  # outside its range
        {"min_fan_runtime": 5.5},  # minutes are whole
        {"temperature_offset": "2.0F"},  # a number, not text
        {"temperature_offset": 9},
        {"temperature_offset": 1.25},  # steps of 0.5
        {"humidity_offset": 2},  # not reported in a known form
        {"firmware": "x"},
        {"power_wires": 0},  # shown only
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
    now = {"early_on": False, "celsius": False, "auto_dst": None, "min_fan_runtime": 10}
    sent = []

    def answer():
        info = {k: None for k in thermostat_settings.SETTINGS}
        info.update(now, temperature_offset="-1F")
        limits = {k: list(v) for k, v in thermostat_settings.LIMITS.items()}
        return {
            "settings": info,
            "missing": [],
            "editable": list(thermostat_settings.SETTINGS),
            "limits": limits,
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
    # The installer settings are in sub menus, folded at first.
    fan = panel.get_by_test_id("thermo-group-fan")
    expect(panel.get_by_test_id("thermo-setting-min_fan_runtime")).to_be_hidden()
    expect(early).to_be_visible()  # the top three are not in a sub menu
    fan.locator("summary").click()
    for group in ("calibration", "humidity"):
        panel.get_by_test_id(f"thermo-group-{group}").locator("summary").click()
    expect(panel.get_by_test_id("thermo-setting-min_fan_runtime")).to_have_value("10")
    expect(panel.get_by_test_id("thermo-setting-temperature_offset")).to_have_value(
        "-1"
    )
    expect(panel.get_by_test_id("thermo-setting-dehumidify")).to_contain_text(
        "not reported"
    )
    early.check()
    expect(page.get_by_test_id("status")).to_contain_text("took the change")
    expect(panel.get_by_test_id("thermo-setting-early_on")).to_be_checked()
    panel.get_by_test_id("thermo-setting-min_fan_runtime").fill("20")
    panel.get_by_test_id("thermo-save-min_fan_runtime").click()
    for _ in range(50):  # the change is sent, then the window is drawn again
        if len(sent) == 2:
            break
        page.wait_for_timeout(100)
    expect(panel.get_by_test_id("thermo-setting-min_fan_runtime")).to_have_value("20")
    expect(fan).to_have_attribute("open", "")  # still open after the redraw
    expect(panel.get_by_test_id("thermo-group-heat-pump")).not_to_have_attribute(
        "open", ""
    )
    assert sent == [{"early_on": True}, {"min_fan_runtime": 20}]
    panel.get_by_test_id("thermo-settings-close").click()
    expect(panel).to_have_count(0)
