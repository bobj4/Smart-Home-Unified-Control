# ruff: noqa: F811 (a fixture shared with test_samsung)
"""Homes at other sites: a home here whose devices are run by that site's
own server. Pairing with a code, the site's connection, requests for the
home forwarded there (after the login, role and CSRF checks here), and the
site running them as the requester's role."""

import asyncio
import json
import threading
from concurrent.futures import ThreadPoolExecutor

import pytest
from starlette.websockets import WebSocketDisconnect

from app import federation, federation_site
from app.models import Home
from tests.test_samsung import secrets_key  # noqa: F401 (a shared fixture)

PAIR = "/api/v1/federation/pair"


@pytest.fixture(autouse=True)
def fresh():
    federation.forget_cache()
    federation._links.clear()
    yield
    federation.forget_cache()
    federation._links.clear()


def start_pairing(client, csrf, home_id):
    r = client.post(f"/api/v1/homes/{home_id}/site/pairing", headers=csrf(client))
    assert r.status_code == 200, r.text
    return r.json()["code"]


def linked(client, new_client, csrf, owner, login, site_home="site-home-1"):
    assert login(client, owner).status_code == 200
    code = start_pairing(client, csrf, owner.home_id)
    r = new_client().post(
        PAIR, json={"code": code, "site_home_id": site_home, "site_name": "Lake site"}
    )
    assert r.status_code == 200, r.text
    return r.json()["token"]


def test_pairing_once_and_unlinking(client, new_client, db, owner, login, csrf):
    assert login(client, owner).status_code == 200
    code = start_pairing(client, csrf, owner.home_id)
    body = {"code": code, "site_home_id": "s1", "site_name": "Lake"}
    r = new_client().post(PAIR, json=body)
    assert r.status_code == 200 and r.json()["home_id"] == owner.home_id
    token = r.json()["token"]
    assert new_client().post(PAIR, json=body).status_code == 404  # used
    state = client.get(f"/api/v1/homes/{owner.home_id}/site").json()
    assert state["linked"] is True and state["connected"] is False
    assert state["site_name"] == "Lake"
    db.expire_all()
    home = db.get(Home, owner.home_id)
    assert token not in (home.site_token_hash or "")  # only its hash is kept
    assert federation.home_for_token(db, token).id == owner.home_id
    r = client.delete(f"/api/v1/homes/{owner.home_id}/site", headers=csrf(client))
    assert r.json()["linked"] is False
    assert federation.home_for_token(db, token) is None
    bad = {"code": "AAAA-BBBB-CCCC", "site_home_id": "s1"}
    assert new_client().post(PAIR, json=bad).status_code == 404


def test_only_admins_link(client, new_client, owner, make_user, login, csrf):
    member = make_user(owner.home_id, role="member")
    c = new_client()
    assert login(c, member).status_code == 200
    url = f"/api/v1/homes/{owner.home_id}/site"
    assert c.post(f"{url}/pairing", headers=csrf(c)).status_code == 403
    assert c.get(url).status_code == 403


@pytest.fixture
def site_loop():
    """The loop a fake site's connection runs on (a thread of its own)."""
    loop = asyncio.new_event_loop()
    thread = threading.Thread(target=loop.run_forever, daemon=True)
    thread.start()
    yield loop
    loop.call_soon_threadsafe(loop.stop)
    thread.join(5)


def echo_site(home_id, loop):
    """A connected site that answers each request with what it was sent."""
    sent = []

    async def send(text):
        message = json.loads(text)
        sent.append(message)
        answer = {
            "type": "response",
            "id": message["id"],
            "status": 200,
            "content_type": "application/json",
            "body": json.dumps({"path": message["path"], "role": message["role"]}),
        }
        asyncio.get_running_loop().call_soon(
            federation.answered, link, json.dumps(answer)
        )

    link = federation.Link(send, loop)
    federation.connected(home_id, link)
    return sent


