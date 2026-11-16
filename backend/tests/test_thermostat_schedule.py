"""Thermostat schedule reading: ReadSetting answers (in the format the
owner's thermostat sent on 2026-10-24), the schedule API and the Schedule
window. Written by the reviewer. Do not edit, skip, mark or delete these
tests. If one looks wrong, stop and report the test name and its full failure
output instead of changing it. Nothing talks to Cync."""

import asyncio
import concurrent.futures
import json
import struct
from types import SimpleNamespace

from playwright.sync_api import expect

from app import cync_live, thermostat_schedule
from app.integrations import cync
from app.integrations import cync_schedule as s
from app.integrations import cync_thermostat as t
from app.models import Device
from tests import test_thermostat as _thermostat
from tests import test_ui as _ui

fake, secrets_key = _thermostat.fake, _thermostat.secrets_key
thermostat = _thermostat.thermostat
card, ui_login = _ui.card, _ui.ui_login
CLOUD_ID = _thermostat.CLOUD_ID
# Temp_Read_Schd_Mon as the thermostat answered it (padded with 255).
SENSOR_MON = [7, 0, 2, 0, 0, 0, 0, 0, 0, 0, 8, 0, 1, 1, 49, 51, 53, 55, 57, 48]
SENSOR_MON += [14, 0, 2, 0, 0, 0, 0, 0, 0, 0, 22, 30, 0, 0, 0, 0, 0, 0, 0, 0]
SENSOR_MON += [255] * 60


def push(device_id, reply):
    """A SYNC push of point 84, as the thermostat sends it."""
    raw = json.dumps(reply).encode()
    body = struct.pack(">IH", device_id, 0x0101) + b"\x06"
    body += bytes([84]) + struct.pack(">H", 0x9000 | len(raw)) + raw
    return bytes([0x43]) + struct.pack(">I", len(body)) + body


def answers():
    values = {name: None for name in s.read_names()}
    values["Temp_Read_Schd_Mon"] = SENSOR_MON
    values["Sched_Heat_Tue"] = list(
        s.encode_schedule("heat", [{"time": "06:30", "heat": 68.0}])
    )
    return values


def test_week_from_the_thermostats_answers():
    week = s.week_from_settings(answers())
    assert week["heat"]["mon"] is None
    assert week["heat"]["tue"] == [{"time": "06:30", "heat": 68.0}]
    assert [p["read"] for p in week["sensors"]["mon"]] == [
        "all",
        "sensor",
        "all",
        "thermostat",
    ]
    assert week["sensors"]["mon"][1]["pin"] == "135790"


class FakeTcp:
    def __init__(self, link_holder, values):
        self.sent = []
        self.holder = link_holder
        self.values = values

        async def original(message):
            return None

        self._client_callback = original

    async def _send_request(self, packet):
        self.sent.append(packet)
        name = packet[5 + 7 + 3 :].decode()  # deviceId msgId 06, then index+header
        if name in self.values:
            reply = push(CLOUD_ID, {name: self.values[name]})
            asyncio.get_running_loop().call_soon(self.holder.link.raw, reply)


def test_link_reads_settings_from_pushes():
    holder = SimpleNamespace(link=None)
    values = {"Sched_Heat_Mon": None, "Temp_Read_Schd_Mon": SENSOR_MON}
    tcp = FakeTcp(holder, values)
    api = SimpleNamespace(_command_client=SimpleNamespace(_tcp_manager=tcp))
    holder.link = t.attach(api, lambda *a: None)
    holder.link.ids = {CLOUD_ID}
    t.SETTING_SECONDS, saved = 0.3, t.SETTING_SECONDS

    async def run():
        names = ["Sched_Heat_Mon", "Temp_Read_Schd_Mon", "Sched_Cool_Mon"]
        return await holder.link.read_settings(CLOUD_ID, names)

    try:
        with concurrent.futures.ThreadPoolExecutor(1) as pool:  # no loop clash
            found = pool.submit(asyncio.run, run()).result()
    finally:
        t.SETTING_SECONDS = saved
        t.detach(api)
    assert found == {"Sched_Heat_Mon": None, "Temp_Read_Schd_Mon": SENSOR_MON}
    # Each request is a set packet writing the name to ReadSetting (84).
    assert tcp.sent[0][5 + 6] == 6 and tcp.sent[0][5 + 7] == 84


