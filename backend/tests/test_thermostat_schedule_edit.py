"""Editing thermostat schedules: encoding, the write-then-read-back check,
safety limits, the API and the editor. Written by the reviewer. Do not edit,
skip, mark or delete these tests. If one looks wrong, stop and report the
test name and its full failure output instead of changing it. Nothing talks
to Cync."""

import asyncio
import concurrent.futures
import json
from types import SimpleNamespace

import pytest
from playwright.sync_api import expect

from app import cync_live, thermostat_schedule
from app.cync_home import CyncUnavailable
from app.features import set_integration
from app.integrations import cync
from app.integrations import cync_schedule as s
from app.integrations import cync_thermostat as t
from app.models import AuditEvent, Device
from app.safety import apply_recommended
from tests import test_thermostat as _thermostat
from tests import test_thermostat_schedule as _read
from tests import test_ui as _ui

fake, secrets_key = _thermostat.fake, _thermostat.secrets_key
thermostat = _thermostat.thermostat
card, ui_login = _ui.card, _ui.ui_login
CLOUD_ID = _thermostat.CLOUD_ID
PIN = "024944"


def test_encoding_and_read_back_check():
    sensors = [
        {"time": "07:00", "read": "all"},
        {"time": "08:00", "read": "sensor", "pin": PIN},
        {"time": "22:30", "read": "thermostat"},
    ]
    raw = s.encode_day("sensors", sensors)
    assert raw[:10] == bytes([7, 0, 2]) + bytes(7)
    assert raw[10:20] == bytes([8, 0, 1, 1]) + PIN.encode()
    padded = list(raw) + [255] * (100 - len(raw))
    assert s.same_day("sensors", sensors, padded)
    assert not s.same_day("sensors", sensors[:2], padded)
    heat = [{"time": "06:30", "heat": 68.0}, {"time": "22:00", "heat": 62.0}]
    assert s.same_day("heat", heat, list(s.encode_day("heat", heat)))
    assert not s.same_day(
        "heat", [{"time": "06:30", "heat": 69.0}], list(s.encode_day("heat", heat))
    )
    assert s.same_day("cool", [], None) and s.encode_day("cool", []) == b"\xff"
    assert s.day_index("sensors", "sun") == 43 and s.day_index("auto", "mon") == 77
    with pytest.raises(s.ScheduleError):
        s.encode_day("heat", [{"time": f"{h:02d}:00", "heat": 68} for h in range(7)])
    with pytest.raises(s.ScheduleError):
        s.encode_day("sensors", [{"time": "07:00", "read": "sensor", "pin": "12"}])
    assert t.entry(63, b"\xff") == bytes([63, 0xA0, 0x01, 0xFF])  # bytes header


class StoringTcp:
    """A thermostat that keeps what is written and answers ReadSetting."""

    def __init__(self, holder):
        self.holder = holder
        self.stored = {}
        self.sent = []

        async def original(message):
            return None

        self._client_callback = original

    async def _send_request(self, packet):
        self.sent.append(packet)
        body = packet[5:]
        i = 7
        while i + 3 <= len(body):
            index = body[i]
            length = int.from_bytes(body[i + 1 : i + 3], "big") & 0x0FFF
            value = body[i + 3 : i + 3 + length]
            if index == 84:
                name = value.decode()
                kind = (
                    "sensors" if name.startswith("Temp") else name.split("_")[1].lower()
                )
                day = name[-3:].lower()
                held = self.stored.get(s.day_index(kind, day))
                answer = {name: list(held) + [255] * 10 if held else None}
                loop = asyncio.get_running_loop()
                loop.call_soon(self.holder.link.raw, _read.push(CLOUD_ID, answer))
            else:
                self.stored[index] = value
            i += 3 + length


def test_link_writes_then_reads_back(monkeypatch):
    holder = SimpleNamespace(link=None)
    tcp = StoringTcp(holder)
    api = SimpleNamespace(_command_client=SimpleNamespace(_tcp_manager=tcp))
    holder.link = t.attach(api, lambda *a: None)
    holder.link.ids = {CLOUD_ID}
    real_sleep = asyncio.sleep

    async def no_wait(seconds, *args):
        await real_sleep(0)

    monkeypatch.setattr(asyncio, "sleep", no_wait)
    heat = s.encode_day("heat", [{"time": "06:30", "heat": 68.0}])

    async def run():
        entries = [(63, heat), (64, heat)]
        return await holder.link.write_settings(
            CLOUD_ID, entries, ["Sched_Heat_Mon", "Sched_Heat_Tue"]
        )

    try:
        with concurrent.futures.ThreadPoolExecutor(1) as pool:
            held = pool.submit(asyncio.run, run()).result()
    finally:
        t.detach(api)
    assert tcp.stored == {63: heat, 64: heat}  # one set packet with both days
    assert s.same_day("heat", [{"time": "06:30", "heat": 68.0}], held["Sched_Heat_Mon"])


