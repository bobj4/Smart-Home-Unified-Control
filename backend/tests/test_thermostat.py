"""Cync thermostat: decoding its reports, building writes, commands with the
safety limits and the Eco rule, the tile; and the water heater's status and
usage graph. Written by the reviewer. Do not edit, skip, mark or delete these
tests. If one looks wrong, stop and report the test name and its full
failure output instead of changing it.

Nothing talks to Cync or Rheem: the live connection and the adapters' network
calls are fakes. The probe reply below is the owner's real thermostat's.
"""

import asyncio
import concurrent.futures
import json
import struct
from types import SimpleNamespace

import pytest
from playwright.sync_api import expect
from pycync.devices.device_types import DeviceType

from app import cync_home, cync_live
from app.integrations import cync, rheem
from app.integrations import cync_thermostat as t
from app.models import Device
from app.safety import apply_recommended
from tests import test_cync as _cync
from tests import test_rheem as _rheem
from tests import test_ui as _ui

fake, secrets_key, econet = _cync.fake, _cync.secrets_key, _rheem.econet
card, ui_login = _ui.card, _ui.ui_login
CLOUD_ID = 123456789
# The probe reply body after the device id, from the owner's thermostat.
REPLY = bytes.fromhex(
    "001800070009786c696e6b5f64657600900856312e322e31333601900856322e302e30313102"
    "90052d3530644204900536372e35460540040000002c06400400000002084004000000000a90"
    "0536382e30460c40040000000310400400000001604004000000005b9004302e304668400400"
    "00000169a0060002000202016a90317b22526573657444617461223a22323032362d30362d31"
    "375431383a32353a3435222c2252756e74696d65223a3938347d"
)


def sensors_entry(text):
    raw = text.encode()
    return bytes([87]) + struct.pack(">H", 0x9000 | len(raw)) + raw


SENSORS = (
    'sensorsData:[{"Type":"internal","Temperature":"67.1F","Humidity":45,"Active":true},'
    '{"Type":"savant sensor","PinCode":135790,"Temperature":"67.8F","Humidity":44,'
    '"Active":true,"Batt":"2.89"},{"Type":"None","Temperature":null,"Active":true}]'
)
FULL_REPLY = REPLY + sensors_entry(SENSORS)


def test_decodes_the_real_probe_reply():
    points = t.parse_probe_reply(FULL_REPLY)
    s = t.thermostat_state(points)
    assert (s["current_temperature"], s["humidity"], s["mode"], s["fan"]) == (
        67.5,
        44,
        "heat",
        "auto",
    )
    assert (s["heat_setpoint"], s["cool_setpoint"], s["target_temperature"]) == (
        68.0,
        None,
        68.0,
    )
    assert (s["status"], s["hold"], s["system"]) == (
        "idle",
        "permanent",
        "Heat and cool (1 stage)",
    )
    assert s["modes"] == ["off", "heat", "cool", "auto", "eco"]
    assert (s["filter_hours"], s["filter_reset"]) == (984, "2026-06-17")
    assert (s["firmware"], s["wifi"], s["device_unit"]) == ("V1.2.136", "-50dB", "F")
    assert s["sensors"] == [
        {
            "name": "Thermostat",
            "temperature": 67.1,
            "humidity": 45,
            "battery": None,
            "active": True,
            "pin": None,
        },
        {
            "name": "Remote sensor",
            "temperature": 67.8,
            "humidity": 44,
            "battery": "2.89",
            "active": True,
            "pin": "135790",
        },
    ]
    assert t.parse_probe_reply(bytes.fromhex("0018" + "0a")) is None  # offline


def test_builds_writes_as_the_notes_describe():
    # The notes' example: heat set point 72.0F.
    assert t.set_packet(0x01020304, 0x0506, [(t.HEAT_SET, "72.0F")]).hex() == (
        "330000000f" + "01020304" + "0506" + "06" + "0b9005" + "37322e3046"
    )
    assert t.entry(t.MODE_SET, 1).hex() == "07400400000001"
    assert t.probe_packet(CLOUD_ID, 24).hex() == "a300000007075bcd1500" + "1800"
    assert t.format_temperature(72, "F") == "72.0F"
    assert t.format_temperature(68, "C") == "20.0C"
    assert t.temperature_f("20.0C") == 68.0 and t.temperature_f("x") is None
    points = {t.MODE: 1, t.HEAT_SETPOINT: "72.0F"}
    assert t.confirmed([(t.MODE_SET, 1), (t.HEAT_SET, "72.0F")], points)
    assert not t.confirmed([(t.HEAT_SET, "73.0F")], points)
    assert t.modes_for(4)[-1] == "emergency" and t.modes_for(2) == [
        "off",
        "heat",
        "eco",
    ]


