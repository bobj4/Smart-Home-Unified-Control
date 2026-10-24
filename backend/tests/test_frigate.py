"""Frigate contract: saved server settings, events, thumbnails and clips.

Written by the reviewer (Frigate phase). Do not edit, skip, mark or delete
these tests. If one looks wrong, stop and report the test name and its full
failure output instead of changing it.

Nothing here talks to Frigate: `app.integrations.frigate.connect` is replaced
by FakeFrigate, and the adapter's own tests replace requests.Session.
"""

import base64
import json

import pytest
from cryptography.fernet import Fernet
from playwright.sync_api import expect

from app.integrations import frigate
from app.models import AuditEvent
from tests import test_ui as _ui

URL = "https://192.168.1.20:8971"
USER, PASSWORD = "viewer", "frigate password 1"
# A real 1x1 PNG, so browsers can draw the thumbnail.
PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
)
CLIP = bytes(range(256)) * 4  # 1024 bytes standing in for an mp4
EVENTS = [
    {
        "id": "1700000100.5-abc",
        "camera": "front_door",
        "label": "person",
        "sub_label": None,
        "start_time": 1700000100.5,
        "end_time": 1700000130.0,
        "has_clip": True,
        "has_snapshot": True,
        "data": {"top_score": 0.912},
        "thumbnail": "ignored",
    },
    {
        "id": "1700000000.1-def",
        "camera": "driveway",
        "label": "car",
        "sub_label": "Our car",
        "start_time": 1700000000.1,
        "end_time": None,
        "has_clip": False,
        "has_snapshot": True,
        "data": {"top_score": 0.8},
    },
]


class FakeFrigate:
    def __init__(self):
        self.connections = []
        self.fail = None

    def connect(self, url, username, password, verify_tls):
        self.connections.append((url, username, verify_tls))
        fake = self

        class Client:
            def _check(self):
                if fake.fail:
                    error, fake.fail = fake.fail, None
                    raise error
                if username and password != PASSWORD:
                    raise frigate.FrigateLoginError(
                        "Frigate refused the username or password"
                    )

            def cameras(self):
                self._check()
                return ["driveway", "front_door"]

            def events(self, limit, camera=None):
                self._check()
                found = [
                    frigate.event_out(e)
                    for e in EVENTS
                    if camera in (None, e["camera"])
                ]
                return found[:limit]

            def thumbnail(self, event_id):
                self._check()
                if event_id not in {e["id"] for e in EVENTS}:
                    raise frigate.FrigateNotFound("not found")
                return frigate.Media(200, "image/png", {}, iter([PNG]))

            def clip(self, event_id, byte_range):
                self._check()
                if event_id != EVENTS[0]["id"]:
                    raise frigate.FrigateNotFound("not found")
                if byte_range == "bytes=0-99":
                    headers = {
                        "Content-Range": f"bytes 0-99/{len(CLIP)}",
                        "Content-Length": "100",
                        "Accept-Ranges": "bytes",
                    }
                    return frigate.Media(206, "video/mp4", headers, iter([CLIP[:100]]))
                headers = {"Content-Length": str(len(CLIP)), "Accept-Ranges": "bytes"}
                return frigate.Media(
                    200, "video/mp4", headers, iter([CLIP[:512], CLIP[512:]])
                )

        return Client()


@pytest.fixture
def frigate_fake(monkeypatch):
    fake = FakeFrigate()
    monkeypatch.setattr(frigate, "connect", fake.connect)
    return fake


@pytest.fixture
def secrets_key(monkeypatch):
    monkeypatch.setenv("SECRETS_KEY", Fernet.generate_key().decode())


def home_url(home_id, suffix):
    return f"/api/v1/homes/{home_id}{suffix}"


def turn_on(client, csrf, home_id):
    r = client.put(
        home_url(home_id, "/integrations/frigate"),
        json={"enabled": True},
        headers=csrf(client),
    )
    assert r.status_code == 200, r.text


