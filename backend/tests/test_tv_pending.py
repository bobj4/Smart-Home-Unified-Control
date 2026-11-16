"""A real TV shows "Turning on…" / "Turning off…" until the TV says it is
(or a minute passes); a demo TV changes at once."""

import json

from playwright.sync_api import expect

from app import refresh, tv_pending, tv_power
from app.integrations import samsung
from app.models import Device
from tests import test_samsung as _tv
from tests import test_ui as _ui

tv, secrets_key = _tv.tv, _tv.secrets_key


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


def test_pending_until_seen_or_a_minute(monkeypatch):
    clock = Clock()
    monkeypatch.setattr(tv_pending.time, "monotonic", clock)
    real = Device(id="tv-1", integration="samsung_tv")
    demo = Device(id="tv-2", integration="simulated")
    tv_pending.start(real, "turn_on")
    tv_pending.start(demo, "turn_on")
    tv_pending.start(Device(id="tv-3", integration="samsung_tv"), "volume_up")
    assert tv_pending.pending("tv-1") == "on"
    assert tv_pending.pending("tv-2") is None and tv_pending.pending("tv-3") is None
    tv_pending.seen("tv-1", False)  # still off: keep waiting
    assert tv_pending.pending("tv-1") == "on"
    tv_pending.seen("tv-1", True)
    assert tv_pending.pending("tv-1") is None
    tv_pending.start(real, "turn_off")
    clock.now += tv_pending.PENDING_SECONDS + 1  # never said: its real state shows
    assert tv_pending.pending("tv-1") is None


def test_reading_the_devices_asks_a_pending_tv(
    client, db, owner, login, csrf, tv, secrets_key, monkeypatch
):
    device_id = _tv.ready_tv(client, csrf, login, owner, tv)
    answer = {"on": False}
    asked = []

    def is_on(host, protocol):
        asked.append(host)
        return answer["on"]

    monkeypatch.setattr(samsung, "is_on", is_on)
    monkeypatch.setattr(tv_power, "power_state", lambda host, protocol: None)
    monkeypatch.setattr(tv_pending, "CHECK_SECONDS", 0)
    r = _tv.command(client, csrf, owner.home_id, device_id, "turn_off")
    assert r.json()["pending"] == "off"
    url = f"/api/v1/homes/{owner.home_id}/devices"

    def mine():
        return next(d for d in client.get(url).json() if d["id"] == device_id)

    answer["on"] = True  # still on
    assert mine()["pending"] == "off" and asked
    answer["on"] = False
    out = mine()
    assert out["pending"] is None and out["state"]["on"] is False
    # A refresh that reads the TV as wanted ends the wait too.
    _tv.command(client, csrf, owner.home_id, device_id, "turn_on")
    monkeypatch.setattr(tv_pending, "CHECK_SECONDS", 3600)  # no asking on reads
    assert mine()["pending"] == "on"
    answer["on"] = True
    refresh.refresh_tvs(db, owner.home_id)
    assert mine()["pending"] is None


def test_a_demo_tv_is_never_pending(client, owner, login, csrf, make_device):
    tv_id = make_device(owner.home_id, device_type="tv", name="Demo TV")
    assert login(client, owner).status_code == 200
    r = _tv.command(client, csrf, owner.home_id, tv_id, "turn_on")
    assert "pending" not in r.json() and r.json()["state"]["on"] is True


def test_ui_turning_on_until_the_tv_says(
    open_page,
    new_client,
    db,
    owner,
    make_user,
    login,
    csrf,
    tv,
    secrets_key,
    monkeypatch,
):
    device_id = _tv.ready_tv(new_client(), csrf, login, owner, tv)
    db.get(Device, device_id).state = json.dumps({"on": False, "reachable": True})
    db.commit()
    tv_pending._pending.pop(device_id, None)
    answer = {"on": False}
    monkeypatch.setattr(samsung, "is_on", lambda host, protocol: answer["on"])
    monkeypatch.setattr(tv_pending, "CHECK_SECONDS", 0)
    page = open_page()
    # Another user: the owner's code was just used by the API login.
    _ui.ui_login(page, make_user(owner.home_id, role="admin"))
    toggle = _ui.card(page, "Living room TV").get_by_test_id("power-toggle")
    expect(toggle).to_have_text("Off")
    toggle.click()
    expect(toggle).to_have_text("Turning on…")
    expect(toggle).to_be_disabled()
    answer["on"] = True  # the TV comes on: the next refresh of the page shows it
    expect(toggle).to_have_text("On", timeout=12000)
    expect(toggle).to_be_enabled()
    # The remote shows the same wait.
    answer["on"] = True
    _ui.card(page, "Living room TV").get_by_test_id("tv-remote-open").click()
    remote = page.get_by_test_id("tv-remote")
    remote.get_by_test_id("remote-power").click()
    expect(remote.get_by_test_id("remote-power")).to_have_text("Turning off…")
    answer["on"] = False
    expect(remote.get_by_test_id("remote-power")).to_have_text("Power", timeout=12000)