def test_requests_go_to_the_site(
    client, new_client, owner, make_user, login, csrf, make_home, site_loop
):
    linked(client, new_client, csrf, owner, login)
    sent = echo_site(owner.home_id, site_loop)
    base = f"/api/v1/homes/{owner.home_id}"
    r = client.get(f"{base}/devices?live=1")
    assert r.status_code == 200
    assert r.json() == {"path": "/api/v1/homes/site-home-1/devices", "role": "admin"}
    assert sent[0]["query"] == "live=1" and sent[0]["method"] == "GET"
    # Writes need the CSRF token here first.
    assert client.post(f"{base}/devices", json={}).status_code == 403
    r = client.post(f"{base}/devices", json={"name": "x"}, headers=csrf(client))
    assert r.status_code == 200 and sent[-1]["body"] == '{"name":"x"}'
    # People and logins stay here: not forwarded.
    assert client.get(f"{base}/members").status_code == 200
    assert all("/members" not in m["path"] for m in sent)
    # The requester's role here goes with it; others are refused here.
    member = make_user(owner.home_id, role="member")
    m = new_client()
    assert login(m, member).status_code == 200
    assert m.get(f"{base}/devices").json()["role"] == "member"
    guest = make_user(owner.home_id, role="guest")
    g = new_client()
    assert login(g, guest).status_code == 200
    assert g.get(f"{base}/devices").status_code == 403
    stranger = make_user(make_home("Elsewhere"), role="admin")
    s = new_client()
    assert login(s, stranger).status_code == 200
    assert s.get(f"{base}/devices").status_code == 404
    assert new_client().get(f"{base}/devices").status_code == 401


def test_a_site_not_connected(client, new_client, owner, login, csrf):
    linked(client, new_client, csrf, owner, login)
    r = client.get(f"/api/v1/homes/{owner.home_id}/devices")
    assert r.status_code == 503 and "not connected" in r.json()["detail"]


def test_the_site_connection(client, new_client, owner, login, csrf):
    token = linked(client, new_client, csrf, owner, login)
    with pytest.raises(WebSocketDisconnect):  # a wrong token is turned away
        with new_client().websocket_connect(
            "/api/v1/federation/connect", headers={"Authorization": "Bearer nope"}
        ) as ws:
            ws.receive_text()
    site = new_client()
    with site.websocket_connect(
        "/api/v1/federation/connect", headers={"Authorization": f"Bearer {token}"}
    ) as ws:
        result = {}
        asking = threading.Thread(
            target=lambda: result.update(
                r=client.get(f"/api/v1/homes/{owner.home_id}/rooms")
            )
        )
        asking.start()
        request = json.loads(ws.receive_text())
        assert request["path"] == "/api/v1/homes/site-home-1/rooms"
        ws.send_text(
            json.dumps(
                {
                    "type": "response",
                    "id": request["id"],
                    "status": 200,
                    "content_type": "application/json",
                    "body": '["Den"]',
                }
            )
        )
        asking.join(10)
        assert result["r"].status_code == 200 and result["r"].json() == ["Den"]
        state = client.get(f"/api/v1/homes/{owner.home_id}/site").json()
        assert state["connected"] is True


def run(coro):
    with ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(asyncio.run, coro).result()


def test_the_site_runs_requests_as_the_role(app, owner, make_device, make_home):
    make_device(owner.home_id, name="Porch light")
    home = owner.home_id

    def ask(method, path, role, body=""):
        answer = run(
            federation_site.run_here(
                app, home, {"method": method, "path": path, "role": role, "body": body}
            )
        )
        return answer["status"], answer["body"]

    status_code, body = ask("GET", f"/api/v1/homes/{home}/devices", "member")
    assert status_code == 200 and "Porch light" in body
    new = json.dumps({"name": "Lamp", "type": "light", "integration": "simulated"})
    assert ask("POST", f"/api/v1/homes/{home}/devices", "member", new)[0] == 403
    assert ask("POST", f"/api/v1/homes/{home}/devices", "admin", new)[0] == 201
    other = make_home("Elsewhere")
    assert ask("GET", f"/api/v1/homes/{other}/devices", "admin")[0] == 403
    assert ask("GET", f"/api/v1/homes/{home}/devices", "guest")[0] == 403


