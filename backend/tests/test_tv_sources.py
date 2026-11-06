# ruff: noqa: F811 (fixtures shared with test_samsung)
"""TV inputs by name through SmartThings: connect a token, link a TV, and the
remote lists and picks its inputs. Nothing here reaches SmartThings."""

import json

import pytest
from playwright.sync_api import expect

from app import features
from app.integrations import smartthings
from app.models import AuditEvent, Device
from tests import test_ui as _ui
from tests.test_samsung import command, ready_tv, secrets_key, tv, url  # noqa: F401

TOKEN = "abcdef12-3456-7890-abcd-ef1234567890"
ST_TV = {"id": "st-tv-1", "name": "[TV] Living room"}
SOURCES = {
    "current": "HDMI1",
    "sources": [
        {"id": "dtv", "name": "TV"},
        {"id": "HDMI1", "name": "PlayStation"},
        {"id": "HDMI2", "name": "Apple TV"},
    ],
}


class FakeSmartThings:
    def __init__(self):
        self.set = []
        self.deny = False

    def tvs(self, token):
        if self.deny or token != TOKEN:
            raise smartthings.SmartThingsDenied("refused")
        return [ST_TV]

    def sources(self, token, device_id):
        assert (token, device_id) == (TOKEN, ST_TV["id"])
        return SOURCES

    def set_source(self, token, device_id, source):
        self.set.append((device_id, source))


@pytest.fixture
def st(monkeypatch):
    fake = FakeSmartThings()
    for name in ("tvs", "sources", "set_source"):
        monkeypatch.setattr(smartthings, name, getattr(fake, name))
    return fake


def st_url(home_id, suffix=""):
    return url(home_id, f"/integrations/samsung_tv/smartthings{suffix}")


def test_reading_named_and_plain_inputs(monkeypatch):
    named = {
        "samsungvd.mediaInputSource": {
            "supportedInputSourcesMap": {
                "value": [{"id": "dtv", "name": "TV"}, {"id": "HDMI1", "name": "PS5"}]
            },
            "inputSource": {"value": "HDMI1"},
        }
    }
    plain = {
        "mediaInputSource": {
            "supportedInputSources": {"value": ["digitalTv", "HDMI1"]},
            "inputSource": {"value": "digitalTv"},
        }
    }
    sent = []
    for status, capability in (
        (named, "samsungvd.mediaInputSource"),
        (plain, "mediaInputSource"),
    ):

        def call(method, path, token, body=None, status=status):
            if method == "POST":
                sent.append(body["commands"][0])
                return None
            return status

        monkeypatch.setattr(smartthings, "_call", call)
        found = smartthings.sources(TOKEN, "x")
        assert found["sources"][1]["id"] == "HDMI1"
        smartthings.set_source(TOKEN, "x", "HDMI1")
        assert sent[-1]["capability"] == capability
        assert sent[-1]["arguments"] == ["HDMI1"]
    assert smartthings.sources(TOKEN, "x")["current"] == "digitalTv"


def test_connect_link_and_pick_an_input(
    client, db, owner, login, csrf, tv, st, secrets_key
):
    device_id = ready_tv(client, csrf, login, owner, tv)
    assert client.get(st_url(owner.home_id)).json() == {
        "connected": False,
        "tvs": [],
        "links": {device_id: None},
    }
    bad = client.put(
        st_url(owner.home_id), json={"token": "wrong-token-123"}, headers=csrf(client)
    )
    assert bad.status_code == 409
    r = client.put(st_url(owner.home_id), json={"token": TOKEN}, headers=csrf(client))
    assert r.status_code == 200, r.text
    assert r.json()["tvs"] == [ST_TV]
    r = client.put(
        url(owner.home_id, f"/integrations/samsung_tv/tvs/{device_id}/smartthings"),
        json={"smartthings_id": ST_TV["id"]},
        headers=csrf(client),
    )
    assert r.status_code == 200, r.text
    devices = client.get(url(owner.home_id, "/devices")).json()
    assert next(d for d in devices if d["id"] == device_id)["smartthings"] is True

    r = client.get(
        url(owner.home_id, f"/integrations/samsung_tv/tvs/{device_id}/sources")
    )
    assert r.json() == SOURCES
    r = command(client, csrf, owner.home_id, device_id, "set_source", source="HDMI2")
    assert r.status_code == 200, r.text
    assert st.set == [(ST_TV["id"], "HDMI2")]
    assert json.loads(db.get(Device, device_id).state)["input"] == "HDMI2"
    for bad_source in ("", "x" * 51, "a/b", 3):
        r = command(
            client, csrf, owner.home_id, device_id, "set_source", source=bad_source
        )
        assert r.status_code == 422, bad_source
    events = [e.event_type for e in db.query(AuditEvent).all()]
    assert "smartthings_connected" in events
    # The token is stored encrypted, never shown.
    assert TOKEN not in json.dumps(client.get(st_url(owner.home_id)).json())

    r = client.delete(st_url(owner.home_id), headers=csrf(client))
    assert r.json()["connected"] is False
    r = command(client, csrf, owner.home_id, device_id, "set_source", source="HDMI1")
    assert r.status_code == 409


def test_unlinked_tv_has_no_sources(client, owner, login, csrf, tv, st, secrets_key):
    device_id = ready_tv(client, csrf, login, owner, tv)
    r = client.get(
        url(owner.home_id, f"/integrations/samsung_tv/tvs/{device_id}/sources")
    )
    assert r.status_code == 409


def test_members_cannot_connect(
    client, owner, make_user, new_client, login, csrf, st, secrets_key
):
    member = make_user(owner.home_id, role="member")
    m = new_client()
    assert login(m, member).status_code == 200
    assert m.get(st_url(owner.home_id)).status_code == 403
    r = m.put(st_url(owner.home_id), json={"token": TOKEN}, headers=csrf(m))
    assert r.status_code == 403


def test_ui_connect_link_and_named_inputs(
    open_page, db, owner, make_device, st, secrets_key
):
    device_id = make_device(owner.home_id, device_type="tv", name="Den TV")
    device = db.get(Device, device_id)
    device.integration = "samsung_tv"
    device.external_id = "192.168.1.60"
    device.capabilities = json.dumps({"protocol": "tizen", "paired": True})
    device.state = json.dumps({"on": True, "input": "tv"})
    db.commit()
    features.set_integration(db, owner.home_id, "samsung_tv", True, None, None)
    page = open_page()
    _ui.ui_login(page, owner)
    page.goto(page.url.split("#")[0] + "#/settings/integrations")
    panel = page.get_by_test_id("smartthings")
    panel.get_by_test_id("smartthings-token").fill(TOKEN)
    panel.get_by_test_id("smartthings-connect").click()
    expect(panel.get_by_test_id("smartthings-connected")).to_be_visible()
    panel.get_by_test_id("smartthings-link").select_option(ST_TV["id"])
    expect(page.get_by_test_id("status")).to_contain_text("Den TV linked")

    page.goto(page.url.split("#")[0] + "#/devices")
    _ui.card(page, "Den TV").get_by_test_id("tv-remote-open").click()
    source = page.get_by_test_id("remote-input")
    expect(source).to_have_attribute("data-named", "true")
    expect(source.locator("option")).to_have_text(["TV", "PlayStation", "Apple TV"])
    expect(page.get_by_test_id("remote-screen")).to_contain_text("PlayStation")
    source.select_option("HDMI2")
    expect(page.get_by_test_id("remote-screen")).to_contain_text("Apple TV")
    assert st.set == [(ST_TV["id"], "HDMI2")]