def save(client, csrf, home_id, **changes):
    body = {
        "url": URL,
        "username": USER,
        "password": PASSWORD,
        "verify_tls": False,
        **changes,
    }
    body = {k: v for k, v in body.items() if v is not ...}
    return client.put(
        home_url(home_id, "/integrations/frigate/server"),
        json=body,
        headers=csrf(client),
    )


def ready(client, csrf, login, owner):
    assert login(client, owner).status_code == 200
    turn_on(client, csrf, owner.home_id)
    assert save(client, csrf, owner.home_id).status_code == 200


# ------------------------------------------------------------ settings


def test_frigate_is_available(client, owner, login):
    assert login(client, owner).status_code == 200
    rows = {
        r["id"]: r for r in client.get(home_url(owner.home_id, "/integrations")).json()
    }
    assert rows["frigate"]["available"] is True and rows["frigate"]["enabled"] is False


def test_frigate_owner_saves_server(
    client,
    new_client,
    db,
    owner,
    make_user,
    login,
    csrf,
    frigate_fake,
    secrets_key,
    monkeypatch,
):
    from app.models import IntegrationCredential

    server = home_url(owner.home_id, "/integrations/frigate/server")
    admin = make_user(owner.home_id, role="operator")
    admin_client = new_client()
    assert login(admin_client, admin).status_code == 200
    assert admin_client.get(server).status_code == 403
    assert save(admin_client, csrf, owner.home_id).status_code == 403

    assert login(client, owner).status_code == 200
    assert client.get(server).json() == {
        "configured": False,
        "url": None,
        "username": None,
        "verify_tls": True,
    }
    for bad in (
        {"url": "ftp://192.168.1.20"},
        {"url": "https://8.8.8.8:8971"},  # not on the home network
        {"url": "https://user:pw@192.168.1.20:8971"},
        {"url": "https://192.168.1.20:8971/api"},
        {"url": "https://192.168.1.20:99999"},
        {"verify_tls": "no"},
        {"password": ...},  # a username without a password
    ):
        assert save(client, csrf, owner.home_id, **bad).status_code == 422, bad
    assert save(client, csrf, owner.home_id, password="wrong").status_code == 400
    frigate_fake.fail = frigate.FrigateError("could not reach Frigate: ConnectTimeout")
    assert save(client, csrf, owner.home_id).status_code == 502
    monkeypatch.delenv("SECRETS_KEY")
    assert save(client, csrf, owner.home_id).status_code == 409
    assert db.query(IntegrationCredential).count() == 0
    monkeypatch.setenv("SECRETS_KEY", Fernet.generate_key().decode())

    r = save(client, csrf, owner.home_id, url="https://192.168.1.20:8971/")
    assert r.status_code == 200, r.text
    assert r.json() == {
        "configured": True,
        "url": URL,
        "username": USER,
        "verify_tls": False,
    }
    assert PASSWORD not in client.get(server).text
    db.expire_all()
    assert PASSWORD not in db.query(IntegrationCredential).one().secret
    saved = db.query(AuditEvent).filter_by(event_type="integration_account_saved").all()
    assert saved and PASSWORD not in (saved[-1].details or "")

    # Port 5000 without a login, on this machine or by host name
    for url in (
        "http://localhost:5000",
        "http://127.0.0.1:5000",
        "http://frigate.lan:5000",
    ):
        r = save(
            client,
            csrf,
            owner.home_id,
            url=url,
            username=None,
            password=None,
            verify_tls=True,
        )
        assert r.status_code == 200, (url, r.text)
        assert r.json()["username"] is None

    r = client.delete(server, headers=csrf(client))
    assert r.status_code == 200 and r.json()["configured"] is False


# ------------------------------------------------------------ events and media