class FakeAnswer:
    def __init__(self, status_code, data):
        self.status_code = status_code
        self.data = data

    def json(self):
        return self.data


def test_linking_this_server_to_a_main_server(
    client, owner, login, csrf, monkeypatch, secrets_key
):
    asked = []

    def post(url, json, timeout):
        asked.append((url, json))
        if json["code"] == "BAD0-BAD0-BAD0":
            return FakeAnswer(404, {})
        return FakeAnswer(
            200, {"token": "t0k", "home_id": "main-1", "home_name": "Lake"}
        )

    monkeypatch.setattr(federation_site.requests, "post", post)
    assert login(client, owner).status_code == 200
    url = f"/api/v1/homes/{owner.home_id}/main-server"
    assert client.get(url).json() == {"linked": False}
    plain = {"main_url": "http://main.example.com", "code": "AB12-CD34-EF56"}
    assert client.post(url, json=plain, headers=csrf(client)).status_code == 422
    wrong = {"main_url": "https://main.example.com", "code": "BAD0-BAD0-BAD0"}
    assert client.post(url, json=wrong, headers=csrf(client)).status_code == 409
    good = {"main_url": "https://main.example.com/", "code": "AB12-CD34-EF56"}
    r = client.post(url, json=good, headers=csrf(client))
    assert r.status_code == 200, r.text
    assert r.json()["linked"] is True and r.json()["main_home_name"] == "Lake"
    assert asked[-1] == (
        "https://main.example.com/api/v1/federation/pair",
        {
            "code": "AB12-CD34-EF56",
            "site_home_id": owner.home_id,
            "site_name": "Home A",
        },
    )
    assert client.delete(url, headers=csrf(client)).json() == {"linked": False}


def test_the_site_answers_on_its_connection(app, owner, make_device):
    make_device(owner.home_id, name="Porch light")
    replies = []

    class Ws:
        async def send_str(self, text):
            replies.append(json.loads(text))

    request = {
        "type": "request",
        "id": "r1",
        "method": "GET",
        "path": f"/api/v1/homes/{owner.home_id}/devices",
        "role": "member",
    }
    run(federation_site._answer(app, owner.home_id, Ws(), json.dumps(request)))
    assert replies[0]["id"] == "r1" and replies[0]["status"] == 200
    assert "Porch light" in replies[0]["body"]


def test_ui_pairing_and_linking(open_page, new_client, owner, monkeypatch, secrets_key):
    from playwright.sync_api import expect

    from tests import test_ui as _ui

    page = open_page()
    _ui.ui_login(page, owner)
    box = _ui.go_settings(page, "admin").get_by_test_id("site-link")
    box.get_by_test_id("site-pairing").click()
    code = box.get_by_test_id("site-pairing-code")
    expect(code).to_have_text(
        __import__("re").compile(r"^[0-9A-F]{4}-[0-9A-F]{4}-[0-9A-F]{4}$")
    )
    expect(box.get_by_test_id("site-main-address")).to_contain_text("http")
    r = new_client().post(
        PAIR,
        json={
            "code": code.inner_text(),
            "site_home_id": "s9",
            "site_name": "Lake site",
        },
    )
    assert r.status_code == 200
    page.reload()
    box = _ui.go_settings(page, "admin").get_by_test_id("site-link")
    expect(box.get_by_test_id("site-link-state")).to_contain_text(
        "devices are at Lake site: its server is not connected right now"
    )
    box.get_by_test_id("site-unlink").click()
    expect(page.get_by_test_id("status")).to_contain_text("other site is unlinked")
    # The other way round: this server linked to a main server.
    monkeypatch.setattr(
        federation_site.requests,
        "post",
        lambda url, json, timeout: FakeAnswer(
            200, {"token": "t", "home_id": "m1", "home_name": "Main home"}
        ),
    )
    box.get_by_test_id("main-server-url").fill("https://main.example.com")
    box.get_by_test_id("main-server-code").fill("AB12-CD34-EF56")
    box.get_by_test_id("main-server-link").click()
    expect(box.get_by_test_id("site-link-state")).to_contain_text(
        "linked to the main server at https://main.example.com (Main home)"
    )


