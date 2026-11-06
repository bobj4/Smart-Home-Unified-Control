# ruff: noqa: F811 (a fixture shared with test_samsung)
"""TP-Link Kasa. Nothing here reaches a real device: the original protocol
is checked against TP-Link's published scrambling, KLAP against a fake
device built from the same key schedule, and the rest with the adapter
replaced."""

import hashlib
import json
import struct

import pytest
from cryptography.hazmat.primitives import padding
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from playwright.sync_api import expect

from app import features, kasa_home
from app.integrations import kasa
from tests import test_ui as _ui
from tests.test_samsung import secrets_key  # noqa: F401

HOST = "192.168.1.90"


def test_scrambling_round_trip():
    text = b'{"system":{"get_sysinfo":{}}}'
    assert kasa._scramble(text)[:4] == bytes(
        [0xD0, 0xF2, 0x81, 0xF8]
    )  # the known prefix
    assert kasa._unscramble(kasa._scramble(text)) == text


def test_commands():
    plug = kasa.body_for("turn_on", {}, bulb=False, child=None)
    assert plug == {"system": {"set_relay_state": {"state": 1}}}
    outlet = kasa.body_for("turn_off", {}, bulb=False, child="ABC01")
    assert outlet["context"] == {"child_ids": ["ABC01"]}
    dim = kasa.body_for("set_brightness", {"brightness": 40}, bulb=False, child=None)
    assert dim[kasa.DIMMER] == {"set_brightness": {"brightness": 40}}
    bulb = kasa.body_for("set_color", {"color": "#ff0000"}, bulb=True, child=None)
    light = bulb[kasa.BULB]["transition_light_state"]
    assert (light["hue"], light["saturation"], light["brightness"]) == (0, 100, 100)
    with pytest.raises(kasa.KasaError):
        kasa.body_for("set_color", {"color": "#ff0000"}, bulb=False, child=None)


def test_devices_strip_and_dimmer(monkeypatch):
    strip = {
        "system": {
            "get_sysinfo": {
                "model": "HS300",
                "alias": "Strip",
                "children": [
                    {"id": "01", "alias": "Lamp", "state": 1},
                    {"id": "02", "alias": "Fan", "state": 0},
                ],
            }
        }
    }
    monkeypatch.setattr(kasa, "request", lambda host, body, login=None: strip)
    found = kasa.devices(HOST)
    assert [(d["id"], d["name"], d["on"]) for d in found] == [
        (f"{HOST}/01", "Lamp", True),
        (f"{HOST}/02", "Fan", False),
    ]
    dimmer = {
        "system": {
            "get_sysinfo": {
                "model": "HS220",
                "alias": "Hall",
                "relay_state": 1,
                "brightness": 30,
            }
        }
    }
    monkeypatch.setattr(kasa, "request", lambda host, body, login=None: dimmer)
    assert kasa.devices(HOST)[0]["kind"] == "light"


class FakeKlapDevice:
    """Answers KLAP v2 as a device set up with this login."""

    def __init__(self, email, password):
        sha1 = lambda s: hashlib.sha1(s.encode()).digest()  # noqa: E731
        self.auth = hashlib.sha256(sha1(email) + sha1(password)).digest()
        self.remote = b"R" * 16

    def post(self, url, data=None, params=None, timeout=None):
        response = type("R", (), {"status_code": 200})()
        if url.endswith("handshake1"):
            self.local = data
            response.content = (
                self.remote
                + hashlib.sha256(self.local + self.remote + self.auth).digest()
            )
        elif url.endswith("handshake2"):
            assert data == hashlib.sha256(self.remote + self.local + self.auth).digest()
            response.content = b""
        else:
            seeds = self.local + self.remote + self.auth
            key = hashlib.sha256(b"lsk" + seeds).digest()[:16]
            iv = hashlib.sha256(b"iv" + seeds).digest()[:12] + struct.pack(
                ">i", params["seq"]
            )
            dec = Cipher(algorithms.AES(key), modes.CBC(iv)).decryptor()
            unpad = padding.PKCS7(128).unpadder()
            body = json.loads(
                unpad.update(dec.update(data[32:]) + dec.finalize()) + unpad.finalize()
            )
            assert body == {"system": {"get_sysinfo": {}}}
            pad = padding.PKCS7(128).padder()
            plain = (
                pad.update(
                    json.dumps(
                        {
                            "system": {
                                "get_sysinfo": {
                                    "model": "KP115",
                                    "alias": "Kettle",
                                    "relay_state": 0,
                                }
                            }
                        }
                    ).encode()
                )
                + pad.finalize()
            )
            enc = Cipher(algorithms.AES(key), modes.CBC(iv)).encryptor()
            response.content = b"S" * 32 + enc.update(plain) + enc.finalize()
        return response


def test_klap_with_login(monkeypatch):
    fake = FakeKlapDevice("me@example.com", "secret")
    monkeypatch.setattr(
        kasa,
        "_xor_request",
        lambda host, body: (_ for _ in ()).throw(kasa.KasaError("no 9999")),
    )
    monkeypatch.setattr(kasa.requests, "Session", lambda: fake)
    found = kasa.devices(HOST, ("me@example.com", "secret"))
    assert found[0]["name"] == "Kettle" and found[0]["kind"] == "plug"
    with pytest.raises(kasa.KasaLogin):
        kasa.devices(HOST, ("me@example.com", "wrong"))


@pytest.fixture
def plug(monkeypatch):
    sent = []
    state = {"on": False}
    monkeypatch.setattr(
        kasa,
        "devices",
        lambda host, login=None: [
            {
                "id": host,
                "name": "Kettle",
                "kind": "plug",
                "model": "KP115",
                "on": state["on"],
            }
        ],
    )
    monkeypatch.setattr(
        kasa, "send", lambda host, body, login=None: sent.append((host, body))
    )
    return {"sent": sent, "state": state}


def test_add_command_refresh(client, db, owner, login, csrf, plug, secrets_key):
    assert login(client, owner).status_code == 200
    base = f"/api/v1/homes/{owner.home_id}/integrations/kasa"
    client.put(base, json={"enabled": True}, headers=csrf(client))
    r = client.post(f"{base}/devices", json={"host": HOST}, headers=csrf(client))
    assert r.status_code == 201, r.text
    device_id = r.json()[0]["device_id"]
    r = client.post(
        f"/api/v1/homes/{owner.home_id}/devices/{device_id}/command",
        json={"command": "turn_on", "payload": {}},
        headers=csrf(client),
    )
    assert r.status_code == 200, r.text
    assert plug["sent"] == [(HOST, {"system": {"set_relay_state": {"state": 1}}})]
    plug["state"]["on"] = True
    assert kasa_home.refresh(db, owner.home_id) >= 0
    r = client.put(
        f"{base}/login",
        json={"email": "me@example.com", "password": "pw"},
        headers=csrf(client),
    )
    assert r.json() == {"login": "me@example.com"}
    assert "pw" not in json.dumps(client.get(base).json())


def test_ui_add_kasa(open_page, db, owner, plug, secrets_key):
    features.set_integration(db, owner.home_id, "kasa", True, None, None)
    page = open_page()
    _ui.ui_login(page, owner)
    page.goto(page.url.split("#")[0] + "#/settings/integrations")
    panel = page.get_by_test_id("kasa-devices")
    panel.get_by_test_id("kasa-host").fill(HOST)
    panel.get_by_test_id("kasa-add").click()
    expect(panel.get_by_test_id("kasa-row")).to_contain_text("Kettle")