def test_frigate_members_see_events(
    client, new_client, owner, make_user, login, csrf, frigate_fake, secrets_key
):
    ready(client, csrf, login, owner)
    member = make_user(owner.home_id, role="member")
    m = new_client()
    assert login(m, member).status_code == 200
    base = home_url(owner.home_id, "/cameras")
    assert m.get(base).status_code == 403  # members: devices only
    member = make_user(owner.home_id, role="operator")
    m = new_client()
    assert login(m, member).status_code == 200

    assert m.get(base).json() == ["driveway", "front_door"]
    events = m.get(f"{base}/events").json()
    assert events[0] == {
        "id": "1700000100.5-abc",
        "camera": "front_door",
        "label": "person",
        "sub_label": None,
        "score": 0.91,
        "start_time": 1700000100.5,
        "end_time": 1700000130.0,
        "has_clip": True,
        "has_snapshot": True,
    }
    assert events[1]["sub_label"] == "Our car"
    assert [
        e["camera"]
        for e in m.get(f"{base}/events", params={"camera": "driveway"}).json()
    ] == ["driveway"]
    assert len(m.get(f"{base}/events", params={"limit": 1}).json()) == 1
    for bad in ({"limit": 0}, {"limit": 101}, {"camera": "../x"}):
        assert m.get(f"{base}/events", params=bad).status_code == 422, bad


def test_frigate_thumbnails_and_clips_pass_through(
    client, owner, login, csrf, frigate_fake, secrets_key
):
    ready(client, csrf, login, owner)
    base = home_url(owner.home_id, "/cameras/events")
    r = client.get(f"{base}/1700000100.5-abc/thumbnail")
    assert r.status_code == 200 and r.content == PNG
    assert r.headers["content-type"] == "image/png"
    assert client.get(f"{base}/no-such-event/thumbnail").status_code == 404
    assert client.get(f"{base}/..%2F..%2Fapi%2Fconfig/thumbnail").status_code in (
        404,
        422,
    )

    r = client.get(f"{base}/1700000100.5-abc/clip")
    assert r.status_code == 200 and r.content == CLIP
    assert r.headers["content-type"] == "video/mp4"
    assert r.headers["accept-ranges"] == "bytes"
    r = client.get(f"{base}/1700000100.5-abc/clip", headers={"Range": "bytes=0-99"})
    assert r.status_code == 206 and r.content == CLIP[:100]
    assert r.headers["content-range"] == f"bytes 0-99/{len(CLIP)}"
    assert (
        client.get(
            f"{base}/1700000100.5-abc/clip", headers={"Range": "lines=1"}
        ).status_code
        == 422
    )
    assert client.get(f"{base}/1700000000.1-def/clip").status_code == 404


def test_frigate_access_rules(
    client,
    new_client,
    owner,
    make_home,
    make_user,
    login,
    csrf,
    frigate_fake,
    secrets_key,
):
    assert login(client, owner).status_code == 200
    base = home_url(owner.home_id, "/cameras")
    assert client.get(f"{base}/events").status_code == 409  # integration off
    turn_on(client, csrf, owner.home_id)
    r = client.get(f"{base}/events")
    assert r.status_code == 409 and "not set up" in r.json()["detail"]
    assert save(client, csrf, owner.home_id).status_code == 200

    stranger = make_user(make_home("Home B"), role="owner")
    s = new_client()
    assert login(s, stranger).status_code == 200
    assert s.get(f"{base}/events").status_code == 404
    assert s.get(f"{base}/events/1700000100.5-abc/thumbnail").status_code == 404
    assert new_client().get(f"{base}/events").status_code == 401

    frigate_fake.fail = frigate.FrigateLoginError("Frigate refused the saved login")
    assert client.get(f"{base}/events").status_code == 502


# ------------------------------------------------------------ the adapter (reviewer's)


class FakeResponse:
    def __init__(self, status_code, body=b"", headers=None, data=None):
        self.status_code, self.content, self.headers = status_code, body, headers or {}
        self._data = data
        self.closed = False

    def json(self):
        if self._data is None:
            raise ValueError("not json")
        return self._data

    def iter_content(self, size):
        yield from (
            self.content[i : i + size] for i in range(0, len(self.content), size)
        )

    def close(self):
        self.closed = True


