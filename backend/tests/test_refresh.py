"""Live state: background refresh of real devices, and the page re-reading.

Written by the reviewer (live refresh phase). Do not edit, skip, mark or
delete these tests. If one looks wrong, stop and report the test name and its
full failure output instead of changing it.
"""

import json

from playwright.sync_api import expect

from app import refresh
from app.integrations import samsung
from app.models import Device, Home
from tests import test_rheem as _rheem
from tests import test_samsung as _tv
from tests import test_ui as _ui

tv, econet, secrets_key = _tv.tv, _rheem.econet, _rheem.secrets_key
card, ui_login = _ui.card, _ui.ui_login


def stored(db, device_id):
    db.expire_all()
    return json.loads(db.get(Device, device_id).state)


def test_tv_power_is_read_back(
    client, db, owner, login, csrf, tv, secrets_key, monkeypatch
):
    device_id = _tv.ready_tv(client, csrf, login, owner, tv)
    probes = []
    power = {"on": False}

    def is_on(host, protocol):
        probes.append((host, protocol))
        return power["on"]

    monkeypatch.setattr(samsung, "is_on", is_on)
    assert stored(db, device_id)["on"] is True
    assert refresh.refresh_tvs(db, owner.home_id) == 1
    assert stored(db, device_id)["on"] is False
    assert probes == [(_tv.HOST, "tizen")]
    assert refresh.refresh_tvs(db, owner.home_id) == 0  # nothing changed
    power["on"] = True
    assert refresh.refresh_tvs(db, owner.home_id) == 1
    assert stored(db, device_id)["on"] is True
    assert db.get(Device, device_id).online is True  # an off TV can still be woken


def test_tv_refresh_skips_unpaired_and_disabled(
    client, db, owner, login, csrf, tv, secrets_key, monkeypatch
):
    assert login(client, owner).status_code == 200
    _tv.turn_on(client, csrf, owner.home_id)
    _tv.add(client, csrf, owner.home_id)  # never paired
    calls = []
    monkeypatch.setattr(samsung, "is_on", lambda *a: calls.append(a) or True)
    assert refresh.refresh_tvs(db, owner.home_id) == 0
    _tv.turn_on(client, csrf, owner.home_id, enabled=False)
    assert refresh.refresh_tvs(db, owner.home_id) == 0
    assert calls == []


def test_rheem_is_read_at_most_every_five_minutes(
    client, db, owner, login, csrf, econet, secrets_key
):
    refresh._rheem_read_at.clear()
    _rheem.ready(client, csrf, login, owner)
    assert refresh.refresh_rheem(db, owner.home_id, now=0) is False  # no heaters yet
    assert _rheem.sync(client, csrf, owner.home_id).status_code == 200
    econet.heaters = [_rheem.heater(set_point=125)]
    assert refresh.refresh_rheem(db, owner.home_id, now=1000) is True
    (device,) = _rheem.rheem_devices(db, owner.home_id)
    assert json.loads(device.state)["target_temperature"] == 125
    logins = len(econet.logins)
    assert refresh.refresh_rheem(db, owner.home_id, now=1000 + 299) is False
    assert len(econet.logins) == logins
    assert refresh.refresh_rheem(db, owner.home_id, now=1000 + 300) is True


def test_rheem_refresh_failure_is_contained(
    client, db, owner, login, csrf, econet, secrets_key
):
    refresh._rheem_read_at.clear()
    _rheem.ready(client, csrf, login, owner)
    assert _rheem.sync(client, csrf, owner.home_id).status_code == 200
    econet.fail = _rheem.RheemError("EcoNet is busy (HTTP 429)")
    assert refresh.refresh_rheem(db, owner.home_id, now=5000) is False
    (device,) = _rheem.rheem_devices(db, owner.home_id)
    assert device.online is True  # nothing was changed


def test_refresh_all_keeps_going_after_a_broken_home(db, owner, monkeypatch):
    seen = []

    def broken(db_, home_id):
        seen.append(home_id)
        raise RuntimeError("boom")

    monkeypatch.setattr(refresh, "refresh_tvs", broken)
    monkeypatch.setattr(refresh, "refresh_rheem", broken)
    refresh.refresh_all(db)
    homes = db.query(Home).count()
    assert len(seen) == 2 * homes


def test_is_on_reads_tizen_power_state(monkeypatch):
    class Reply:
        def __init__(self, body):
            self.body = body

        def json(self):
            return self.body

    replies = {
        "a": Reply({"device": {"PowerState": "on"}}),
        "b": Reply({"device": {"PowerState": "standby"}}),
        "c": Reply({"device": {}}),  # older Tizen: answering means on
    }

    def get(url, timeout):
        assert timeout <= 3
        host = url.split("//")[1].split(":")[0]
        if host not in replies:
            raise samsung.requests.ConnectionError()
        return replies[host]

    monkeypatch.setattr(samsung.requests, "get", get)
    assert samsung.is_on("a", "tizen") is True
    assert samsung.is_on("b", "tizen") is False
    assert samsung.is_on("c", "tizen") is True
    assert samsung.is_on("d", "tizen") is False


# ------------------------------------------------------------ browser


def test_ui_devices_page_shows_changes_without_reload(
    open_page, db, owner, make_device
):
    lamp = make_device(owner.home_id, name="Hall lamp")
    page = open_page()
    ui_login(page, owner)
    toggle = card(page, "Hall lamp").get_by_test_id("power-toggle")
    expect(toggle).to_have_attribute("aria-pressed", "false")
    page.evaluate(
        "() => { window.smartHomeApp.refreshMs = 300; window.smartHomeApp.scheduleLive(); }"
    )
    device = db.get(Device, lamp)
    device.state = json.dumps({"on": True, "brightness": 60})
    db.commit()
    expect(card(page, "Hall lamp").get_by_test_id("power-toggle")).to_have_attribute(
        "aria-pressed", "true"
    )
    device.online = False
    db.commit()
    expect(card(page, "Hall lamp")).to_have_attribute("data-online", "false")


def test_ui_live_refresh_waits_while_the_light_window_is_open(
    open_page, db, owner, make_device
):
    lamp = make_device(owner.home_id, name="Desk lamp")
    page = open_page()
    ui_login(page, owner)
    card(page, "Desk lamp").get_by_test_id("light-settings-open").click()
    expect(page.get_by_test_id("light-panel")).to_be_visible()
    page.evaluate(
        "() => { window.smartHomeApp.refreshMs = 200; window.smartHomeApp.scheduleLive(); }"
    )
    device = db.get(Device, lamp)
    device.name = "Renamed lamp"
    db.commit()
    page.wait_for_timeout(800)
    expect(page.get_by_test_id("light-panel")).to_be_visible()
    expect(page.get_by_text("Renamed lamp")).to_have_count(0)
    page.get_by_test_id("light-close").click()
    expect(card(page, "Renamed lamp")).to_be_visible()
