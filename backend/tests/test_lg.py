# ruff: noqa: F811 (a fixture shared with test_samsung)
"""LG webOS TVs. Nothing here reaches a real TV: the websocket and the
adapter are replaced."""

import json

import pytest
from playwright.sync_api import expect

from app import features
from app.integrations import lg, samsung
from tests import test_ui as _ui
from tests.test_samsung import secrets_key  # noqa: F401

HOST = "192.168.1.70"


class FakeSocket:
    """Answers registration, then each request with an empty payload."""

    def __init__(self, sent):
        self.sent, self.queue = sent, []

    def settimeout(self, value):
        pass

    def send(self, text):
        if text.startswith("type:button"):
            self.sent.append(("button", text.split("\n")[1]))
            return
        message = json.loads(text)
        self.sent.append(
            (message.get("uri") or message["type"], message.get("payload"))
        )
        if message["type"] == "register":
            self.queue.append({"type": "registered", "payload": {"client-key": "KEY"}})
        elif message.get("uri", "").endswith("getPointerInputSocket"):
            self.queue.append(
                {
                    "id": message["id"],
                    "type": "response",
                    "payload": {"socketPath": "wss://tv/pointer"},
                }
            )
        elif message.get("uri", "").endswith("getStatus"):
            self.queue.append(
                {"id": message["id"], "type": "response", "payload": {"mute": False}}
            )
        else:
            self.queue.append({"id": message["id"], "type": "response", "payload": {}})

    def recv(self):
        return json.dumps(self.queue.pop(0))

    def close(self):
        pass


def test_adapter_commands(monkeypatch):
    sent = []
    monkeypatch.setattr(
        lg.websocket, "create_connection", lambda url, timeout, sslopt: FakeSocket(sent)
    )
    assert lg.pair(HOST) == "KEY"
    lg.command(HOST, "KEY", "set_volume", {"level": 12})
    lg.command(HOST, "KEY", "toggle_mute", {})
    lg.command(HOST, "KEY", "set_input", {"source": "hdmi2"})
    lg.command(HOST, "KEY", "launch_app", {"app": "netflix"})
    lg.command(HOST, "KEY", "press_key", {"key": "select"})
    lg.command(HOST, "KEY", "press_key", {"key": "pause"})
    uris = [s for s in sent if s[0] != "register"]
    assert ("ssap://audio/setVolume", {"volume": 12}) in uris
    assert ("ssap://audio/setMute", {"mute": True}) in uris
    assert ("ssap://tv/switchInput", {"inputId": "HDMI_2"}) in uris
    assert ("ssap://system.launcher/launch", {"id": "netflix"}) in uris
    assert ("button", "name:ENTER") in uris
    assert ("ssap://media.controls/pause", None) in uris
    registers = [s[1] for s in sent if s[0] == "register"]
    assert "client-key" not in registers[0]  # pairing: no key yet
    assert registers[1]["client-key"] == "KEY"  # later connections send it
    with pytest.raises(lg.LgUnsupported):
        lg.command(HOST, "KEY", "set_input", {"source": "usb"})


@pytest.fixture
def tv(monkeypatch):
    sent = []
    monkeypatch.setattr(lg, "pair", lambda host: "KEY")
    monkeypatch.setattr(
        lg,
        "command",
        lambda host, key, name, payload: sent.append((host, key, name, payload)),
    )
    monkeypatch.setattr(lg, "is_on", lambda host: True)
    monkeypatch.setattr(samsung, "wake", lambda mac: sent.append(("wake", mac)))
    return sent


def test_add_pair_command(client, db, owner, login, csrf, tv, secrets_key):
    assert login(client, owner).status_code == 200
    base = f"/api/v1/homes/{owner.home_id}/integrations/lg_tv"
    client.put(base, json={"enabled": True}, headers=csrf(client))
    r = client.post(
        f"{base}/tvs",
        json={"name": "Bedroom TV", "host": HOST, "mac": "aa-bb-cc-dd-ee-ff"},
        headers=csrf(client),
    )
    assert r.status_code == 201, r.text
    device_id = r.json()["device_id"]
    cmd = f"/api/v1/homes/{owner.home_id}/devices/{device_id}/command"
    r = client.post(
        cmd, json={"command": "turn_on", "payload": {}}, headers=csrf(client)
    )
    assert r.status_code == 200  # Wake-on-LAN needs no pairing
    assert ("wake", "AA:BB:CC:DD:EE:FF") in tv
    r = client.post(
        cmd, json={"command": "volume_up", "payload": {}}, headers=csrf(client)
    )
    assert r.status_code == 409  # not paired yet
    r = client.post(f"{base}/tvs/{device_id}/pair", headers=csrf(client))
    assert r.status_code == 200 and r.json()["paired"] is True
    r = client.post(
        cmd, json={"command": "volume_up", "payload": {}}, headers=csrf(client)
    )
    assert r.status_code == 200, r.text
    assert (HOST, "KEY", "volume_up", {}) in tv
    assert (
        client.delete(f"{base}/tvs/{device_id}", headers=csrf(client)).status_code
        == 200
    )


def test_ui_add_and_pair(open_page, db, owner, tv, secrets_key):
    features.set_integration(db, owner.home_id, "lg_tv", True, None, None)
    page = open_page()
    _ui.ui_login(page, owner)
    page.goto(page.url.split("#")[0] + "#/settings/integrations")
    panel = page.get_by_test_id("lg-tvs")
    panel.get_by_test_id("lg-name").fill("Bedroom TV")
    panel.get_by_test_id("lg-host").fill(HOST)
    panel.get_by_test_id("lg-add").click()
    row = panel.get_by_test_id("lg-row")
    expect(row).to_contain_text("Not paired yet")
    row.get_by_test_id("lg-pair").click()
    expect(panel.get_by_test_id("lg-row")).to_contain_text("Paired")