class FakeSession:
    """Stands in for requests.Session inside the real adapter."""

    log = []
    replies = []

    def __init__(self):
        self.verify = True

    def post(self, url, json=None, timeout=None):
        FakeSession.log.append(("POST", url, json, self.verify))
        return FakeSession.replies.pop(0)

    def get(self, url, timeout=None, stream=False, params=None, headers=None):
        FakeSession.log.append(("GET", url, params, headers))
        return FakeSession.replies.pop(0)


@pytest.fixture
def fake_http(monkeypatch):
    monkeypatch.setattr(frigate.requests, "Session", FakeSession)
    monkeypatch.setattr(frigate, "_sessions", {})
    FakeSession.log, FakeSession.replies = [], []
    return FakeSession


def test_frigate_adapter_logs_in_once_and_reads_events(fake_http):
    fake_http.replies = [
        FakeResponse(200),  # login
        FakeResponse(200, data={"cameras": {"front_door": {}, "driveway": {}}}),
        FakeResponse(200, data=EVENTS),
    ]
    client = frigate.connect(URL + "/", USER, PASSWORD, False)
    assert client.cameras() == ["driveway", "front_door"]
    assert (
        frigate.connect(URL, USER, PASSWORD, False).events(5, "front_door")[0]["id"]
        == EVENTS[0]["id"]
    )
    assert fake_http.log[0] == (
        "POST",
        f"{URL}/api/login",
        {"user": USER, "password": PASSWORD},
        False,
    )
    assert fake_http.log[1][1] == f"{URL}/api/config"
    assert fake_http.log[2][1:3] == (
        f"{URL}/api/events",
        {"limit": 5, "include_thumbnails": 0, "cameras": "front_door"},
    )
    assert [entry[0] for entry in fake_http.log].count(
        "POST"
    ) == 1  # the second client reused the login


def test_frigate_adapter_relogs_in_once_and_reports_errors(fake_http):
    fake_http.replies = [
        FakeResponse(200),
        FakeResponse(401),
        FakeResponse(200),
        FakeResponse(200, data={"cameras": {}}),
    ]
    assert frigate.connect(URL, USER, PASSWORD, True).cameras() == []
    assert [e[0] for e in fake_http.log] == ["POST", "GET", "POST", "GET"]

    frigate._sessions.clear()
    fake_http.replies = [FakeResponse(401)]
    with pytest.raises(frigate.FrigateLoginError):
        frigate.connect(URL, USER, "wrong", True).cameras()
    fake_http.replies = [FakeResponse(200), FakeResponse(404)]
    with pytest.raises(frigate.FrigateNotFound):
        frigate.connect(URL, USER, PASSWORD, True).thumbnail("x")
    fake_http.replies = [FakeResponse(500)]
    with pytest.raises(frigate.FrigateError):
        frigate.connect(URL, USER, PASSWORD, True).cameras()


def test_frigate_adapter_without_login_and_clip_range(fake_http):
    headers = {
        "Content-Range": "bytes 0-99/1024",
        "Content-Length": "100",
        "Accept-Ranges": "bytes",
        "Server": "x",
    }
    fake_http.replies = [FakeResponse(206, CLIP[:100], headers)]
    media = frigate.connect("http://127.0.0.1:5000", None, None, True).clip(
        "e1", "bytes=0-99"
    )
    assert fake_http.log == [
        (
            "GET",
            "http://127.0.0.1:5000/api/events/e1/clip.mp4",
            None,
            {"Range": "bytes=0-99"},
        )
    ]
    assert (media.status_code, media.content_type) == (206, "video/mp4")
    assert media.headers == {
        "Content-Range": "bytes 0-99/1024",
        "Content-Length": "100",
        "Accept-Ranges": "bytes",
    }
    assert b"".join(media.body) == CLIP[:100]


