"""A Cync thermostat's History: readings kept as its state comes in, every
few minutes and on each change, and run hours worked out from them."""

import json
from datetime import timedelta

from playwright.sync_api import expect

from app import thermostat_history
from app.models import Device, ThermostatReading, utcnow
from tests import test_ui as _ui


def state(status, temp=68.0, heat=68.0):
    return {
        "status": status,
        "mode": "heat",
        "current_temperature": temp,
        "heat_setpoint": heat,
        "cool_setpoint": None,
        "humidity": 44,
    }


def test_readings_every_few_minutes_and_on_changes(db, owner, make_device, monkeypatch):
    hall = db.get(
        Device, make_device(owner.home_id, device_type="thermostat", name="Hall")
    )
    clock = [1000.0]
    monkeypatch.setattr(thermostat_history.time, "monotonic", lambda: clock[0])
    thermostat_history._last.clear()
    assert thermostat_history.record(db, hall, state("idle"))
    clock[0] += 10
    assert not thermostat_history.record(db, hall, state("idle"))  # too soon
    clock[0] += 25
    assert thermostat_history.record(db, hall, state("heating"))  # a change
    clock[0] += 60
    assert not thermostat_history.record(db, hall, state("heating"))
    clock[0] += 300
    assert thermostat_history.record(db, hall, state("heating", temp=68.5))
    db.commit()
    assert db.query(ThermostatReading).filter_by(device_id=hall.id).count() == 3


def test_history_and_run_hours(client, db, owner, login, make_device):
    hall_id = make_device(owner.home_id, device_type="thermostat", name="Hall")
    now = utcnow()
    # A reading every 5 minutes: heating for 20 minutes, cooling for 10.
    timeline = [(60, "idle"), (55, "idle"), (50, "heating"), (45, "heating")]
    timeline += [(40, "heating"), (35, "heating"), (30, "idle"), (25, "idle")]
    timeline += [(20, "cooling"), (15, "cooling"), (10, "idle")]
    for minutes, status in timeline:
        db.add(
            ThermostatReading(
                device_id=hall_id,
                at=now - timedelta(minutes=minutes),
                temperature=68.0,
                heat_setpoint=68.0,
                status=status,
            )
        )
    # A gap longer than 15 minutes counts as missing, not running.
    db.add(
        ThermostatReading(
            device_id=hall_id, at=now - timedelta(hours=5), status="heating"
        )
    )
    db.add(
        ThermostatReading(device_id=hall_id, at=now - timedelta(hours=3), status="idle")
    )
    db.commit()
    assert login(client, owner).status_code == 200
    url = f"/api/v1/homes/{owner.home_id}/devices/{hall_id}/history"
    day = client.get(url).json()
    assert len(day["points"]) == 13 and day["since"]
    total = {k: sum(d[k] for d in day["run_hours"]) for k in ("heating", "cooling")}
    # 20 min heating + 15 min (the capped gap); 10 min cooling.
    assert round(total["heating"] * 60) == 35 and round(total["cooling"] * 60) == 10
    week = client.get(f"{url}?days=7").json()
    assert len(week["points"]) <= 4  # hourly
    assert client.get(f"{url}?days=5").status_code == 422
    lamp = make_device(owner.home_id, name="Lamp")
    assert (
        client.get(f"/api/v1/homes/{owner.home_id}/devices/{lamp}/history").status_code
        == 404
    )


def test_ui_history_button(open_page, db, owner, make_device):
    hall = make_device(owner.home_id, device_type="thermostat", name="Hallway")
    device = db.get(Device, hall)
    device.integration = "cync"
    device.state = json.dumps({**state("heating"), "filter_hours": 984})
    db.add(
        ThermostatReading(
            device_id=hall,
            at=utcnow() - timedelta(minutes=30),
            temperature=67.5,
            heat_setpoint=68.0,
            status="heating",
        )
    )
    db.add(
        ThermostatReading(
            device_id=hall,
            at=utcnow() - timedelta(minutes=5),
            temperature=68.0,
            heat_setpoint=68.0,
            status="idle",
        )
    )
    db.commit()
    page = open_page()
    _ui.ui_login(page, owner)
    tile = _ui.card(page, "Hallway")
    expect(tile.get_by_test_id("thermo-info-open")).to_have_count(0)
    tile.get_by_test_id("thermo-history-open").click()
    panel = page.get_by_test_id("history-panel")
    expect(panel.get_by_test_id("history-chart")).to_be_visible()
    expect(panel.get_by_test_id("history-run")).to_contain_text(
        "heating 15 min"
    )  # 25 min apart: capped
    panel.get_by_test_id("history-range-7").click()
    expect(panel.get_by_test_id("history-range-7")).to_have_attribute(
        "aria-pressed", "true"
    )
    expect(panel.get_by_test_id("history-chart")).to_be_visible()
    panel.get_by_test_id("history-close").click()
    expect(panel).to_have_count(0)
    # Its Info is in Settings, below daylight saving time.
    tile.get_by_test_id("thermo-settings-open").click()
    info = page.get_by_test_id("thermo-settings-panel").get_by_test_id(
        "thermo-settings-info"
    )
    expect(info).to_contain_text("984 h")
