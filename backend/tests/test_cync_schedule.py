"""Cync thermostat schedule format (from the Cync app 6.24) and the schedule
read request in the probe script. Written by the reviewer. Do not edit, skip,
mark or delete these tests. Nothing talks to Cync."""

import importlib.util
import json
import struct
from pathlib import Path

import pytest

from app.integrations import cync_schedule as s


def probe_script():
    path = (
        Path(__file__).resolve().parent.parent / "scripts" / "cync_thermostat_probe.py"
    )
    spec = importlib.util.spec_from_file_location("probe", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_indices_and_names_match_the_app():
    assert [s.schedule_index("heat", d) for d in ("mon", "sun")] == [63, 69]
    assert [s.schedule_index("cool", d) for d in ("mon", "sun")] == [70, 76]
    assert [s.schedule_index("auto", d) for d in ("mon", "sun")] == [77, 83]
    assert [s.sensor_index(d) for d in ("mon", "sun")] == [37, 43]
    assert s.schedule_name("heat", "mon") == "Sched_Heat_Mon"
    assert s.schedule_name("auto", "sun") == "Sched_Auto_Sun"
    assert s.sensor_name("wed") == "Temp_Read_Schd_Wed"


def test_heat_day_round_trip():
    periods = [
        {"time": "06:30", "heat": 68.0},
        {"time": "08:00", "heat": 62.5},
        {"time": "22:15", "heat": 65.0},
    ]
    raw = s.encode_schedule("heat", periods)
    # hour, minute, unit (0 = F), temperature x100
    assert raw[:5] == bytes([6, 30, 0]) + struct.pack(">H", 6800)
    assert s.parse_schedule("heat", raw) == periods


def test_auto_day_and_celsius():
    periods = [{"time": "07:00", "heat": 68.0, "cool": 75.2}]
    raw = s.encode_schedule("auto", periods, unit="C")
    assert raw == bytes([7, 0, 1]) + struct.pack(">HH", 2000, 2400)
    assert s.parse_schedule("auto", raw) == periods


def test_empty_day_and_bad_input():
    assert s.encode_schedule("cool", []) == b"\xff"
    assert s.parse_schedule("cool", b"\xff") == []
    assert s.parse_schedule("cool", b"") == []
    with pytest.raises(s.ScheduleError):
        s.encode_schedule(
            "heat", [{"time": "08:00", "heat": 68}, {"time": "07:00", "heat": 66}]
        )
    with pytest.raises(s.ScheduleError):
        s.encode_schedule("heat", [{"time": "25:00", "heat": 68}])
    with pytest.raises(s.ScheduleError):
        s.encode_schedule("heat", [{"time": "08:00", "heat": "warm"}])
    with pytest.raises(s.ScheduleError):
        s.parse_schedule("heat", bytes([30, 0, 0, 0, 0]))


def test_sensor_schedule():
    sensor = bytes.fromhex("01020304050607")
    raw = (
        bytes([6, 0, 0])
        + bytes(7)
        + bytes([9, 0, 1])
        + sensor
        + bytes([18, 30, 2])
        + bytes(7)
    )
    assert s.parse_sensor_schedule(raw) == [
        {"time": "06:00", "read": "thermostat", "sensor": None, "pin": None},
        {"time": "09:00", "read": "sensor", "sensor": sensor.hex(), "pin": None},
        {"time": "18:30", "read": "all", "sensor": None, "pin": None},
    ]
    assert s.parse_sensor_schedule(b"\xff") == []


def test_probe_asks_for_every_schedule_and_decodes_replies():
    probe = probe_script()
    names = probe.schedule_requests()
    assert len(names) == 28 and names[0] == "Sched_Heat_Mon"
    assert names[-1] == "Temp_Read_Schd_Sun"
    heat = s.encode_schedule("heat", [{"time": "06:30", "heat": 68.0}])
    reply = json.dumps({"Sched_Heat_Mon": heat.hex()}).encode()
    entries = bytes([84]) + struct.pack(">H", 0x9000 | len(reply)) + reply
    entries += bytes([63]) + struct.pack(">H", 0xA000 | len(heat)) + heat
    lines = probe.decode_schedules(entries)
    assert any("setting Sched_Heat_Mon" in line for line in lines)
    decoded = [line for line in lines if '"heat": 68.0' in line]
    assert len(decoded) == 2  # from the ReadSetting reply and from point 63
    ack = struct.pack(">IHB", 556336025, 100, 0)
    assert any(
        "set reply" in line and "code 0" in line
        for line in probe.describe(3, True, ack)
    )


def test_reply_values_padding_and_pins():
    assert s.setting_bytes(None) is None
    assert s.setting_bytes([1, 2, 255]) == b"\x01\x02\xff"
    assert s.setting_bytes([1, 300]) is None
    assert s.setting_bytes("0aff") == b"\x0a\xff"
    heat = s.encode_schedule("heat", [{"time": "06:30", "heat": 68.0}])
    assert s.parse_schedule("heat", heat + b"\xff" * 20) == [
        {"time": "06:30", "heat": 68.0}
    ]
    assert s.sensor_pin(bytes([1]) + b"024944") == "024944"
    assert s.sensor_pin(bytes(7)) is None