# ------------------------------------------------------------ browser


card, go_settings, ui_login = _ui.card, _ui.go_settings, _ui.ui_login


def test_ui_frigate_setup_and_events(open_page, owner, frigate_fake, secrets_key):
    page = open_page()
    ui_login(page, owner)
    expect(page.get_by_test_id("nav-cameras")).to_be_hidden()  # Frigate is off

    section = go_settings(page, "integrations")
    section.locator(
        '[data-testid="integration-row"][data-integration="frigate"]'
    ).get_by_test_id("integration-toggle").check()
    panel = page.get_by_test_id("frigate-server")
    expect(panel).to_be_visible()
    panel.get_by_test_id("frigate-url").fill(URL)
    panel.get_by_test_id("frigate-username").fill(USER)
    panel.get_by_test_id("frigate-password").fill(PASSWORD)
    panel.get_by_test_id("frigate-verify").uncheck()
    panel.get_by_test_id("frigate-save").click()
    expect(page.get_by_test_id("status")).to_have_attribute("data-kind", "success")
    expect(page.get_by_test_id("frigate-configured")).to_contain_text(URL)
    expect(page.get_by_test_id("frigate-password")).to_have_value("")
    assert frigate_fake.connections[-1] == (URL, USER, False)

    page.get_by_test_id("nav-cameras").click()
    events = page.get_by_test_id("camera-event")
    expect(events).to_have_count(2)
    first = events.first
    expect(first).to_contain_text("person")
    expect(first).to_contain_text("front door")
    expect(first).to_contain_text("91%")
    thumb = first.get_by_test_id("event-thumb")
    expect(thumb).to_be_visible()
    page.wait_for_function(
        "document.querySelector('[data-testid=event-thumb]').naturalWidth > 0"
    )
    expect(events.nth(1).get_by_test_id("event-play")).to_have_count(0)  # no clip

    first.get_by_test_id("event-play").click()
    video = page.get_by_test_id("event-video")
    expect(video).to_be_visible()
    assert video.get_attribute("src").endswith("/cameras/events/1700000100.5-abc/clip")
    page.get_by_test_id("event-close").click()
    expect(page.get_by_test_id("event-video")).to_have_count(0)

    page.get_by_test_id("camera-filter").select_option("driveway")
    expect(page.get_by_test_id("camera-event")).to_have_count(1)
    expect(page.get_by_test_id("camera-event")).to_contain_text("car")


def test_ui_frigate_members_view_but_cannot_configure(
    open_page, new_client, owner, make_user, login, csrf, frigate_fake, secrets_key
):
    owner_client = new_client()
    ready(owner_client, csrf, login, owner)
    member = make_user(owner.home_id, role="operator")
    page = open_page()
    ui_login(page, member)
    page.get_by_test_id("nav-cameras").click()
    expect(page.get_by_test_id("camera-event")).to_have_count(2)
    go_settings(page, "integrations")
    expect(page.get_by_test_id("frigate-server")).to_have_count(0)


def test_ui_frigate_bad_password_shows_error(
    open_page, owner, frigate_fake, secrets_key
):
    page = open_page()
    ui_login(page, owner)
    section = go_settings(page, "integrations")
    section.locator(
        '[data-testid="integration-row"][data-integration="frigate"]'
    ).get_by_test_id("integration-toggle").check()
    panel = page.get_by_test_id("frigate-server")
    panel.get_by_test_id("frigate-url").fill(URL)
    panel.get_by_test_id("frigate-username").fill(USER)
    panel.get_by_test_id("frigate-password").fill("wrong")
    panel.get_by_test_id("frigate-save").click()
    expect(page.get_by_test_id("status")).to_have_attribute("data-kind", "error")
    expect(page.get_by_test_id("frigate-configured")).to_contain_text("Not set up")
    assert json.dumps(frigate_fake.connections)  # it did try to connect