SITE_DEVICES = [
    {
        "id": "l1",
        "name": "Porch",
        "type": "light",
        "room": "Out",
        "online": True,
        "state": {"on": False},
        "network": {"ip": "10.0.0.9"},
    },
    {
        "id": "t1",
        "name": "Hall",
        "type": "thermostat",
        "integration": "cync",
        "room": "Hall",
        "online": True,
        "state": {},
    },
    {
        "id": "tv",
        "name": "Den TV",
        "type": "tv",
        "room": "Den",
        "online": True,
        "state": {"on": True},
    },
]


def fake_site(home_id, loop):
    """A connected site with three devices, answering what it is asked."""
    sent = []

    async def send(text):
        message = json.loads(text)
        sent.append(message)
        path = message["path"].split("/", 5)[-1]
        if message["method"] == "GET" and path == "devices":
            body = SITE_DEVICES
        elif path == "integrations":
            body = [{"id": "cync", "enabled": True}, {"id": "hue", "enabled": False}]
        elif path == "safety-limits":
            body = []
        else:
            body = {"path": path, "role": message["role"], "body": message["body"]}
        answer = {
            "type": "response",
            "id": message["id"],
            "status": 200,
            "content_type": "application/json",
            "body": json.dumps(body),
        }
        asyncio.get_running_loop().call_soon(
            federation.answered, link, json.dumps(answer)
        )

    link = federation.Link(send, loop)
    federation.connected(home_id, link)
    return sent


def test_guests_of_a_home_at_another_site(
    client, new_client, db, owner, make_user, login, csrf, site_loop
):
    from app.guest_access import access_for

    linked(client, new_client, csrf, owner, login)
    sent = fake_site(owner.home_id, site_loop)
    guest = make_user(owner.home_id, role="guest")
    access = access_for(db, owner.home_id, guest.id)
    access.light_power = True
    access.thermostat_ids = '["t1"]'
    db.add(access)
    db.commit()
    g = new_client()
    assert login(g, guest).status_code == 200
    base = f"/api/v1/homes/{owner.home_id}/guest"
    page = g.get(base).json()
    # Only what the guest may use; no addresses.
    assert [d["id"] for d in page["devices"]] == ["l1", "t1"]
    assert "network" not in page["devices"][0]
    assert page["integrations_on"] == ["cync"] and page["access"]["light_power"] is True
    r = g.post(
        f"{base}/devices/l1/command", json={"command": "turn_on"}, headers=csrf(g)
    )
    assert r.status_code == 200
    assert r.json() == {
        "path": "devices/l1/command",
        "role": "member",
        "body": '{"command":"turn_on"}',
    }
    # Refused here, not sent on.
    count = len(sent)
    colour = {"command": "set_color", "payload": {"color": "#ff0000"}}
    assert (
        g.post(f"{base}/devices/l1/command", json=colour, headers=csrf(g)).status_code
        == 403
    )
    off = {"command": "turn_off"}
    assert (
        g.post(f"{base}/devices/tv/command", json=off, headers=csrf(g)).status_code
        == 404
    )
    assert g.get(f"{base}/devices/t1/settings").status_code == 403  # not allowed yet
    assert all(m["method"] == "GET" for m in sent[count:])  # only reads of the list
    # The rest of the home's API is not for guests; cameras only if allowed.
    assert g.get(f"/api/v1/homes/{owner.home_id}/devices").status_code == 403
    cameras = f"/api/v1/homes/{owner.home_id}/cameras"
    assert g.get(cameras).status_code == 403
    access.cameras = True
    access.thermostat_settings = True
    db.commit()
    assert g.get(cameras).json()["role"] == "operator"
    r = g.get(f"{base}/devices/t1/settings")
    assert r.status_code == 200 and r.json()["installer_allowed"] is False
    installer = {"system_type": "heat_pump"}
    assert (
        g.put(
            f"{base}/devices/t1/settings", json=installer, headers=csrf(g)
        ).status_code
        == 403
    )