class FakeTcp:
    def __init__(self):
        self.sent = []
        self.seen = []
        self.link = None

        async def original(message):
            self.seen.append(message)

        self._client_callback = original

    async def _send_request(self, packet):
        self.sent.append(packet)
        if packet[0] >> 4 == t.PROBE:  # the thermostat answers a probe
            device_id = struct.unpack(">I", packet[5:9])[0]
            reply = SimpleNamespace(
                message_type=t.PROBE, is_response=True, device_id=device_id, data=REPLY
            )
            asyncio.get_running_loop().call_soon(
                lambda: asyncio.ensure_future(self._client_callback(reply))
            )


def test_link_hooks_replies_and_writes(monkeypatch):
    monkeypatch.setattr(asyncio, "sleep", _no_sleep())
    tcp = FakeTcp()
    api = SimpleNamespace(_command_client=SimpleNamespace(_tcp_manager=tcp))
    reports = []
    link = t.attach(api, lambda device_id, points: reports.append((device_id, points)))
    assert api.thermostat_link is link
    link.ids = {CLOUD_ID}

    async def run():
        await link.probe_all()
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        return await link.write(CLOUD_ID, [(t.HEAT_SET, "68.0F")])

    with concurrent.futures.ThreadPoolExecutor(1) as pool:  # no loop clash
        points = pool.submit(asyncio.run, run()).result()
    assert points[t.HEAT_SETPOINT] == "68.0F"
    assert len(reports) >= 2 and reports[0][0] == CLOUD_ID
    assert len(tcp.seen) >= 2  # pycync still got every message
    kinds = [p[0] >> 4 for p in tcp.sent]
    assert kinds == [t.PROBE, t.SET, t.PROBE]
    t.attach(api, lambda *a: None)  # re-attaching does not stack hooks
    assert tcp._client_callback.original is not None


def _no_sleep():
    real = asyncio.sleep

    async def fast(seconds, *args):
        await real(0)

    return fast


def test_adapter_lists_the_thermostat():
    device = SimpleNamespace(
        device_type=DeviceType.THERMOSTAT,
        unique_id="77-9",
        name="Hallway",
        is_online=True,
        mac="3413431C0CE5",
        device_id=CLOUD_ID,
    )
    found = cync._info(device)
    assert (found.kind, found.cloud_id, found.name) == (
        "thermostat",
        CLOUD_ID,
        "Hallway",
    )


@pytest.fixture
def thermostat(client, db, owner, login, csrf, fake, secrets_key, monkeypatch):
    fake.devices = [_cync.info("77-9", "thermostat", name="Hallway", cloud_id=CLOUD_ID)]
    _cync.ready(client, csrf, login, owner)
    apply_recommended(db, owner.home_id, None, None)
    did = _cync.device_id(db, owner.home_id, "77-9")
    report = t.thermostat_state(t.parse_probe_reply(FULL_REPLY))
    cync_home.store_states(db, owner.home_id, {"77-9": {"thermostat": report}})
    writes = []
    answer = {}

    def write(api, loop, cloud_id, entries):
        writes.append((cloud_id, entries))
        points = dict(t.parse_probe_reply(REPLY))
        for index, value in entries:
            points[t.REPORTED_BY[index]] = value
        points.update(answer)
        return points

    monkeypatch.setattr(cync_live, "connection", lambda home_id: ("api", "loop"))
    monkeypatch.setattr(cync, "thermostat_write_on_open", write)
    return SimpleNamespace(id=did, writes=writes, answer=answer)


def state(db, device_id):
    db.expire_all()
    return json.loads(db.get(Device, device_id).state)


