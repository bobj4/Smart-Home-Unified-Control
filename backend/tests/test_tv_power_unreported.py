"""A TV that says "on" even when turned off (a 2020 TU7000, for one): once
the app has turned it off and it still says "on" after LEARN_SECONDS, its
on/off follows the app's own power button. The same key wakes it."""

import json

from app import refresh, tv_pending, tv_power
from app.integrations import samsung
from app.models import Device
from tests import test_samsung as _tv

tv, secrets_key = _tv.tv, _tv.secrets_key


def test_a_tv_that_says_on_while_off(
    client,
    db,
    owner,
    login,
    csrf,
    tv,
    secrets_key,
    monkeypatch,  # noqa: F811
):
    device_id = _tv.ready_tv(client, csrf, login, owner, tv)
    home = owner.home_id
    says = ["on"]  # what the TU7000 answers, on or off
    monkeypatch.setattr(tv_power, "power_state", lambda host, protocol: says[0])
    monkeypatch.setattr(samsung, "is_on", lambda host, protocol: says[0] == "on")
    clock = [1000.0]
    monkeypatch.setattr(tv_pending.time, "monotonic", lambda: clock[0])
    tv_pending._pending.pop(device_id, None)

    def power(command):
        r = _tv.command(client, csrf, home, device_id, command)
        assert r.status_code == 200, r.text
        return r.json()["state"]["on"]

    def shown():
        db.expire_all()
        device = db.get(Device, device_id)
        return json.loads(device.state)["on"], tv_power.unreported(device)

    assert power("turn_off") is False and len(tv.keys) == 1  # the key: it goes off
    refresh.refresh_tvs(db, home)
    assert shown() == (True, False)  # it says "on": not learned yet, waiting
    clock[0] += tv_power.LEARN_SECONDS
    refresh.refresh_tvs(db, home)
    assert shown() == (False, True)  # still "on" after a while: noted, shown off
    refresh.refresh_tvs(db, home)
    assert shown() == (False, True)  # and stays off though it says "on"
    shown_device = {
        d["id"]: d for d in client.get(f"/api/v1/homes/{home}/devices").json()
    }[device_id]
    assert shown_device["online"] is True and shown_device["state"]["reachable"] is True
    # On: it says "on", but the app left it off, so the key (it wakes).
    assert power("turn_on") is True and len(tv.keys) == 2
    refresh.refresh_tvs(db, home)
    assert shown() == (True, True)
    assert power("turn_off") is False and len(tv.keys) == 3
    assert tv_pending.pending(device_id) is None  # nothing to wait for: shown off
    refresh.refresh_tvs(db, home)
    assert shown() == (False, True)
    # Not answering at all: off. Saying "standby" after all: it reports again.
    says[0] = None
    refresh.refresh_tvs(db, home)
    assert shown()[0] is False
    says[0] = "standby"
    refresh.refresh_tvs(db, home)
    assert shown() == (False, False)


def test_a_tv_that_reports_off_is_never_noted(
    client,
    db,
    owner,
    login,
    csrf,
    tv,
    secrets_key,
    monkeypatch,  # noqa: F811
):
    device_id = _tv.ready_tv(client, csrf, login, owner, tv)
    says = ["on"]
    monkeypatch.setattr(tv_power, "power_state", lambda host, protocol: says[0])
    monkeypatch.setattr(samsung, "is_on", lambda host, protocol: says[0] == "on")
    clock = [1000.0]
    monkeypatch.setattr(tv_pending.time, "monotonic", lambda: clock[0])
    tv_pending._pending.pop(device_id, None)
    r = _tv.command(client, csrf, owner.home_id, device_id, "turn_off")
    assert r.status_code == 200
    says[0] = "standby"  # the 2024 DU7200: says so within seconds
    clock[0] += tv_power.LEARN_SECONDS * 2
    refresh.refresh_tvs(db, owner.home_id)
    db.expire_all()
    device = db.get(Device, device_id)
    assert json.loads(device.state)["on"] is False
    assert tv_power.unreported(device) is False
