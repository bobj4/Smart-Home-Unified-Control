"""Cync: a bulb whose wall switch is turned off (or on again) shows offline
(or back) within seconds, from the live connection's reports; wall switches
show as "Light Switch"."""

import json
from types import SimpleNamespace

from playwright.sync_api import expect
from pycync.devices.capabilities import CyncCapability
from pycync.devices.device_types import DeviceType

from app import cync_home, cync_live
from app.integrations import cync
from app.models import Device
from tests import test_cync
from tests import test_ui as _ui
from tests.test_cync import device_id, info, ready

fake, secrets_key = test_cync.fake, test_cync.secrets_key  # its fixtures


def bulb(unique_id, online, device_type=DeviceType.LIGHT):
    return SimpleNamespace(
        unique_id=unique_id, is_online=online, device_type=device_type
    )


def test_reachable_report_skips_thermostats():
    devices = [
        bulb("77-1", True),
        bulb("77-2", False),
        bulb("77-3", True, DeviceType.THERMOSTAT),
        SimpleNamespace(unique_id="77-4", is_online=None, device_type=None),
    ]
    assert cync._reachable(devices) == {
        "77-1": {"online": True},
        "77-2": {"online": False},
    }


def test_a_state_report_says_whether_it_is_reachable():
    plug = SimpleNamespace(is_on=True, is_online=False, capabilities=set())
    assert cync._state(plug) == {"on": True, "online": False}


def test_reports_turn_devices_offline_and_back(
    client,
    db,
    owner,
    login,
    csrf,
    fake,
    secrets_key,
    monkeypatch,  # noqa: F811
):
    ready(client, csrf, login, owner)
    lamp = device_id(db, owner.home_id, "77-1")
    before = json.loads(db.get(Device, lamp).state or "{}")
    # Power off at the wall switch: the full report no longer lists it.
    assert cync_home.store_states(db, owner.home_id, {"77-1": {"online": False}}) == 1
    db.expire_all()
    assert db.get(Device, lamp).online is False
    assert json.loads(db.get(Device, lamp).state or "{}") == before  # kept
    shown = {
        d["id"]: d for d in client.get(f"/api/v1/homes/{owner.home_id}/devices").json()
    }
    assert shown[lamp]["online"] is False
    # On again: reachable, with its state.
    cync_home.store_states(db, owner.home_id, {"77-1": {"on": True, "online": True}})
    db.expire_all()
    assert db.get(Device, lamp).online is True
    assert json.loads(db.get(Device, lamp).state)["on"] is True
    # The account's list lags: a sync keeps what the live connection said.
    fake.devices[0] = info(online=False)
    monkeypatch.setattr(cync_live, "connection", lambda home_id: (object(), None))
    monkeypatch.setattr(cync_home, "_import_groups", lambda *a: None)
    cync_home.sync(db, owner.home_id)
    db.expire_all()
    assert db.get(Device, lamp).online is True
    monkeypatch.setattr(cync_live, "connection", lambda home_id: None)
    cync_home.sync(db, owner.home_id)  # no live connection: the list is all
    db.expire_all()
    assert db.get(Device, lamp).online is False


def test_wall_switches_are_light_switches(
    client,
    db,
    owner,
    login,
    csrf,
    fake,
    secrets_key,
    open_page,  # noqa: F811
):
    switch = SimpleNamespace(
        unique_id="77-9",
        name="Hall switch",
        is_online=True,
        mac="AABBCCDDEEFF",
        device_type=DeviceType.SWITCH,
        capabilities={CyncCapability.ON_OFF},
        device_id=9,
    )
    assert cync._info(switch).switch is True
    fake.devices.append(cync._info(switch))
    ready(client, csrf, login, owner)
    hall = device_id(db, owner.home_id, "77-9")
    assert json.loads(db.get(Device, hall).capabilities)["switch"] is True
    shown = {
        d["id"]: d for d in client.get(f"/api/v1/homes/{owner.home_id}/devices").json()
    }
    assert shown[hall]["switch"] is True and shown[hall]["type"] == "plug"
    assert shown[device_id(db, owner.home_id, "77-2")]["switch"] is False


def test_ui_light_switch_label(open_page, db, owner, make_device):
    hall = db.get(
        Device, make_device(owner.home_id, device_type="plug", name="Hall switch")
    )
    hall.integration, hall.capabilities = "cync", json.dumps({"switch": True})
    make_device(owner.home_id, device_type="plug", name="Fan plug")
    db.commit()
    hall = hall.id
    page = open_page()
    _ui.ui_login(page, owner)
    expect(_ui.card(page, "Hall switch")).to_contain_text("Light Switch")
    panel = _ui.go_settings(page, "devices")
    row = panel.locator(f'[data-testid="device-row"][data-device-id="{hall}"]')
    expect(row.locator(".device-kind")).to_contain_text("Light Switch")
    panel.get_by_test_id("device-filter").select_option("switch")
    expect(panel.locator('[data-testid="device-row"]:visible')).to_have_count(1)
    panel.get_by_test_id("device-search").fill("light switch")
    expect(row).to_be_visible()
