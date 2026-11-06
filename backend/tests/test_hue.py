# ruff: noqa: F811 (a fixture shared with test_samsung)
"""Philips Hue through the bridge's local API. Nothing here reaches a real
bridge: requests and the adapter are replaced."""

import json

import pytest
from playwright.sync_api import expect

from app import features, hue_home
from app.integrations import hue
from app.models import Device
from tests import test_ui as _ui
from tests.test_samsung import secrets_key  # noqa: F401

BRIDGE = "192.168.1.40"
LIGHTS = {
    "1": {
        "name": "Sofa lamp",
        "type": "Extended color light",
        "state": {
            "on": True,
            "bri": 127,
            "ct": 366,
            "xy": [0.4, 0.4],
            "reachable": True,
        },
        "capabilities": {"control": {"ct": {"min": 153, "max": 500}, "colorgamut": []}},
    },
    "2": {
        "name": "Fan plug",
        "type": "On/Off plug-in unit",
        "state": {"on": False, "reachable": False},
    },
}


class FakeResponse:
    def __init__(self, data, status=200):
        self._data, self.status_code = data, status

    def json(self):
        return self._data


def test_adapter(monkeypatch):
    calls = []

    def request(method, url, json=None, timeout=None):
        calls.append((method, url, json))
        if url.endswith("/api") and method == "POST":
            return FakeResponse([{"success": {"username": "KEY"}}])
        if url.endswith("/lights"):
            return FakeResponse(LIGHTS)
        return FakeResponse([{"success": {}}])

    monkeypatch.setattr(hue.requests, "request", request)
    assert hue.pair(BRIDGE) == "KEY"
    found = {i["id"]: i for i in hue.lights(BRIDGE, "KEY")}
    assert found["1"]["kind"] == "light" and found["1"]["brightness"] == 50
    assert found["1"]["white"] and found["1"]["color"]
    assert found["2"]["kind"] == "plug" and found["2"]["online"] is False
    hue.set_state(BRIDGE, "KEY", "1", {"on": True})
    assert calls[-1] == ("PUT", f"http://{BRIDGE}/api/KEY/lights/1/state", {"on": True})
    with pytest.raises(hue.HueError):
        hue.set_state(BRIDGE, "KEY", "../x", {})
    monkeypatch.setattr(
        hue.requests,
        "request",
        lambda *a, **k: FakeResponse([{"error": {"type": 101}}]),
    )
    with pytest.raises(hue.HueButton):
        hue.pair(BRIDGE)


def test_bodies():
    assert hue.body_for("turn_off", {}) == {"on": False}
    assert hue.body_for("set_brightness", {"brightness": 100}) == {
        "on": True,
        "bri": 254,
    }
    assert hue.body_for("set_brightness", {"brightness": 0}) == {"on": False}
    assert hue.body_for("set_color_temp", {"color_temp": 2700}) == {
        "on": True,
        "ct": 370,
    }
    assert hue.body_for("set_color_temp", {"color_temp": 6500})["ct"] == 154
    xy = hue.body_for("set_color", {"color": "#ff0000"})["xy"]
    assert abs(xy[0] - 0.64) < 0.01 and abs(xy[1] - 0.33) < 0.01


@pytest.fixture
def bridge(monkeypatch):
    sent = []
    data = {
        "lights": [
            {
                "id": "1",
                "name": "Sofa lamp",
                "kind": "light",
                "white": True,
                "color": True,
                "online": True,
                "on": True,
                "brightness": 50,
            },
            {
                "id": "2",
                "name": "Fan plug",
                "kind": "plug",
                "white": False,
                "color": False,
                "online": True,
                "on": False,
                "brightness": None,
            },
        ]
    }
    monkeypatch.setattr(hue, "pair", lambda host: "KEY")
    monkeypatch.setattr(
        hue, "lights", lambda host, key: [dict(i) for i in data["lights"]]
    )
    monkeypatch.setattr(
        hue, "set_state", lambda host, key, light, body: sent.append((light, body))
    )
    return {"sent": sent, "data": data}


def test_pair_command_refresh_unpair(
    client, db, owner, login, csrf, bridge, secrets_key
):
    assert login(client, owner).status_code == 200
    base = f"/api/v1/homes/{owner.home_id}/integrations/hue"
    assert (
        client.post(
            f"{base}/pair", json={"host": BRIDGE}, headers=csrf(client)
        ).status_code
        == 409
    )
    client.put(
        f"/api/v1/homes/{owner.home_id}/integrations/hue",
        json={"enabled": True},
        headers=csrf(client),
    )
    assert (
        client.post(
            f"{base}/pair", json={"host": "8.8.8.8"}, headers=csrf(client)
        ).status_code
        == 422
    )
    r = client.post(f"{base}/pair", json={"host": BRIDGE}, headers=csrf(client))
    assert r.status_code == 200, r.text
    assert r.json()["paired"] and r.json()["created"] == 2
    lamp = db.query(Device).filter_by(integration="hue", external_id="1").one()
    assert lamp.type == "light" and json.loads(lamp.state)["brightness"] == 50
    r = client.post(
        f"/api/v1/homes/{owner.home_id}/devices/{lamp.id}/command",
        json={"command": "set_brightness", "payload": {"brightness": 100}},
        headers=csrf(client),
    )
    assert r.status_code == 200, r.text
    assert bridge["sent"] == [("1", {"on": True, "bri": 254})]
    bridge["data"]["lights"][0]["on"] = False
    assert hue_home.refresh(db, owner.home_id) == 1
    r = client.delete(base, headers=csrf(client))
    assert r.json()["paired"] is False
    assert db.query(Device).filter_by(integration="hue").count() == 0


def test_ui_pair_hue(open_page, db, owner, bridge, secrets_key):
    features.set_integration(db, owner.home_id, "hue", True, None, None)
    page = open_page()
    _ui.ui_login(page, owner)
    page.goto(page.url.split("#")[0] + "#/settings/integrations")
    panel = page.get_by_test_id("hue")
    panel.get_by_test_id("hue-host").fill(BRIDGE)
    panel.get_by_test_id("hue-pair").click()
    expect(panel.get_by_test_id("hue-paired")).to_contain_text("2 lights")
    page.goto(page.url.split("#")[0] + "#/devices")
    expect(_ui.card(page, "Sofa lamp")).to_be_visible()
    expect(_ui.card(page, "Fan plug")).to_be_visible()