@pytest.fixture
def writer(thermostat, monkeypatch):
    """The live connection's write: keeps what is written, answers reads."""
    stored = {}
    calls = []
    keep = {"ok": True}

    def write(api, loop, cloud_id, entries, names):
        calls.append(entries)
        if keep["ok"]:
            stored.update(dict(entries))
        return {
            name: (list(stored[index]) + [255] * 10 if index in stored else None)
            for (index, _), name in zip(entries, names, strict=True)
        }

    def read(api, loop, cloud_id, names):
        values = {}
        for name in names:
            kind = "sensors" if name.startswith("Temp") else name.split("_")[1].lower()
            index = s.day_index(kind, name[-3:].lower())
            values[name] = list(stored[index]) + [255] * 10 if index in stored else None
        return values

    monkeypatch.setattr(cync, "thermostat_write_settings_on_open", write)
    monkeypatch.setattr(cync, "thermostat_settings_on_open", read)
    thermostat_schedule._schedule_cache.clear()
    return SimpleNamespace(calls=calls, stored=stored, keep=keep)


def put(client, csrf, home_id, device_id, kind, days, periods):
    return client.put(
        f"/api/v1/homes/{home_id}/devices/{device_id}/schedule/{kind}",
        json={"days": days, "periods": periods},
        headers=csrf(client),
    )


def test_save_schedule(client, db, owner, csrf, thermostat, writer):
    home, did = owner.home_id, thermostat.id
    heat = [{"time": "06:30", "heat": 68.0}, {"time": "22:00", "heat": 62.0}]
    r = put(client, csrf, home, did, "heat", ["mon", "tue"], heat)
    assert r.status_code == 200, r.text
    (entries,) = writer.calls
    assert [i for i, _ in entries] == [63, 64]
    assert entries[0][1] == s.encode_day("heat", heat)
    week = r.json()["week"]
    assert week["heat"]["mon"] == heat and week["heat"]["wed"] is None
    # The rest is kept: the next write answers from what is known.
    auto = [{"time": "07:00", "heat": 66.0, "cool": 76.0}]
    r = put(client, csrf, home, did, "auto", ["sun"], auto)
    assert r.status_code == 200 and r.json()["week"]["heat"]["tue"] == heat
    assert r.json()["week"]["auto"]["sun"] == auto
    sensors = [{"time": "08:00", "read": "sensor", "pin": PIN}]
    r = put(client, csrf, home, did, "sensors", ["sat"], sensors)
    assert r.status_code == 200
    assert r.json()["week"]["sensors"]["sat"][0]["label"] == "Remote sensor"
    r = put(client, csrf, home, did, "heat", ["mon"], [])  # clear a day
    assert r.status_code == 200 and not r.json()["week"]["heat"]["mon"]
    assert writer.stored[63] == b"\xff"
    db.expire_all()
    saved = (
        db.query(AuditEvent).filter_by(event_type="thermostat_schedule_saved").count()
    )
    assert saved == 4


def test_refused_schedules_write_nothing(client, db, owner, csrf, thermostat, writer):
    home, did = owner.home_id, thermostat.id
    for kind, periods in (
        ("heat", [{"time": "06:30", "heat": 95.0}]),  # above the safety limit
        ("cool", [{"time": "06:30", "cool": 40.0}]),  # below it
        ("auto", [{"time": "06:30", "heat": 74.0, "cool": 72.0}]),  # cool below heat
        ("sensors", [{"time": "06:30", "read": "sensor", "pin": "999999"}]),  # unknown
        (
            "heat",
            [{"time": "08:00", "heat": 68}, {"time": "07:00", "heat": 66}],
        ),  # order
    ):
        r = put(client, csrf, home, did, kind, ["mon"], periods)
        assert r.status_code == 422, (kind, r.text)
    r = put(client, csrf, home, did, "heat", [], [])
    assert r.status_code == 422  # no day
    r = put(client, csrf, home, did, "heat", ["mon"], [{"time": "25:00", "heat": 68}])
    assert r.status_code == 422
    assert writer.calls == []


