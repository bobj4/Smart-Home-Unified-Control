"""2014-2015 Samsung TVs (H and J series): PIN pairing, encrypted keys.

Written by the reviewer (encrypted TV phase). Do not edit, skip, mark or
delete these tests. If one looks wrong, stop and report the test name and its
full failure output instead of changing it. Nothing here talks to a TV.
"""

import json

import pytest
from playwright.sync_api import expect

from app.integrations import samsung
from app.models import AuditEvent, Device, IntegrationCredential
from tests import test_samsung as _tv
from tests import test_ui as _ui
from tests import test_ui_tv_security as _tvui

tv, secrets_key = _tv.tv, _tv.secrets_key
card, go_settings, ui_login = _ui.card, _ui.go_settings, _ui.ui_login
HOST = "192.168.1.70"
PIN = "4821"
TOKEN = "00112233445566778899aabbccddeeff:7"


class FakePin:
    def __init__(self):
        self.shown = []
        self.tried = []
        self.fail = None

    def start(self, host):
        if self.fail:
            error, self.fail = self.fail, None
            raise error
        self.shown.append(host)

    def finish(self, host, pin):
        self.tried.append((host, pin))
        if pin != PIN:
            raise samsung.TvDenied("the TV did not accept that PIN")
        return TOKEN


@pytest.fixture
def pin_tv(monkeypatch, tv):
    fake = FakePin()
    monkeypatch.setattr(samsung, "start_pin_pairing", fake.start)
    monkeypatch.setattr(samsung, "finish_pin_pairing", fake.finish)
    return fake


def url(home_id, suffix):
    return f"/api/v1/homes/{home_id}/integrations/samsung_tv/tvs{suffix}"


def add_encrypted(client, csrf, login, owner):
    assert login(client, owner).status_code == 200
    _tv.turn_on(client, csrf, owner.home_id)
    r = _tv.add(client, csrf, owner.home_id, host=HOST, protocol="encrypted")
    assert r.status_code == 201, r.text
    assert r.json()["protocol"] == "encrypted"
    return r.json()["device_id"]


def send_pin(client, csrf, home_id, device_id, pin):
    return client.post(
        url(home_id, f"/{device_id}/pin"), json={"pin": pin}, headers=csrf(client)
    )


def test_pin_pairing(client, db, owner, login, csrf, tv, pin_tv, secrets_key):
    device_id = add_encrypted(client, csrf, login, owner)
    home = owner.home_id
    r = _tv.pair(client, csrf, home, device_id)
    assert r.status_code == 200, r.text
    assert (r.json()["pin_required"], r.json()["paired"]) == (True, False)
    assert pin_tv.shown == [HOST]
    assert tv.paired == []  # the Allow-prompt pairing is not used

    for bad in ("12345", "12a4", "", 4821):
        assert send_pin(client, csrf, home, device_id, bad).status_code == 422
    r = send_pin(client, csrf, home, device_id, "0000")
    assert r.status_code == 409
    assert "PIN" in r.json()["detail"]
    assert _tv.pair(client, csrf, home, device_id).json()["paired"] is False

    r = send_pin(client, csrf, home, device_id, PIN)
    assert r.status_code == 200, r.text
    assert r.json()["paired"] is True
    stored = db.query(IntegrationCredential).all()
    assert len(stored) == 1
    assert TOKEN not in stored[0].secret  # kept encrypted
    events = [e.event_type for e in db.query(AuditEvent).all()]
    assert "tv_pin_shown" in events and "tv_paired" in events
    for e in db.query(AuditEvent).all():
        assert PIN not in (e.details or "") and TOKEN not in (e.details or "")


def test_encrypted_tv_commands(client, db, owner, login, csrf, tv, pin_tv, secrets_key):
    device_id = add_encrypted(client, csrf, login, owner)
    home = owner.home_id
    _tv.pair(client, csrf, home, device_id)
    assert send_pin(client, csrf, home, device_id, PIN).status_code == 200
    assert _tv.command(client, csrf, home, device_id, "turn_on").status_code == 200
    assert _tv.command(client, csrf, home, device_id, "volume_up").status_code == 200
    assert tv.keys == [
        (HOST, "encrypted", TOKEN, ["KEY_POWER"]),
        (HOST, "encrypted", TOKEN, ["KEY_VOLUP"]),
    ]
    r = _tv.command(client, csrf, home, device_id, "launch_app", app="netflix")
    assert r.status_code == 422
    db.expire_all()
    assert json.loads(db.get(Device, device_id).state)["volume"] == 11


def test_pin_only_for_encrypted_tvs(
    client, owner, login, csrf, tv, pin_tv, secrets_key
):
    device_id = _tv.ready_tv(client, csrf, login, owner, tv)
    r = send_pin(client, csrf, owner.home_id, device_id, PIN)
    assert r.status_code == 409
    assert pin_tv.tried == []


def test_pin_page_unreachable(client, owner, login, csrf, tv, pin_tv, secrets_key):
    device_id = add_encrypted(client, csrf, login, owner)
    pin_tv.fail = samsung.TvError("could not reach the TV: ClientConnectorError")
    r = _tv.pair(client, csrf, owner.home_id, device_id)
    assert r.status_code == 502


