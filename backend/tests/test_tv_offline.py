"""A TV that does not answer is greyed out like an offline device. It stays
online in the app (one with a MAC address can still be woken), and its
power button stays when it can be."""

import json

from playwright.sync_api import expect

from app import features, lg_home, refresh, tv_power
from app.integrations import lg, samsung
from app.models import Device
from tests import test_samsung as _tv
from tests import test_ui as _ui

tv, secrets_key = _tv.tv, _tv.secrets_key


def stored(db, device_id):
    """The TV's power and whether it answers (its other state aside)."""
    db.expire_all()
    state = json.loads(db.get(Device, device_id).state)
    return {key: state.get(key) for key in ("on", "reachable")}


def test_samsung_refresh_says_whether_the_tv_answers(
    client, db, owner, login, csrf, tv, secrets_key, monkeypatch
):
    device_id = _tv.ready_tv(client, csrf, login, owner, tv)
    power = {"on": False, "state": None}
    monkeypatch.setattr(samsung, "is_on", lambda host, protocol: power["on"])
    monkeypatch.setattr(tv_power, "power_state", lambda host, protocol: power["state"])
    assert refresh.refresh_tvs(db, owner.home_id) == 1
    assert stored(db, device_id) == {"on": False, "reachable": False}
    assert db.get(Device, device_id).online is True  # can still be woken
    power["state"] = "standby"  # 2018+: answers with its screen off
    assert refresh.refresh_tvs(db, owner.home_id) == 1
    assert stored(db, device_id) == {"on": False, "reachable": True}
    assert refresh.refresh_tvs(db, owner.home_id) == 0
    power.update(on=True, state="on")
    assert refresh.refresh_tvs(db, owner.home_id) == 1
    assert stored(db, device_id) == {"on": True, "reachable": True}


def test_lg_refresh_says_whether_the_tv_answers(db, owner, make_device, monkeypatch):
    features.set_integration(db, owner.home_id, lg_home.INTEGRATION, True, None, None)
    device = db.get(Device, make_device(owner.home_id, device_type="tv", name="Den"))
    device.integration, device.capabilities = lg_home.INTEGRATION, '{"paired": true}'
    device.external_id = "192.168.1.70"
    db.commit()
    answer = {"on": False}
    monkeypatch.setattr(lg, "is_on", lambda host: answer["on"])
    assert lg_home.refresh(db, owner.home_id) == 1
    assert stored(db, device.id) == {"on": False, "reachable": False}
    answer["on"] = True
    assert lg_home.refresh(db, owner.home_id) == 1
    assert stored(db, device.id) == {"on": True, "reachable": True}


def test_devices_say_whether_a_tv_can_be_woken(
    client, db, owner, login, csrf, tv, secrets_key
):
    with_mac = _tv.ready_tv(client, csrf, login, owner, tv, mac="AA:BB:CC:DD:EE:FF")
    lamp = _tv.add(client, csrf, owner.home_id, name="Den TV", host="192.168.1.51")
    out = {
        d["id"]: d for d in client.get(f"/api/v1/homes/{owner.home_id}/devices").json()
    }
    assert out[with_mac]["wakeable"] is True
    assert out[lamp.json()["device_id"]]["wakeable"] is False


def test_ui_a_tv_that_does_not_answer_is_greyed_out(
    open_page, new_client, db, owner, make_user, login, csrf, tv, secrets_key
):
    client = new_client()
    wakeable = _tv.ready_tv(client, csrf, login, owner, tv, mac="AA:BB:CC:DD:EE:FF")
    other = _tv.add(client, csrf, owner.home_id, name="Den TV", host="192.168.1.51")
    for device_id in (wakeable, other.json()["device_id"]):
        db.get(Device, device_id).state = json.dumps({"on": True, "reachable": False})
    db.commit()
    page = open_page()
    # Another user: the owner's code was just used by the API login.
    _ui.ui_login(page, make_user(owner.home_id, role="admin"))
    for name, can_wake in (("Living room TV", True), ("Den TV", False)):
        card = _ui.card(page, name)
        expect(card).to_have_class("device-card offline")  # drawn off, dimmed
        expect(card).to_contain_text("TV · offline")
        expect(card.get_by_test_id("tv-remote-open")).to_be_disabled()
        toggle = card.get_by_test_id("power-toggle")
        expect(toggle).to_have_text("Off")
        if can_wake:
            expect(toggle).to_be_enabled()
        else:
            expect(toggle).to_be_disabled()