def test_not_stored_is_reported(client, db, owner, csrf, thermostat, writer):
    writer.keep["ok"] = False  # the thermostat ignores the write
    r = put(
        client,
        csrf,
        owner.home_id,
        thermostat.id,
        "heat",
        ["mon", "wed"],
        [{"time": "06:30", "heat": 68.0}],
    )
    assert r.status_code == 502 and "Mon, Wed" in r.json()["detail"]
    db.expire_all()
    failed = (
        db.query(AuditEvent).filter_by(event_type="thermostat_schedule_failed").count()
    )
    assert failed == 1


def test_schedule_needs_limits_and_a_connection(
    client, db, owner, csrf, thermostat, writer, monkeypatch
):
    from app.models import DeviceSafetyLimits

    db.query(DeviceSafetyLimits).delete()
    db.commit()
    r = put(client, csrf, owner.home_id, thermostat.id, "heat", ["mon"], [])
    assert r.status_code == 409  # limits not configured
    apply_recommended(db, owner.home_id, None, None)
    monkeypatch.setattr(cync_live, "connection", lambda home_id: None)
    r = put(client, csrf, owner.home_id, thermostat.id, "heat", ["mon"], [])
    assert r.status_code == 503
    assert writer.calls == []


def test_ui_edit_a_day(open_page, db, owner, monkeypatch):
    report = t.thermostat_state(t.parse_probe_reply(_thermostat.FULL_REPLY))
    apply_recommended(db, owner.home_id, None, None)
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
    set_integration(db, owner.home_id, "cync", True, None, None)  # controllable
    week = s.week_from_settings(_read.answers())  # heat Tue 06:30 68
    saved = []

    def fake_read(db_, device, refresh=False):
        return {"week": week, "missing": []}

    def fake_write(db_, device, kind, days, periods, bounds):
        saved.append((kind, days, periods, bounds))
        if periods and periods[0].get("heat") == 79.5:
            raise CyncUnavailable(
                502, "the thermostat did not store the schedule for Wed"
            )
        for day in days:
            week[kind][day] = periods
        return {"week": week, "missing": []}

    monkeypatch.setattr("app.routes.thermostat.read_schedule", fake_read)
    monkeypatch.setattr("app.routes.thermostat.write_schedule", fake_write)
    page = open_page()
    ui_login(page, owner)
    card(page, "Hallway").get_by_test_id("thermo-schedule-open").click()
    panel = page.get_by_test_id("schedule-panel")
    panel.get_by_test_id("schedule-edit-tue").click()
    editor = panel.get_by_test_id("sched-editor")
    expect(editor.get_by_test_id("sched-row")).to_have_count(1)
    expect(editor.get_by_test_id("sched-time")).to_have_value("06:30")
    editor.get_by_test_id("sched-heat").fill("70")
    editor.get_by_test_id("sched-add").click()
    expect(editor.get_by_test_id("sched-time").nth(1)).to_have_value("08:30")
    editor.get_by_test_id("sched-time").nth(1).fill("21:00")
    editor.get_by_test_id("sched-heat").nth(1).fill("62")
    editor.get_by_test_id("sched-day-wed").check()
    editor.get_by_test_id("sched-save").click()
    expect(page.get_by_test_id("status")).to_have_attribute("data-kind", "success")
    assert saved[-1][:3] == (
        "heat",
        ["tue", "wed"],
        [{"time": "06:30", "heat": 70.0}, {"time": "21:00", "heat": 62.0}],
    )
    assert saved[-1][3] == (60.0, 80.0)  # the safety limits
    expect(panel.get_by_test_id("schedule-wed")).to_contain_text("9:00 PM → 62 °F")

    # A refused or unconfirmed write keeps the editor open with the reason.
    panel.get_by_test_id("schedule-edit-wed").click()
    editor = panel.get_by_test_id("sched-editor")
    editor.get_by_test_id("sched-heat").first.fill("79.5")
    editor.get_by_test_id("sched-save").click()
    expect(editor.get_by_test_id("sched-error")).to_contain_text("did not store")
    editor.get_by_test_id("sched-cancel").click()
    expect(panel.get_by_test_id("schedule-wed")).to_contain_text("6:30 AM → 70 °F")

    # Sensors: the remote sensor is offered by name.
    panel.get_by_test_id("schedule-tab-sensors").click()
    panel.get_by_test_id("schedule-edit-fri").click()
    editor = panel.get_by_test_id("sched-editor")
    editor.get_by_test_id("sched-add").click()
    editor.get_by_test_id("sched-read").select_option(label="Remote sensor")
    editor.get_by_test_id("sched-save").click()
    expect(panel.get_by_test_id("sched-editor")).to_have_count(0)  # saved and closed
    assert saved[-1][:3] == (
        "sensors",
        ["fri"],
        [{"time": "06:00", "read": "sensor", "pin": PIN}],
    )