def test_pycync_still_parses_every_packet():
    from pycync.tcp import packet_parser

    tcp = FakeTcp(SimpleNamespace(link=None), {})
    api = SimpleNamespace(_command_client=SimpleNamespace(_tcp_manager=tcp))
    link = t.attach(api, lambda *a: None)
    link.ids = {CLOUD_ID}
    seen = []
    link.raw = seen.append
    try:
        login = bytes.fromhex("1800000002") + b"\x00\x00"
        parsed = packet_parser.parse_packet(bytearray(login), 42)
        assert parsed.message_type == 1  # pycync's own result
        assert seen == [login]
    finally:
        t.detach(api)


def test_schedule_api(client, db, owner, csrf, thermostat, monkeypatch):
    asked = []

    def read(api, loop, cloud_id, names):
        asked.append((cloud_id, len(names)))
        return answers()

    monkeypatch.setattr(cync, "thermostat_settings_on_open", read)
    thermostat_schedule._schedule_cache.clear()
    url = f"/api/v1/homes/{owner.home_id}/devices/{thermostat.id}/schedule"
    r = client.get(url)
    assert r.status_code == 200, r.text
    week = r.json()["week"]
    assert week["sensors"]["mon"][1]["label"] == "Remote sensor"
    assert week["heat"]["tue"][0]["heat"] == 68.0
    assert r.json()["missing"] == []
    assert asked == [(CLOUD_ID, 28)]
    assert client.get(url).status_code == 200 and len(asked) == 1  # kept
    assert client.get(url + "?refresh=true").status_code == 200 and len(asked) == 2
    monkeypatch.setattr(cync_live, "connection", lambda home_id: None)
    thermostat_schedule._schedule_cache.clear()
    assert client.get(url).status_code == 503
    assert writes_nothing(thermostat)


def writes_nothing(thermostat):
    return thermostat.writes == []


def test_schedule_only_for_cync(client, db, owner, make_device, login):
    hall = make_device(owner.home_id, device_type="thermostat", name="Hall")
    assert login(client, owner).status_code == 200
    r = client.get(f"/api/v1/homes/{owner.home_id}/devices/{hall}/schedule")
    assert r.status_code == 409
    assert (
        client.get(f"/api/v1/homes/{owner.home_id}/devices/nope/schedule").status_code
        == 404
    )


def test_ui_schedule_window(open_page, db, owner, monkeypatch):
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
    week = s.week_from_settings(answers())
    week["sensors"]["mon"][1]["label"] = "Remote sensor"
    calls = []

    def fake_read(db_, device, refresh=False):
        calls.append(refresh)
        return {"week": week, "missing": []}

    monkeypatch.setattr("app.routes.thermostat.read_schedule", fake_read)
    page = open_page()
    ui_login(page, owner)
    card(page, "Hallway").get_by_test_id("thermo-schedule-open").click()
    panel = page.get_by_test_id("schedule-panel")
    expect(panel.get_by_test_id("schedule-tab-heat")).to_have_attribute(
        "aria-pressed", "true"
    )
    expect(panel.get_by_test_id("schedule-tue")).to_contain_text("6:30 AM → 68 °F")
    expect(panel.get_by_test_id("schedule-mon")).to_contain_text("Nothing set")
    panel.get_by_test_id("schedule-tab-cool").click()
    expect(panel.get_by_test_id("schedule-empty")).to_have_text(
        "No cooling schedule is set on the thermostat."
    )
    panel.get_by_test_id("schedule-tab-sensors").click()
    monday = panel.get_by_test_id("schedule-mon")
    expect(monday).to_contain_text("7:00 AM → All sensors")
    expect(monday).to_contain_text("8:00 AM → Remote sensor")
    expect(monday).to_contain_text("10:30 PM → Thermostat only")
    panel.get_by_test_id("schedule-refresh").click()
    expect(panel.get_by_test_id("schedule-mon")).to_be_visible()
    assert calls == [False, True]
    panel.get_by_test_id("schedule-close").click()
    expect(panel).to_have_count(0)


def test_demo_thermostat_has_no_schedule_button(open_page, db, owner, make_device):
    hall = make_device(owner.home_id, device_type="thermostat", name="Hallway")
    d = db.get(Device, hall)
    d.state = json.dumps(
        t.thermostat_state(t.parse_probe_reply(_thermostat.FULL_REPLY))
    )
    db.commit()
    page = open_page()
    ui_login(page, owner)
    expect(card(page, "Hallway").get_by_test_id("thermo-info-open")).to_be_visible()
    expect(card(page, "Hallway").get_by_test_id("thermo-schedule-open")).to_have_count(
        0
    )


def test_sensor_pins_are_in_the_state():
    report = t.thermostat_state(t.parse_probe_reply(_thermostat.FULL_REPLY))
    assert [x["pin"] for x in report["sensors"]] == [None, "135790"]
