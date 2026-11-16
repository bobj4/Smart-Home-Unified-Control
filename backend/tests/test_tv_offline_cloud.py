# ruff: noqa: F811 (fixtures shared with test_samsung)
"""Only a TV that cannot be reached any way is greyed out: one that does
not answer on the network but is online in SmartThings (which can turn it
on) shows as off, not offline. SmartThings is asked at most every
CLOUD_SECONDS per TV, and only while the TV does not answer."""

import json

from app import credentials, refresh, tv_power, tv_sources
from app.integrations import samsung, smartthings
from app.models import Device
from tests.test_samsung import ready_tv, secrets_key, tv  # noqa: F401

TOKEN = "abcdef12-3456-7890-abcd-ef1234567890"


def stored(db, device_id):
    db.expire_all()
    state = json.loads(db.get(Device, device_id).state)
    return {key: state.get(key) for key in ("on", "reachable")}


def test_online_in_smartthings_is_not_offline(
    client, db, owner, login, csrf, tv, secrets_key, monkeypatch
):
    device_id = ready_tv(client, csrf, login, owner, tv)
    credentials.save(
        db, owner.home_id, tv_sources.CREDENTIAL, "SmartThings", {"token": TOKEN}
    )
    lan = {"on": False, "state": None}
    monkeypatch.setattr(samsung, "is_on", lambda host, protocol: lan["on"])
    monkeypatch.setattr(tv_power, "power_state", lambda host, protocol: lan["state"])
    cloud = {"online": True}
    asked = []
    monkeypatch.setattr(
        smartthings, "tvs", lambda token: [{"id": "st-1", "name": "[TV] Living room"}]
    )

    def online(token, st_id):
        asked.append(st_id)
        return cloud["online"]

    monkeypatch.setattr(smartthings, "online", online)
    clock = [1000.0]
    real = tv_sources.cloud_online
    monkeypatch.setattr(
        tv_sources, "cloud_online", lambda db, device: real(db, device, clock[0])
    )
    refresh.refresh_tvs(db, owner.home_id)
    assert stored(db, device_id) == {"on": False, "reachable": True}
    assert asked == ["st-1"]
    # Asked again only after CLOUD_SECONDS.
    cloud["online"] = False
    refresh.refresh_tvs(db, owner.home_id)
    assert stored(db, device_id)["reachable"] is True and asked == ["st-1"]
    clock[0] += tv_sources.CLOUD_SECONDS
    refresh.refresh_tvs(db, owner.home_id)
    assert stored(db, device_id) == {"on": False, "reachable": False}  # truly gone
    # Answering on the network: SmartThings is not asked.
    lan.update(on=True, state="on")
    clock[0] += tv_sources.CLOUD_SECONDS
    refresh.refresh_tvs(db, owner.home_id)
    assert stored(db, device_id) == {"on": True, "reachable": True}
    assert len(asked) == 2


def test_smartthings_trouble_or_none_means_offline(
    client, db, owner, login, csrf, tv, secrets_key, monkeypatch
):
    device_id = ready_tv(client, csrf, login, owner, tv)
    monkeypatch.setattr(samsung, "is_on", lambda host, protocol: False)
    monkeypatch.setattr(tv_power, "power_state", lambda host, protocol: None)
    refresh.refresh_tvs(db, owner.home_id)  # not connected
    assert stored(db, device_id)["reachable"] is False
    credentials.save(
        db, owner.home_id, tv_sources.CREDENTIAL, "SmartThings", {"token": TOKEN}
    )

    def broken(token):
        raise smartthings.SmartThingsError("SmartThings answered 500")

    monkeypatch.setattr(smartthings, "tvs", broken)
    device = db.get(Device, device_id)
    assert tv_sources.cloud_online(db, device, now=5000.0) is False
