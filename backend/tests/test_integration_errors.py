"""Integration logins that fail say why, in plain words: under the form when
a login is saved, and on the integration's row when a background read stops
working (a saved login that expired, a server that went away)."""

import time

import pytest
from cryptography.fernet import Fernet
from playwright.sync_api import expect

from app import cync_home, integration_status, refresh, rheem_home
from app.frigate_home import plain_reason
from app.integrations import frigate
from app.models import Device
from tests import test_ui as _ui
from tests.test_frigate import FakeFrigate, save, turn_on


@pytest.fixture
def frigate_fake(monkeypatch):
    fake = FakeFrigate()
    monkeypatch.setattr(frigate, "connect", fake.connect)
    return fake


@pytest.fixture
def secrets_key(monkeypatch):
    monkeypatch.setenv("SECRETS_KEY", Fernet.generate_key().decode())


@pytest.fixture(autouse=True)
def _no_old_problems():
    integration_status.clear()
    refresh._rheem_read_at.clear()
    refresh._cync_read_at.clear()
    yield
    integration_status.clear()


def problems_url(home_id):
    return f"/api/v1/homes/{home_id}/integrations/problems"


@pytest.mark.parametrize(
    ("kind", "words"),
    [
        ("ConnectionError", "Check the address and port"),
        ("ConnectTimeout", "did not answer within 10 seconds"),
        ("ReadTimeout", "did not answer within 10 seconds"),
        ("SSLError", "untick"),
        ("SomethingNew", "Could not connect to Frigate (SomethingNew)"),
    ],
)
def test_plain_reasons(kind, words):
    assert words in plain_reason(f"could not reach Frigate: {kind}")


def test_other_reasons_are_kept():
    assert plain_reason("Frigate refused the saved login") == (
        "Frigate refused the saved login"
    )


def test_frigate_save_errors(client, owner, login, csrf, frigate_fake, secrets_key):
    assert login(client, owner).status_code == 200
    turn_on(client, csrf, owner.home_id)
    frigate_fake.fail = frigate.FrigateError("could not reach Frigate: ConnectionError")
    r = save(client, csrf, owner.home_id)
    assert r.status_code == 502
    assert r.json()["detail"].startswith("Could not connect to Frigate.")

    frigate_fake.fail = frigate.FrigateNotFound("not found in Frigate")
    r = save(client, csrf, owner.home_id)
    assert r.status_code == 400 and "not as Frigate" in r.json()["detail"]

    r = save(client, csrf, owner.home_id, password="wrong")
    assert r.status_code == 400 and "refused" in r.json()["detail"]

    r = save(client, csrf, owner.home_id, url="https://192.168.1.20:8971/api")
    assert r.status_code == 422
    assert "must end at the port" in r.text
    r = save(client, csrf, owner.home_id, url="frigate.lan")
    assert r.status_code == 422 and "must look like" in r.text


def _heater(db, make_device, home_id):
    device_id = make_device(home_id, device_type="water_heater", name="Tank")
    db.get(Device, device_id).integration = rheem_home.INTEGRATION
    db.commit()


def test_background_problem_shown_and_cleared(
    client, new_client, db, owner, make_user, make_device, login, monkeypatch
):
    _heater(db, make_device, owner.home_id)

    def broken(db, home_id):
        raise rheem_home.RheemUnavailable(
            502, "EcoNet refused the saved email or password"
        )

    monkeypatch.setattr(rheem_home, "sync", broken)
    assert refresh.refresh_rheem(db, owner.home_id, now=1000.0) is False
    assert login(client, owner).status_code == 200
    body = client.get(problems_url(owner.home_id)).json()
    assert (
        body["rheem_econet"]["reason"] == "EcoNet refused the saved email or password"
    )

    # Members do not manage integrations.
    member = make_user(owner.home_id, role="member")
    member_client = new_client()
    assert login(member_client, member).status_code == 200
    assert member_client.get(problems_url(owner.home_id)).status_code == 403
    # Other homes see nothing of it.
    assert new_client().get(problems_url(owner.home_id)).status_code == 401

    monkeypatch.setattr(rheem_home, "sync", lambda db, home_id: {"created": 0})
    assert refresh.refresh_rheem(db, owner.home_id, now=2000.0) is True
    assert client.get(problems_url(owner.home_id)).json() == {}


def test_cync_background_problem(db, owner, monkeypatch):
    monkeypatch.setattr(refresh, "integration_enabled", lambda db, home, name: True)

    def broken(db, home_id):
        raise cync_home.CyncUnavailable(502, "Cync refused the login: log in again")

    monkeypatch.setattr(cync_home, "sync", broken)
    assert refresh.refresh_cync(db, owner.home_id, now=1000.0) is False
    assert integration_status.for_home(owner.home_id)["cync"]["reason"].startswith(
        "Cync refused"
    )
    assert integration_status.for_home("another home") == {}


def test_ui_frigate_error_under_the_form(open_page, owner, frigate_fake, secrets_key):
    page = open_page()
    _ui.ui_login(page, owner)
    section = _ui.go_settings(page, "integrations")
    section.locator(
        '[data-testid="integration-row"][data-integration="frigate"]'
    ).get_by_test_id("integration-toggle").check()
    panel = page.get_by_test_id("frigate-server")
    note = panel.get_by_test_id("frigate-note")
    # Not a URL at all: the server says what it should look like.
    panel.get_by_test_id("frigate-url").fill("frigate.lan")
    panel.get_by_test_id("frigate-save").click()
    expect(note).to_contain_text("must look like http://192.168.1.20:5000")
    expect(note).to_have_attribute("data-kind", "error")
    expect(note).not_to_contain_text("Value error")
    # A server that does not answer.
    frigate_fake.fail = frigate.FrigateError("could not reach Frigate: ConnectTimeout")
    panel.get_by_test_id("frigate-url").fill("http://192.168.1.20:5000")
    panel.get_by_test_id("frigate-save").click()
    expect(note).to_contain_text("did not answer within 10 seconds")
    expect(page.get_by_test_id("status")).to_contain_text("did not answer")
    # Then a working one: the note clears and it says connected.
    panel.get_by_test_id("frigate-save").click()
    expect(page.get_by_test_id("status")).to_contain_text("Frigate connected")
    expect(page.get_by_test_id("frigate-configured")).to_contain_text("Connected to")


def test_ui_problem_on_the_integration_row(
    open_page, db, owner, make_device, login, client, csrf
):
    _heater(db, make_device, owner.home_id)
    assert login(client, owner).status_code == 200
    r = client.put(
        f"/api/v1/homes/{owner.home_id}/integrations/rheem_econet",
        json={"enabled": True},
        headers=csrf(client),
    )
    assert r.status_code == 200, r.text
    integration_status.failed(
        owner.home_id, "rheem_econet", "EcoNet refused the saved email or password"
    )
    page = open_page()
    _ui.ui_login(page, owner, owner.totp.at(time.time() + 30))
    section = _ui.go_settings(page, "integrations")
    row = section.locator(
        '[data-testid="integration-row"][data-integration="rheem_econet"]'
    )
    expect(row.get_by_test_id("integration-problem")).to_have_text(
        "Connection problem: EcoNet refused the saved email or password"
    )
    other = section.locator('[data-testid="integration-row"][data-integration="cync"]')
    expect(other.get_by_test_id("integration-problem")).to_have_count(0)
