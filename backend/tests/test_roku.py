"""Roku TVs and players over Roku's local control protocol. Nothing here
reaches a real Roku: requests and the adapter are replaced."""

import json

import pytest
from playwright.sync_api import expect

from app import roku_home
from app.integrations import roku
from app.models import Device
from tests import test_ui as _ui

HOST = "192.168.1.60"
INFO = """<device-info><user-device-name>Den Roku TV</user-device-name>
<model-name>TCL 55S455</model-name><is-tv>true</is-tv><power-mode>PowerOn</power-mode></device-info>"""
APPS = """<apps><app id="12" type="appl" version="5">Netflix</app>
<app id="837" type="appl">YouTube &amp; Kids</app></apps>"""


def url(home_id, suffix):
    return f"/api/v1/homes/{home_id}/integrations/roku_tv{suffix}"


class FakeResponse:
    def __init__(self, text="", status=200):
        self.text, self.status_code = text, status


def test_adapter_reads_and_sends(monkeypatch):
    sent = []
    monkeypatch.setattr(
        roku.requests,
        "get",
        lambda u, timeout: FakeResponse(INFO if "device-info" in u else APPS),
    )
    monkeypatch.setattr(
        roku.requests, "post", lambda u, timeout: sent.append(u) or FakeResponse()
    )
    assert roku.info(HOST) == {
        "name": "Den Roku TV",
        "model": "TCL 55S455",
        "is_tv": True,
        "on": True,
    }
    assert roku.apps(HOST) == [
        {"id": "12", "name": "Netflix"},
        {"id": "837", "name": "YouTube & Kids"},
    ]
    roku.command(HOST, "volume_up", {})
    roku.command(HOST, "set_input", {"source": "hdmi2"})
    roku.command(HOST, "launch_app", {"app": "netflix"})
    roku.command(HOST, "press_key", {"key": "select"})
    roku.command(HOST, "set_channel", {"channel": 7})
    assert sent == [
        f"http://{HOST}:8060/keypress/VolumeUp",
        f"http://{HOST}:8060/keypress/InputHDMI2",
        f"http://{HOST}:8060/launch/12",
        f"http://{HOST}:8060/keypress/Select",
        f"http://{HOST}:8060/launch/tvinput.dtv?ch=7",
    ]
    with pytest.raises(roku.RokuUnsupported):
        roku.command(HOST, "set_volume", {"level": 5})
    with pytest.raises(roku.RokuError):
        roku.launch(HOST, "../x")
    monkeypatch.setattr(roku.requests, "get", lambda u, timeout: FakeResponse("", 403))
    with pytest.raises(roku.RokuError, match="Control by mobile apps"):
        roku.info(HOST)
    assert roku.is_on(HOST) is None


@pytest.fixture
def fake(monkeypatch):
    sent = []
    state = {"on": True}
    monkeypatch.setattr(
        roku,
        "info",
        lambda host: {
            "name": "Den Roku TV",
            "model": "TCL",
            "is_tv": True,
            "on": state["on"],
        },
    )
    monkeypatch.setattr(roku, "is_on", lambda host: state["on"])
    monkeypatch.setattr(
        roku, "command", lambda host, name, payload: sent.append((host, name, payload))
    )
    return {"sent": sent, "state": state}


def turn_on(client, csrf, home_id):
    r = client.put(
        f"/api/v1/homes/{home_id}/integrations/roku_tv",
        json={"enabled": True},
        headers=csrf(client),
    )
    assert r.status_code == 200, r.text


def test_add_command_refresh_remove(
    client, db, owner, make_user, new_client, login, csrf, fake
):
    assert login(client, owner).status_code == 200
    r = client.post(
        url(owner.home_id, "/tvs"), json={"host": HOST}, headers=csrf(client)
    )
    assert r.status_code == 409  # turned off
    turn_on(client, csrf, owner.home_id)
    for bad in ("8.8.8.8", "127.0.0.1", "not-an-ip"):
        r = client.post(
            url(owner.home_id, "/tvs"), json={"host": bad}, headers=csrf(client)
        )
        assert r.status_code == 422, bad
    r = client.post(
        url(owner.home_id, "/tvs"), json={"host": HOST}, headers=csrf(client)
    )
    assert r.status_code == 201, r.text
    tv = r.json()
    assert tv["name"] == "Den Roku TV" and tv["is_tv"] is True
    r = client.post(
        url(owner.home_id, "/tvs"), json={"host": HOST}, headers=csrf(client)
    )
    assert r.status_code == 409  # already added
    r = client.post(
        f"/api/v1/homes/{owner.home_id}/devices/{tv['device_id']}/command",
        json={"command": "volume_up", "payload": {}},
        headers=csrf(client),
    )
    assert r.status_code == 200, r.text
    assert fake["sent"] == [(HOST, "volume_up", {})]
    fake["state"]["on"] = False
    assert roku_home.refresh(db, owner.home_id) == 1
    db.expire_all()
    assert json.loads(db.get(Device, tv["device_id"]).state)["on"] is False
    member = make_user(owner.home_id, role="member")
    m = new_client()
    assert login(m, member).status_code == 200
    assert m.get(url(owner.home_id, "/tvs")).status_code == 403
    r = client.delete(
        url(owner.home_id, f"/tvs/{tv['device_id']}"), headers=csrf(client)
    )
    assert r.status_code == 200 and client.get(url(owner.home_id, "/tvs")).json() == []


def test_player_has_no_inputs(client, db, owner, login, csrf, fake, monkeypatch):
    monkeypatch.setattr(
        roku,
        "info",
        lambda host: {"name": "Stick", "model": "Express", "is_tv": False, "on": True},
    )
    assert login(client, owner).status_code == 200
    turn_on(client, csrf, owner.home_id)
    tv = client.post(
        url(owner.home_id, "/tvs"), json={"host": HOST}, headers=csrf(client)
    ).json()
    r = client.post(
        f"/api/v1/homes/{owner.home_id}/devices/{tv['device_id']}/command",
        json={"command": "set_input", "payload": {"source": "hdmi1"}},
        headers=csrf(client),
    )
    assert r.status_code == 422


def test_ui_add_roku(open_page, db, owner, fake):
    from app import features

    features.set_integration(db, owner.home_id, "roku_tv", True, None, None)
    page = open_page()
    _ui.ui_login(page, owner)
    page.goto(page.url.split("#")[0] + "#/settings/integrations")
    panel = page.get_by_test_id("roku-tvs")
    panel.get_by_test_id("roku-host").fill(HOST)
    panel.get_by_test_id("roku-add").click()
    expect(panel.get_by_test_id("roku-row")).to_contain_text("Den Roku TV")
    page.goto(page.url.split("#")[0] + "#/devices")
    expect(_ui.card(page, "Den Roku TV")).to_be_visible()
    _ui.card(page, "Den Roku TV").get_by_test_id("tv-remote-open").click()
    page.get_by_test_id("remote-key-select").click()
    expect(page.get_by_test_id("status")).to_contain_text("press key")
    assert (HOST, "press_key", {"key": "select"}) in fake["sent"]
