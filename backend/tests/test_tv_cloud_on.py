# ruff: noqa: F811 (fixtures shared with test_samsung)
"""Turning a TV on that does not answer on the network: Samsung's cloud
(SmartThings) as well as the wake-up packet, which often cannot reach it.
Never beside the power key (the TV would come on and go straight off). A
TV not yet linked to SmartThings is linked by name, or as the only TV."""

import json

import pytest

from app import credentials, tv_power, tv_sources
from app.integrations import smartthings
from app.models import Device
from tests.test_samsung import command, ready_tv, secrets_key, tv  # noqa: F401

TOKEN = "abcdef12-3456-7890-abcd-ef1234567890"
MAC = "AA:BB:CC:DD:EE:FF"


class Cloud:
    def __init__(self):
        self.tvs_list = [{"id": "st-1", "name": "[TV] Living room"}]
        self.on = []
        self.fail = None

    def tvs(self, token):
        assert token == TOKEN
        return self.tvs_list

    def switch_on(self, token, device_id):
        if self.fail:
            raise self.fail
        self.on.append(device_id)


@pytest.fixture
def cloud(monkeypatch):
    fake = Cloud()
    monkeypatch.setattr(smartthings, "tvs", fake.tvs)
    monkeypatch.setattr(smartthings, "switch_on", fake.switch_on)
    return fake


def connect(db, home_id):
    credentials.save(
        db, home_id, tv_sources.CREDENTIAL, "SmartThings", {"token": TOKEN}
    )


def setup(client, db, owner, login, csrf, tv, monkeypatch, state=None, **changes):
    device_id = ready_tv(client, csrf, login, owner, tv, **changes)
    connect(db, owner.home_id)
    answer = [state]
    monkeypatch.setattr(tv_power, "power_state", lambda host, protocol: answer[0])
    monkeypatch.setattr(tv_power, "wake", lambda mac, host: tv.wakes.append(mac))

    def on():
        r = command(client, csrf, owner.home_id, device_id, "turn_on")
        assert r.status_code == 200, r.text

    return device_id, answer, on


def linked(db, device_id):
    db.expire_all()
    return json.loads(db.get(Device, device_id).capabilities).get("smartthings_id")


def test_off_tv_gets_the_cloud_and_the_wake_up_packet(
    client, db, owner, login, csrf, tv, secrets_key, cloud, monkeypatch
):
    device_id, _, on = setup(client, db, owner, login, csrf, tv, monkeypatch, mac=MAC)
    on()
    assert cloud.on == ["st-1"] and tv.wakes == [MAC] and tv.keys == []
    assert linked(db, device_id) == "st-1"  # "[TV] Living room" = "Living room TV"


def test_standby_tv_gets_only_the_power_key(
    client, db, owner, login, csrf, tv, secrets_key, cloud, monkeypatch
):
    *_, on = setup(
        client, db, owner, login, csrf, tv, monkeypatch, state="standby", mac=MAC
    )
    on()
    assert cloud.on == [] and [k[3] for k in tv.keys] == [["KEY_POWER"]]


def test_no_mac_the_cloud_instead_of_the_key(
    client, db, owner, login, csrf, tv, secrets_key, cloud, monkeypatch
):
    *_, on = setup(client, db, owner, login, csrf, tv, monkeypatch)
    on()
    assert cloud.on == ["st-1"] and tv.keys == [] and tv.wakes == []


def test_the_only_tv_is_linked_and_two_others_are_not(
    client, db, owner, login, csrf, tv, secrets_key, cloud, monkeypatch
):
    cloud.tvs_list = [{"id": "st-9", "name": "Samsung QN90"}]
    device_id, _, on = setup(client, db, owner, login, csrf, tv, monkeypatch, mac=MAC)
    on()
    assert cloud.on == ["st-9"] and linked(db, device_id) == "st-9"
    tv_sources.link(db, db.get(Device, device_id), None)
    cloud.tvs_list = [{"id": "a", "name": "Bedroom"}, {"id": "b", "name": "TV"}]
    on()
    assert cloud.on == ["st-9"] and linked(db, device_id) is None
    assert tv.wakes == [MAC, MAC]  # the wake-up packet either way


def test_cloud_trouble_still_wakes(
    client, db, owner, login, csrf, tv, secrets_key, cloud, monkeypatch
):
    *_, on = setup(client, db, owner, login, csrf, tv, monkeypatch, mac=MAC)
    cloud.fail = smartthings.SmartThingsError("SmartThings answered 500")
    on()
    assert tv.wakes == [MAC]


def test_without_smartthings_nothing_changes(
    client, db, owner, login, csrf, tv, secrets_key, cloud, monkeypatch
):
    device_id = ready_tv(client, csrf, login, owner, tv, mac=MAC)
    monkeypatch.setattr(tv_power, "power_state", lambda host, protocol: None)
    monkeypatch.setattr(tv_power, "wake", lambda mac, host: tv.wakes.append(mac))
    r = command(client, csrf, owner.home_id, device_id, "turn_on")
    assert r.status_code == 200 and tv.wakes == [MAC] and cloud.on == []