def test_thermostat_commands(client, db, owner, csrf, thermostat):
    home, did = owner.home_id, thermostat.id
    s = state(db, did)
    assert (s["current_temperature"], s["mode"]) == (67.5, "heat")
    assert json.loads(db.get(Device, did).capabilities)["cloud_id"] == CLOUD_ID

    def send(name, **payload):
        return _cync.command(client, csrf, home, did, name, **payload)

    assert send("set_temperature", temperature=70).status_code == 200
    assert thermostat.writes[-1] == (CLOUD_ID, [(t.HEAT_SET, "70.0F")])
    assert state(db, did)["heat_setpoint"] == 70
    assert send("set_temperature", temperature=95).status_code == 422  # limits
    assert send("set_fan", fan="on").status_code == 200
    assert thermostat.writes[-1] == (CLOUD_ID, [(t.FAN_SET, 1)])
    assert send("set_fan", fan="turbo").status_code == 422
    assert send("set_mode", mode="cool").status_code == 200
    assert thermostat.writes[-1] == (CLOUD_ID, [(t.MODE_SET, 1)])
    assert send("set_temperature", temperature=76).status_code == 200
    assert thermostat.writes[-1] == (CLOUD_ID, [(t.COOL_SET, "76.0F")])
    assert send("set_cool_temperature", temperature=77).status_code == 422  # not Auto
    assert send("set_mode", mode="emergency").status_code == 422  # not a heat pump
    assert send("set_mode", mode="auto").status_code == 200
    assert send("set_temperature", temperature=68).status_code == 200  # heat in Auto
    assert send("set_cool_temperature", temperature=67).status_code == 422
    assert send("set_cool_temperature", temperature=75).status_code == 200
    assert thermostat.writes[-1] == (CLOUD_ID, [(t.COOL_SET, "75.0F")])
    assert send("set_mode", mode="eco").status_code == 200
    count = len(thermostat.writes)
    r = send("set_temperature", temperature=70)
    assert r.status_code == 409 and "Eco" in r.json()["detail"]
    assert len(thermostat.writes) == count  # nothing was sent


def test_unconfirmed_write_changes_nothing(client, db, owner, csrf, thermostat):
    thermostat.answer[t.HEAT_SETPOINT] = "68.0F"  # the thermostat kept 68
    r = _cync.command(
        client, csrf, owner.home_id, thermostat.id, "set_temperature", temperature=71
    )
    assert r.status_code == 502 and "did not take" in r.json()["detail"]
    assert state(db, thermostat.id)["heat_setpoint"] == 68.0


def test_no_live_connection(client, db, owner, csrf, thermostat, monkeypatch):
    monkeypatch.setattr(cync_live, "connection", lambda home_id: None)
    r = _cync.command(
        client, csrf, owner.home_id, thermostat.id, "set_mode", mode="cool"
    )
    assert r.status_code == 503


def test_demo_thermostat_keeps_its_dial(client, db, owner, make_device, login, csrf):
    hall = make_device(owner.home_id, device_type="thermostat", name="Hall")
    apply_recommended(db, owner.home_id, None, None)
    assert login(client, owner).status_code == 200
    r = _cync.command(
        client, csrf, owner.home_id, hall, "set_temperature", temperature=70
    )
    assert r.status_code == 200 and state(db, hall)["target_temperature"] == 70
    r = _cync.command(client, csrf, owner.home_id, hall, "set_mode", mode="cool")
    assert r.status_code == 422


def test_ui_thermostat_tile(open_page, db, owner, make_device):
    hall = make_device(owner.home_id, device_type="thermostat", name="Hallway")
    apply_recommended(db, owner.home_id, None, None)
    d = db.get(Device, hall)
    d.state = json.dumps(t.thermostat_state(t.parse_probe_reply(FULL_REPLY)))
    db.commit()
    page = open_page()
    ui_login(page, owner)
    tile = card(page, "Hallway")
    expect(tile.get_by_test_id("thermo-temp")).to_have_text("67.5 °F")
    expect(tile.get_by_test_id("thermo-heat-value")).to_have_text("Heat to 68 °F")
    expect(tile.get_by_test_id("thermo-status")).to_have_text("Idle")
    expect(tile.get_by_test_id("thermo-humidity")).to_have_text("44% humidity")
    expect(tile.get_by_test_id("thermo-mode")).to_have_value("heat")
    expect(tile.get_by_test_id("thermo-fan")).to_have_text("Fan: auto")
    expect(tile.get_by_test_id("thermo-sensors")).to_contain_text(
        "Remote sensor: 67.8 °F · 44% · battery 2.89 V"
    )
    expect(tile.get_by_test_id("thermo-hold")).to_have_text("Permanent hold")
    tile.get_by_test_id("thermo-info-open").click()
    panel = page.get_by_test_id("thermo-panel")
    expect(panel).to_contain_text("984 h since 2026-06-17")
    panel.get_by_test_id("thermo-close").click()
    eco = {**json.loads(d.state), "mode": "eco"}
    db.expire_all()
    db.get(Device, hall).state = json.dumps(eco)
    db.commit()
    page.reload()
    tile = card(page, "Hallway")
    expect(tile.get_by_test_id("thermo-eco")).to_be_visible()
    expect(tile.get_by_test_id("thermo-heat-up")).to_have_count(0)  # none in Eco


