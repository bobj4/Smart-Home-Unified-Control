"""Garage doors through a ratgdo (ESPHome web server). Nothing here reaches
a real opener: requests and the adapter are replaced."""

import json

import pytest
from playwright.sync_api import expect

from app import features, ratgdo_home
from app.integrations import ratgdo
from app.models import Device
from tests import test_ui as _ui

HOST = "192.168.1.80"


class FakeResponse:
    def __init__(self, data=None, status=200):
        self._data, self.status_code = data, status

    def json(self):
        return self._data


def test_adapter(monkeypatch):
    calls = []

    def request(method, url, timeout):
        calls.append((method, url))
        return FakeResponse(
            {
                "id": "cover-door",
                "state": "OPEN",
                "value": 1.0,
                "current_operation": "IDLE",
            }
        )

    monkeypatch.setattr(ratgdo.requests, "request", request)
    assert ratgdo.door(HOST) == {"door": "open", "position": 100}
    ratgdo.act(HOST, "close")
    assert calls[-1] == ("POST", f"http://{HOST}/cover/door/close")
    with pytest.raises(ratgdo.RatgdoError):
        ratgdo.act(HOST, "explode")
    monkeypatch.setattr(
        ratgdo.requests,
        "request",
        lambda *a, **k: FakeResponse(
            {"state": "CLOSED", "current_operation": "OPENING"}
        ),
    )
    assert ratgdo.door(HOST)["door"] == "opening"
    monkeypatch.setattr(
        ratgdo.requests, "request", lambda *a, **k: FakeResponse(status=404)
    )
    with pytest.raises(ratgdo.RatgdoError, match="ESPHome"):
        ratgdo.door(HOST)


@pytest.fixture
def opener(monkeypatch):
    sent = []
    door = {"door": "closed", "position": 0}
    monkeypatch.setattr(ratgdo, "door", lambda host: dict(door))
    monkeypatch.setattr(ratgdo, "act", lambda host, command: sent.append(command))
    return {"sent": sent, "door": door}


def test_add_command_refresh(client, db, owner, login, csrf, opener):
    assert login(client, owner).status_code == 200
    base = f"/api/v1/homes/{owner.home_id}/integrations/ratgdo"
    client.put(base, json={"enabled": True}, headers=csrf(client))
    r = client.post(
        f"{base}/doors", json={"name": "Garage", "host": HOST}, headers=csrf(client)
    )
    assert r.status_code == 201, r.text
    device_id = r.json()["device_id"]
    cmd = f"/api/v1/homes/{owner.home_id}/devices/{device_id}/command"
    r = client.post(cmd, json={"command": "open", "payload": {}}, headers=csrf(client))
    assert r.status_code == 200, r.text
    assert opener["sent"] == ["open"] and r.json()["state"]["door"] == "opening"
    for bad in (
        {"command": "turn_on", "payload": {}},
        {"command": "open", "payload": {"x": 1}},
    ):
        assert client.post(cmd, json=bad, headers=csrf(client)).status_code == 422
    opener["door"]["door"] = "open"
    assert ratgdo_home.refresh(db, owner.home_id) == 1
    db.expire_all()
    assert json.loads(db.get(Device, device_id).state)["door"] == "open"


def test_ui_garage_tile(open_page, db, owner, opener):
    features.set_integration(db, owner.home_id, "ratgdo", True, None, None)
    ratgdo_home.add_door(db, owner.home_id, "Garage", HOST, "Garage")
    page = open_page()
    _ui.ui_login(page, owner)
    tile = _ui.card(page, "Garage")
    expect(tile.get_by_test_id("garage-state")).to_have_text("Closed")
    expect(tile.get_by_test_id("garage-close")).to_be_disabled()
    tile.get_by_test_id("garage-open").click()
    expect(tile.get_by_test_id("garage-open")).to_have_text("Tap again to open")
    assert opener["sent"] == []  # one tap does not open the garage
    tile.get_by_test_id("garage-open").click()
    expect(tile.get_by_test_id("garage-state")).to_have_text("Opening…")
    assert opener["sent"] == ["open"]
    expect(tile.get_by_test_id("garage-stop")).to_be_visible()
