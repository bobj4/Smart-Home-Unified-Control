"""Per-device safety limits; the email server and recovery codes by email.
Written by the reviewer. Do not edit, skip, mark or delete these tests. If one
looks wrong, stop and report the test name and its full failure output instead
of changing it. No real email is sent: app.mailer.send is replaced.
"""

import re

import pytest
from cryptography.fernet import Fernet
from playwright.sync_api import expect

from app import mailer
from app.models import SystemSettings
from tests import test_admin as _admin
from tests import test_safety_limits as _limits
from tests import test_ui as _ui

go_settings, ui_login = _ui.go_settings, _ui.ui_login
set_policy, recover = _admin.set_policy, _admin.recover
THERMOSTAT_F = _limits.THERMOSTAT_F


@pytest.fixture
def secrets_key(monkeypatch):
    monkeypatch.setenv("SECRETS_KEY", Fernet.generate_key().decode())


@pytest.fixture
def outbox(monkeypatch):
    sent = []
    monkeypatch.setattr(
        mailer, "send", lambda row, to, subject, body: sent.append((to, subject, body))
    )
    return sent


# ------------------------------------------------------------ per-device limits


def test_device_limits_narrow_the_home_limits(
    client, new_client, owner, make_user, make_device, login, csrf
):
    home = owner.home_id
    hall = make_device(home, device_type="thermostat", name="Hall")
    den = make_device(home, device_type="thermostat", name="Den")
    assert login(client, owner).status_code == 200
    url = f"/api/v1/homes/{home}/devices/{hall}/limits"
    body = {"min_temperature": 65, "max_temperature": 72}
    assert client.put(url, json=body, headers=csrf(client)).status_code == 409
    assert (
        client.put(
            _limits.limits_url(home, "thermostat"),
            json=THERMOSTAT_F,
            headers=csrf(client),
        ).status_code
        == 200
    )
    for bad in (
        {"min_temperature": 50},
        {"max_temperature": 90},
        {"min_temperature": 75, "max_temperature": 70},
    ):
        assert client.put(url, json=bad, headers=csrf(client)).status_code == 422, bad
    r = client.put(url, json=body, headers=csrf(client))
    assert r.status_code == 200, r.text
    assert r.json()["limits"] == {"min_temperature": 65.0, "max_temperature": 72.0}
    assert _limits.command(client, csrf, home, hall, 75).status_code == 422
    assert _limits.command(client, csrf, home, hall, 70).status_code == 200
    assert (
        _limits.command(client, csrf, home, den, 78).status_code == 200
    )  # type limits
    operator = make_user(home, role="operator")
    o = new_client()
    assert login(o, operator).status_code == 200
    assert o.put(url, json=body, headers=csrf(o)).status_code == 403
    cleared = client.put(url, json={}, headers=csrf(client))
    assert cleared.json()["limits"] == {
        "min_temperature": None,
        "max_temperature": None,
    }


def test_ui_device_limits(open_page, client, db, owner, make_device, login, csrf):
    hall = make_device(owner.home_id, device_type="thermostat", name="Hall")
    _ui.recommended_limits(db, owner.home_id)
    page = open_page()
    ui_login(page, owner)
    section = go_settings(page, "safety")
    row = section.locator(f'[data-testid="device-limits-row"][data-device-id="{hall}"]')
    row.get_by_test_id("device-limits-min").fill("64")
    row.get_by_test_id("device-limits-max").fill("74")
    row.get_by_test_id("device-limits-save").click()
    expect(page.get_by_test_id("status")).to_have_attribute("data-kind", "success")
    page.get_by_test_id("nav-devices").click()
    expect(page.get_by_test_id("temp-limits")).to_contain_text("64")
    expect(page.get_by_test_id("temp-limits")).to_contain_text("74")


# ------------------------------------------------------------ email server


SERVER = {
    "host": "smtp.example.com",
    "port": 587,
    "security": "starttls",
    "username": "home@example.com",
    "password": "smtp secret 1",
    "sender": "home@example.com",
}


def test_admin_sets_up_email_server(
    client, new_client, db, owner, make_user, login, csrf, secrets_key, outbox
):
    operator = make_user(owner.home_id, role="operator")
    o = new_client()
    assert login(o, operator).status_code == 200
    assert o.get("/api/v1/admin/email").status_code == 403
    assert login(client, owner).status_code == 200
    r = client.put("/api/v1/admin/email", json=SERVER, headers=csrf(client))
    assert r.status_code == 200, r.text
    assert r.json()["password_saved"] is True and "smtp secret" not in r.text
    row = db.get(SystemSettings, 1)
    db.refresh(row)
    assert "smtp secret" not in (row.smtp_password or "")
    keep = {k: v for k, v in SERVER.items() if k != "password"}
    assert client.put("/api/v1/admin/email", json=keep, headers=csrf(client)).json()[
        "password_saved"
    ]  # left out: kept
    r = client.post(
        "/api/v1/admin/email/test", json={"to": "me@example.com"}, headers=csrf(client)
    )
    assert r.status_code == 200
    assert outbox[-1][0] == "me@example.com"
    assert (
        client.delete("/api/v1/admin/email", headers=csrf(client)).json()["configured"]
        is False
    )


def test_recovery_code_by_email(
    client, new_client, owner, make_user, login, csrf, secrets_key, outbox
):
    member = make_user(owner.home_id, role="member")
    guest = new_client()
    body = {"login": member.email}
    assert (
        guest.post("/api/v1/recover/email", json=body).status_code == 404
    )  # not set up
    assert login(client, owner).status_code == 200
    assert (
        client.put("/api/v1/admin/email", json=SERVER, headers=csrf(client)).status_code
        == 200
    )
    assert (
        guest.post("/api/v1/recover/email", json=body).status_code == 404
    )  # recovery off
    assert set_policy(client, csrf, allow_recovery=True).status_code == 200
    assert guest.get("/api/v1/login-options").json()["email_recovery"] is True
    r = guest.post("/api/v1/recover/email", json={"login": member.email.upper()})
    assert r.json() == {"sent": True}
    to, _subject, text = outbox[-1]
    assert to == member.email
    code = re.search(r"[A-Z0-9]{4}-[A-Z0-9]{4}-[A-Z0-9]{4}-[A-Z0-9]{4}", text).group(0)
    assert recover(guest, member.email, code).status_code == 200
    assert recover(guest, member.email, code).status_code == 404  # used once
    sent = len(outbox)
    assert guest.post(
        "/api/v1/recover/email", json={"login": "nobody@example.com"}
    ).json() == {"sent": True}
    assert len(outbox) == sent  # same answer, nothing sent
    for _ in range(2):
        guest.post("/api/v1/recover/email", json=body)
    assert guest.post("/api/v1/recover/email", json=body).status_code == 429


def test_ui_recover_page_offers_email(
    open_page, client, owner, login, csrf, secrets_key, outbox
):
    assert login(client, owner).status_code == 200
    client.put("/api/v1/admin/email", json=SERVER, headers=csrf(client))
    set_policy(client, csrf, allow_recovery=True)
    page = open_page()
    page.get_by_test_id("recover-link").click()
    page.get_by_test_id("recover-login").fill(owner.email)
    page.get_by_test_id("recover-email-send").click()
    expect(page.get_by_test_id("recover-email-sent")).to_be_visible()
    assert outbox and outbox[-1][0] == owner.email