def test_heater_running_value():
    assert rheem.is_running("Heating") is True
    for idle in (None, "", " ", "0", "Idle", "Off", "Not running", {"value": ""}):
        assert rheem.is_running(idle) is False, idle
    assert rheem.is_running({"title": "Compressor running"}) is True


class FakeApi:
    def __init__(self):
        self.asked = []

    async def get_dynamic_action(self, payload):
        self.asked.append(payload)
        day = int(payload["start_date"][8:10])
        if payload["usage_type"] == "energyUsage":
            data = [{"name": "6", "value": 0.5}, {"name": "18", "value": day / 10}]
            return {
                "results": {
                    "energy_usage": {"data": data, "message": "Energy used in KWH"}
                }
            }
        raise rheem.InvalidResponseFormat("no water report")


def test_heater_usage_by_hour_and_day(monkeypatch):
    api = FakeApi()
    unit = SimpleNamespace(serial_number="S1", device_id="D1")
    client = rheem.PyeconetClient("me@example.com", "pw")

    async def heaters():
        return api, [unit]

    monkeypatch.setattr(client, "_heaters", heaters)
    today = client.usage("S1", 1)
    assert today["energy"] == [
        {"label": "6", "value": 0.5},
        {"label": "18", "value": today["energy"][1]["value"]},
    ]
    assert (today["water"], today["energy_unit"]) == (None, "KWH")
    week = client.usage("S1", 7)
    assert (
        len(week["energy"]) == 7
        and week["energy"][-1]["label"] > week["energy"][0]["label"]
    )
    assert all(p["value"] > 0.5 for p in week["energy"])
    first = api.asked[0]
    assert (
        first["ACTION"] == "waterheaterUsageReportView"
        and first["serial_number"] == "S1"
    )


def test_ui_heater_usage_graph(open_page, db, owner, monkeypatch):
    tank = Device(
        home_id=owner.home_id,
        integration="rheem_econet",
        external_id="S1",
        type="water_heater",
        name="Tank",
        room="Lab",
        capabilities="{}",
        state=json.dumps({"target_temperature": 120, "unit": "F", "status": "idle"}),
        online=True,
    )
    db.add(tank)
    db.commit()
    days7 = [f"2026-10-{d:02}" for d in range(17, 24)]
    usage = {
        1: {
            "days": 1,
            "energy_unit": "KWH",
            "water": None,
            "energy": [{"label": str(h), "value": h / 10} for h in range(24)],
        },
        7: {
            "days": 7,
            "energy_unit": "KWH",
            "water": [{"label": d, "value": 20.0} for d in days7],
            "energy": [{"label": d, "value": 3.0} for d in days7],
        },
    }
    asked = []

    def fake_usage(db_, device, days):
        asked.append(days)
        return usage[days]

    monkeypatch.setattr("app.routes.rheem.usage", fake_usage)
    page = open_page()
    ui_login(page, owner)
    card(page, "Tank").get_by_test_id("heater-usage").click()
    panel = page.get_by_test_id("usage-panel")
    expect(panel.get_by_test_id("usage-readout")).to_have_text("27.60 kWh in total")
    expect(panel.locator(".usage-bar")).to_have_count(24)
    panel.locator(".usage-hit").nth(15).hover()
    expect(panel.get_by_test_id("usage-readout")).to_have_text("3 PM: 1.50 kWh")
    panel.get_by_test_id("usage-7").click()
    expect(panel.locator(".usage-bar")).to_have_count(7)
    panel.get_by_test_id("usage-water").click()
    expect(panel.get_by_test_id("usage-readout")).to_have_text("140 gal in total")
    panel.get_by_test_id("usage-1").click()
    expect(panel.get_by_test_id("usage-none")).to_be_visible()
    panel.get_by_test_id("usage-close").click()
    expect(panel).to_be_hidden()
    assert asked == [1, 7, 1]