def test_members_cannot_pair(
    client, new_client, owner, make_user, login, csrf, tv, pin_tv, secrets_key
):
    device_id = add_encrypted(client, csrf, login, owner)
    member = make_user(owner.home_id, role="member")
    m = new_client()
    assert login(m, member).status_code == 200
    assert send_pin(m, csrf, owner.home_id, device_id, PIN).status_code == 403
    assert pin_tv.tried == []


# ------------------------------------------------------------ the adapter


class FakeAuth:
    instances = []
    accept = True
    expired = False

    def __init__(self, host, *, web_session, timeout=None, port=8080):
        self.host, self.calls = host, []
        FakeAuth.instances.append(self)

    async def start_pairing(self):
        self.calls.append("start")

    async def try_pin(self, pin):
        self.calls.append(("pin", pin))
        return "aabb" if FakeAuth.accept else None

    async def get_session_id_and_close(self):
        if FakeAuth.expired:
            from samsungtvws.encrypted.authenticator import (
                SamsungTVEncryptedPairingExpiredError,
            )

            raise SamsungTVEncryptedPairingExpiredError("expired")
        return "3"


class FakeRemote:
    sent = []

    def __init__(self, host, *, web_session, token, session_id, **kwargs):
        self.args = (host, token, session_id)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return None

    async def send_commands(self, commands):
        FakeRemote.sent.append(
            (self.args, [c.as_dict()["body"]["param3"] for c in commands])
        )


@pytest.fixture
def fake_library(monkeypatch):
    FakeAuth.instances, FakeAuth.accept, FakeAuth.expired = [], True, False
    FakeRemote.sent = []
    monkeypatch.setattr(samsung, "SamsungTVEncryptedWSAsyncAuthenticator", FakeAuth)
    monkeypatch.setattr(samsung, "SamsungTVEncryptedWSAsyncRemote", FakeRemote)


def test_adapter_pairs_and_sends(fake_library):
    samsung.start_pin_pairing(HOST)
    assert FakeAuth.instances[-1].calls == ["start"]
    assert samsung.finish_pin_pairing(HOST, PIN) == "aabb:3"
    samsung.send_keys(HOST, "encrypted", "aabb:3", ["KEY_VOLUP", "KEY_MUTE"])
    assert FakeRemote.sent == [((HOST, "aabb", "3"), ["KEY_VOLUP", "KEY_MUTE"])]
    with pytest.raises(samsung.TvDenied):
        samsung.send_keys(HOST, "encrypted", None, ["KEY_VOLUP"])
    with pytest.raises(samsung.TvUnsupported):
        samsung.pair(HOST, "encrypted")


def test_adapter_refusals(fake_library):
    FakeAuth.accept = False
    with pytest.raises(samsung.TvDenied, match="PIN"):
        samsung.finish_pin_pairing(HOST, "0000")
    FakeAuth.accept, FakeAuth.expired = True, True
    with pytest.raises(samsung.TvDenied, match="expired"):
        samsung.finish_pin_pairing(HOST, PIN)


def test_adapter_network_errors(monkeypatch):
    class Unreachable(FakeAuth):
        async def start_pairing(self):
            raise OSError("no route")

    monkeypatch.setattr(samsung, "SamsungTVEncryptedWSAsyncAuthenticator", Unreachable)
    with pytest.raises(samsung.TvError, match="could not reach"):
        samsung.start_pin_pairing(HOST)


# ------------------------------------------------------------ browser


def test_ui_encrypted_tv_pin_pairing(open_page, owner, tv, pin_tv, secrets_key):
    page = open_page()
    ui_login(page, owner)
    _tvui.samsung_row(go_settings(page, "integrations")).get_by_test_id(
        "integration-toggle"
    ).check()
    panel = page.get_by_test_id("samsung-tvs")
    panel.get_by_test_id("samsung-name").fill("Bedroom TV")
    panel.get_by_test_id("samsung-host").fill(HOST)
    panel.get_by_test_id("samsung-legacy").check()
    panel.get_by_test_id("samsung-encrypted").check()
    expect(panel.get_by_test_id("samsung-legacy")).not_to_be_checked()
    panel.get_by_test_id("samsung-add").click()
    row = panel.get_by_test_id("samsung-tv-row")
    expect(row).to_contain_text("2014-2015")
    row.get_by_test_id("samsung-pair").click()
    expect(row.get_by_test_id("samsung-pin")).to_be_visible()
    assert pin_tv.shown == [HOST]
    row.get_by_test_id("samsung-pin").fill("1111")
    row.get_by_test_id("samsung-pin-submit").click()
    expect(page.get_by_test_id("status")).to_have_attribute("data-kind", "error")
    row.get_by_test_id("samsung-pin").fill(PIN)
    row.get_by_test_id("samsung-pin-submit").click()
    expect(page.get_by_test_id("status")).to_have_attribute("data-kind", "success")
    expect(
        panel.get_by_test_id("samsung-tv-row").get_by_test_id("samsung-paired")
    ).to_have_text("Paired")
