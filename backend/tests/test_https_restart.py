# ruff: noqa: F811 (the secrets_key fixture, shared with test_https)
"""Restart now / Restart later after HTTPS is switched (a popup that does
not cover the page). The app only restarts itself inside a container, where
the restart policy starts it again. Nothing here stops the test server."""

from playwright.sync_api import expect

from app.models import AuditEvent
from app.routes import https_admin
from tests.test_https import make_pair, secrets_key  # noqa: F401
from tests.test_ui import go_settings, ui_login

URL = "/api/v1/admin/https/restart"


class NowTimer:
    """threading.Timer that runs at once (no waiting in tests)."""

    def __init__(self, seconds, action):
        self.action = action

    def start(self):
        self.action()


def test_restart_only_in_a_container(
    client, db, owner, make_user, new_client, login, csrf, monkeypatch
):
    stopped = []
    monkeypatch.setattr(https_admin, "_stop_server", lambda: stopped.append(1))
    monkeypatch.setattr(https_admin.threading, "Timer", NowTimer)
    assert login(client, owner).status_code == 200
    monkeypatch.setattr(https_admin, "restart_available", lambda: False)
    assert client.get(URL).json() == {"available": False}
    r = client.post(URL, json={}, headers=csrf(client))
    assert r.status_code == 409 and "smarthome restart" in r.json()["detail"]
    assert stopped == []
    monkeypatch.setattr(https_admin, "restart_available", lambda: True)
    r = client.post(URL, json={}, headers=csrf(client))
    assert r.status_code == 200 and r.json()["restarting"] is True
    assert stopped == [1]
    db.expire_all()
    assert (
        db.query(AuditEvent).filter_by(event_type="server_restart_requested").count()
        == 1
    )
    member = make_user(owner.home_id, role="operator")
    m = new_client()
    assert login(m, member).status_code == 200
    assert m.post(URL, json={}, headers=csrf(m)).status_code == 403
    assert stopped == [1]
    assert client.post(URL, json={}).status_code == 403  # no CSRF token


def test_container_markers(tmp_path, monkeypatch):
    monkeypatch.setattr(https_admin, "CONTAINER_MARKERS", (str(tmp_path / "x"),))
    assert https_admin.restart_available() is False
    (tmp_path / "x").write_text("")
    assert https_admin.restart_available() is True


def _upload_and_switch(page, tmp_path):
    cert, key = make_pair("lights.home.arpa")
    (tmp_path / "cert.pem").write_text(cert)
    (tmp_path / "key.pem").write_text(key)
    box = go_settings(page, "admin").get_by_test_id("https-box")
    box.get_by_test_id("https-cert-file").set_input_files(str(tmp_path / "cert.pem"))
    box.get_by_test_id("https-key-file").set_input_files(str(tmp_path / "key.pem"))
    box.get_by_test_id("https-upload").click()
    expect(box.get_by_test_id("https-certificate")).to_contain_text("lights.home.arpa")
    box.get_by_test_id("https-toggle").check()
    return box


def test_ui_restart_now_or_later(open_page, owner, secrets_key, tmp_path, monkeypatch):
    stopped = []
    monkeypatch.setattr(https_admin, "restart_available", lambda: True)
    monkeypatch.setattr(https_admin, "_stop_server", lambda: stopped.append(1))
    monkeypatch.setattr(https_admin.threading, "Timer", NowTimer)
    page = open_page()
    ui_login(page, owner)
    page.evaluate("window.smartHomeApp.restartMoveMs = 600000")
    box = _upload_and_switch(page, tmp_path)
    popup = page.get_by_test_id("restart-popup")
    expect(popup).to_be_visible()
    expect(popup.get_by_test_id("restart-popup-text")).to_contain_text("HTTPS is on")
    popup.get_by_test_id("restart-later").click()
    expect(popup).to_be_hidden()
    assert stopped == []
    box.get_by_test_id("https-restart").click()  # later, from the HTTPS section
    popup.get_by_test_id("restart-now").click()
    # This page is plain HTTP: it moves to the HTTPS address.
    expect(popup.get_by_test_id("restart-target")).to_contain_text("https://")
    assert stopped == [1]


def test_ui_outside_a_container(open_page, owner, secrets_key, tmp_path, monkeypatch):
    monkeypatch.setattr(https_admin, "restart_available", lambda: False)
    page = open_page()
    ui_login(page, owner)
    _upload_and_switch(page, tmp_path)
    popup = page.get_by_test_id("restart-popup")
    expect(popup.get_by_test_id("restart-popup-text")).to_contain_text(
        "deploy/linux/smarthome restart"
    )
    expect(popup.get_by_test_id("restart-now")).to_be_hidden()
    popup.get_by_test_id("restart-later").click()
    expect(popup).to_be_hidden()
