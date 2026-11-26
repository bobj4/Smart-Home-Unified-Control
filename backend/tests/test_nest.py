"""Google Nest through Device Access: signing in (Google's page, the
address pasted back), the devices it finds, thermostat commands (Celsius to
Google, whole degrees F here), camera and doorbell events from Pub/Sub, and
the settings panel with its paid-registration warning. Nothing talks to
Google: app.integrations.nest is replaced."""

import base64
import json
from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qs, urlsplit

import pytest
from playwright.sync_api import expect

from app import alerts, features, nest_home, refresh
from app.integrations import nest
from app.models import Device
from app.safety import apply_recommended
from tests import test_alerts as _alerts
from tests import test_cync as _cync
from tests import test_package1 as _package1
from tests import test_ui as _ui

secrets_key, outbox, pushed = _package1.secrets_key, _package1.outbox, _alerts.pushed
PROJECT = "a1b2c3d4-0000-1111-2222-333344445555"
CLIENT = "123-abc.apps.googleusercontent.com"
SUBSCRIPTION = "projects/my-home-123/subscriptions/nest-events"
T = nest.TRAIT


def thermostat_item(mode="HEAT", eco="OFF", heat=20.0, cool=24.0, hvac="HEATING"):
    return {
        "name": f"enterprises/{PROJECT}/devices/THERMO1",
        "type": "sdm.devices.types.THERMOSTAT",
        "traits": {
            f"{T}Info": {"customName": ""},
            f"{T}Connectivity": {"status": "ONLINE"},
            f"{T}Humidity": {"ambientHumidityPercent": 41.6},
            f"{T}Temperature": {"ambientTemperatureCelsius": 21.1},
            f"{T}ThermostatMode": {
                "availableModes": ["HEAT", "COOL", "HEATCOOL", "OFF"],
                "mode": mode,
            },
            f"{T}ThermostatEco": {
                "availableModes": ["OFF", "MANUAL_ECO"],
                "mode": eco,
                "heatCelsius": 15.5,
                "coolCelsius": 26.6,
            },
            f"{T}ThermostatHvac": {"status": hvac},
            f"{T}ThermostatTemperatureSetpoint": {
                "heatCelsius": heat,
                "coolCelsius": cool,
            },
            f"{T}Fan": {"timerMode": "OFF"},
        },
        "parentRelations": [{"parent": "x", "displayName": "Hallway"}],
    }


DOORBELL = {
    "name": f"enterprises/{PROJECT}/devices/BELL1",
    "type": "sdm.devices.types.DOORBELL",
    "traits": {f"{T}Info": {"customName": "Front door"}},
    "parentRelations": [{"parent": "y", "displayName": "Porch"}],
}


@pytest.fixture
def google(monkeypatch):
    """Google's side: tokens, the shared devices, commands and events."""
    state = {
        "devices": [thermostat_item(), DOORBELL],
        "commands": [],
        "events": [],
        "acked": [],
        "refreshes": 0,
        "deny_refresh": False,
    }

    def exchange(client_id, secret, code):
        assert (client_id, secret, code) == (CLIENT, "s3cret", "4/abc")
        return {"access_token": "a1", "refresh_token": "r1", "expires_in": 3599}

    def renew(client_id, secret, token):
        if state["deny_refresh"]:
            raise nest.NestDenied("Google refused the sign-in: invalid_grant")
        state["refreshes"] += 1
        return {"access_token": f"a{state['refreshes'] + 1}", "expires_in": 3599}

    def list_devices(token, project):
        assert project == PROJECT and token.startswith("a")
        return state["devices"]

    def execute(token, name, command, params):
        state["commands"].append((name.rsplit("/", 1)[-1], command, params))

    def pull(token, subscription, most=50):
        assert subscription == SUBSCRIPTION
        got, state["events"] = state["events"], []
        return got

    def acknowledge(token, subscription, ids):
        state["acked"] += ids

    for name, fn in (
        ("exchange", exchange),
        ("refresh", renew),
        ("list_devices", list_devices),
        ("execute", execute),
        ("pull", pull),
        ("acknowledge", acknowledge),
    ):
        monkeypatch.setattr(nest, name, fn)
    nest_home._read_at.clear()
    nest_home._seen_events.clear()
    return state


def base(home_id, end="/account"):
    return f"/api/v1/homes/{home_id}/integrations/google_nest{end}"


def signed_in(client, db, owner, login, csrf, subscription=SUBSCRIPTION, kinds=None):
    """Signs in to the app (with these alert kinds chosen), then Nest."""
    features.set_integration(db, owner.home_id, "google_nest", True, None, None)
    if kinds:
        _alerts.ready(client, db, owner, login, csrf, kinds, push=False)
    else:
        assert login(client, owner).status_code == 200
    r = client.put(
        base(owner.home_id),
        json={
            "project_id": PROJECT,
            "client_id": CLIENT,
            "client_secret": "s3cret",
            "subscription": subscription,
        },
        headers=csrf(client),
    )
    assert r.status_code == 200, r.text
    url = r.json()["authorize_url"]
    query = parse_qs(urlsplit(url).query)
    landed = f"https://www.google.com/?state={query['state'][0]}&code=4/abc&scope=x"
    r = client.post(
        base(owner.home_id, "/finish"), json={"address": landed}, headers=csrf(client)
    )
    assert r.status_code == 200, r.text
    return url, r.json()


def nest_device(db, home_id, external):
    db.expire_all()
    return (
        db.query(Device)
        .filter_by(home_id=home_id, integration="google_nest", external_id=external)
        .one()
    )


def event(external, name, session="s1", thread="STARTED", ago=0):
    when = datetime.now(UTC) - timedelta(seconds=ago)
    body = {
        "eventId": f"e-{session}",
        "timestamp": when.isoformat().replace("+00:00", "Z"),
        "resourceUpdate": {
            "name": f"enterprises/{PROJECT}/devices/{external}",
            "events": {
                f"{nest.EVENT}{name}": {"eventSessionId": session, "eventId": "x"}
            },
        },
        "eventThreadState": thread,
    }
    return {"ack_id": f"ack-{session}-{name}", "event": body}


def test_sign_in_finds_the_devices(client, db, owner, login, csrf, secrets_key, google):
    url, found = signed_in(client, db, owner, login, csrf)
    assert url.startswith(
        f"https://nestservices.google.com/partnerconnections/{PROJECT}/auth?"
    )
    query = parse_qs(urlsplit(url).query)
    assert query["redirect_uri"] == ["https://www.google.com"]
    assert query["scope"] == [" ".join(nest.SCOPES)]
    assert (found["connected"], found["created"]) == (True, 2)
    hall = nest_device(db, owner.home_id, "THERMO1")
    state = json.loads(hall.state)
    assert (hall.type, hall.name, hall.room) == (
        "thermostat",
        "Hallway thermostat",
        "Hallway",
    )
    assert state["mode"] == "heat" and state["modes"] == [
        "heat",
        "cool",
        "auto",
        "off",
        "eco",
    ]
    assert (state["heat_setpoint"], state["cool_setpoint"]) == (68, 75)
    assert (state["current_temperature"], state["humidity"]) == (70, 42)
    assert (state["status"], state["fan"], state["target_temperature"]) == (
        "heating",
        "auto",
        68,
    )
    bell = nest_device(db, owner.home_id, "BELL1")
    assert (bell.type, bell.name, bell.room) == ("camera", "Front door", "Porch")
    # The secret is never sent back; a sign-in from another start is refused.
    shown = client.get(base(owner.home_id)).json()
    assert "client_secret" not in shown and shown["subscription"] == SUBSCRIPTION
    r = client.post(
        base(owner.home_id, "/finish"),
        json={"address": "https://www.google.com/?state=forged&code=4/abc"},
        headers=csrf(client),
    )
    assert r.status_code == 409


def test_only_admins_set_it_up(
    client, new_client, db, owner, make_user, login, csrf, secrets_key, google
):
    signed_in(client, db, owner, login, csrf)
    operator = make_user(owner.home_id, role="operator")
    other = new_client()
    assert login(other, operator).status_code == 200
    assert other.get(base(owner.home_id)).json()["connected"] is True
    assert (
        other.post(base(owner.home_id, "/sync"), headers=csrf(other)).status_code == 200
    )
    body = {"project_id": PROJECT, "client_id": CLIENT}
    assert (
        other.put(base(owner.home_id), json=body, headers=csrf(other)).status_code
        == 403
    )
    assert other.delete(base(owner.home_id), headers=csrf(other)).status_code == 403


def test_thermostat_commands(client, db, owner, login, csrf, secrets_key, google):
    signed_in(client, db, owner, login, csrf)
    apply_recommended(db, owner.home_id, None, None)
    hall = nest_device(db, owner.home_id, "THERMO1").id

    def send(name, **payload):
        return _cync.command(client, csrf, owner.home_id, hall, name, **payload)

    assert send("set_temperature", temperature=70).status_code == 200
    assert google["commands"][-1] == (
        "THERMO1",
        "ThermostatTemperatureSetpoint.SetHeat",
        {"heatCelsius": 21.11},
    )
    assert send("set_fan", fan="on").status_code == 200
    assert google["commands"][-1] == (
        "THERMO1",
        "Fan.SetTimer",
        {"timerMode": "ON", "duration": "43200s"},
    )
    assert send("set_mode", mode="auto").status_code == 200
    assert google["commands"][-1] == (
        "THERMO1",
        "ThermostatMode.SetMode",
        {"mode": "HEATCOOL"},
    )
    assert send("set_cool_temperature", temperature=76).status_code == 200
    assert google["commands"][-1] == (
        "THERMO1",
        "ThermostatTemperatureSetpoint.SetRange",
        {"heatCelsius": 21.11, "coolCelsius": 24.44},
    )
    assert send("set_mode", mode="eco").status_code == 200
    assert google["commands"][-1] == (
        "THERMO1",
        "ThermostatEco.SetMode",
        {"mode": "MANUAL_ECO"},
    )
    assert send("set_temperature", temperature=70).status_code == 409  # Eco
    count = len(google["commands"])
    assert send("set_mode", mode="cool").status_code == 200
    assert google["commands"][count:] == [
        ("THERMO1", "ThermostatEco.SetMode", {"mode": "OFF"}),
        ("THERMO1", "ThermostatMode.SetMode", {"mode": "COOL"}),
    ]
    assert send("set_temperature", temperature=95).status_code == 422  # limits


def test_events_alert_and_update(
    client, db, owner, login, csrf, secrets_key, outbox, pushed, google
):
    signed_in(client, db, owner, login, csrf, kinds=["camera", "doorbell"])
    bell = nest_device(db, owner.home_id, "BELL1")
    google["events"] = [
        event("BELL1", "DoorbellChime.Chime", "s1"),
        event("BELL1", "DoorbellChime.Chime", "s1", thread="UPDATED"),
        event("BELL1", "CameraPerson.Person", "s2"),
        event("BELL1", "CameraMotion.Motion", "s3"),  # motion: off by default
        event("BELL1", "CameraPerson.Person", "s4", ago=3600),  # too old
    ]
    assert nest_home.refresh(db, owner.home_id, now=0) is not False
    subjects = [mail[1] for mail in outbox]
    assert subjects.count("Smart home: Someone rang the Front door") == 1
    assert "Smart home: Person at Front door" in subjects
    assert not any("Motion" in s for s in subjects)
    assert len(google["acked"]) == 5
    state = json.loads(nest_device(db, owner.home_id, "BELL1").state)
    assert state["last_event"]["kind"] == "person"
    # A trait change comes with the events too.
    change = {
        "ack_id": "t1",
        "event": {
            "resourceUpdate": {
                "name": f"enterprises/{PROJECT}/devices/THERMO1",
                "traits": {f"{T}ThermostatHvac": {"status": "OFF"}},
            }
        },
    }
    google["events"] = [change]
    nest_home.refresh(db, owner.home_id, now=1)
    assert (
        json.loads(nest_device(db, owner.home_id, "THERMO1").state)["status"] == "idle"
    )
    # The device's bell turns its alerts off.
    r = client.put(
        f"/api/v1/homes/{owner.home_id}/alerts/devices/{bell.id}",
        json={"enabled": False},
        headers=csrf(client),
    )
    assert r.status_code == 200, r.text
    before = len(outbox)
    google["events"] = [event("BELL1", "DoorbellChime.Chime", "s9")]
    nest_home.refresh(db, owner.home_id, now=2)
    assert len(outbox) == before


def test_lapsed_sign_in_alerts_once(
    client, db, owner, login, csrf, secrets_key, outbox, pushed, google
):
    signed_in(client, db, owner, login, csrf, kinds=["nest"])
    saved = nest_home.saved(db, owner.home_id)
    nest_home._keep(db, owner.home_id, {**saved, "expires_at": 0})
    google["deny_refresh"] = True
    assert nest_home.refresh(db, owner.home_id, now=10**6) is False
    assert nest_home.status(db, owner.home_id)["problem"] == nest_home.RECONNECT
    assert alerts.check_home(db, owner.home_id, now=0) >= 1
    assert alerts.check_home(db, owner.home_id, now=60) == 0
    assert any("Google Nest needs signing in again" in m[1] for m in outbox)


def test_background_refresh_reads_now_and_then(
    client, db, owner, login, csrf, secrets_key, google
):
    signed_in(client, db, owner, login, csrf, subscription="")
    google["devices"] = [thermostat_item(mode="COOL", hvac="COOLING")]
    google["devices"].append(DOORBELL)
    refresh.refresh_all(db)
    assert json.loads(nest_device(db, owner.home_id, "THERMO1").state)["mode"] == "cool"
    # An empty answer keeps the devices (offline), as a hiccup.
    google["devices"] = []
    nest_home._read_at.clear()
    nest_home.refresh(db, owner.home_id, now=0)
    assert nest_device(db, owner.home_id, "THERMO1").online is False


def test_code_from_the_address():
    assert nest.code_from("https://www.google.com/?state=s&code=4/x&scope=y") == (
        "4/x",
        "s",
    )
    assert nest.code_from("4/0Abc") == ("4/0Abc", None)
    with pytest.raises(nest.NestError):
        nest.code_from("https://www.google.com/?error=access_denied")
    encoded = base64.b64encode(json.dumps({"a": 1}).encode()).decode()
    assert json.loads(base64.b64decode(encoded)) == {"a": 1}


def test_ui_panel_warns_about_the_fee(open_page, db, owner, secrets_key, google):
    features.set_integration(db, owner.home_id, "google_nest", True, None, None)
    page = open_page()
    _ui.ui_login(page, owner)
    section = _ui.go_settings(page, "integrations")
    panel = section.get_by_test_id("nest")
    expect(panel.get_by_test_id("nest-paid")).to_contain_text(
        "one-time, non-refundable US$5"
    )
    expect(panel.get_by_test_id("nest-state")).to_have_text("Not signed in yet.")
    panel.get_by_test_id("nest-project").fill(PROJECT)
    panel.get_by_test_id("nest-client-id").fill(CLIENT)
    panel.get_by_test_id("nest-client-secret").fill("s3cret")
    # Google's page is not really opened: its address is all that matters.
    page.context.route(
        "https://nestservices.google.com/**",
        lambda route: route.fulfill(status=200, body="Google sign-in"),
    )
    with page.context.expect_page() as opened:
        panel.get_by_test_id("nest-sign-in").click()
    google_page = opened.value
    google_page.wait_for_url("**/partnerconnections/**")
    state = parse_qs(urlsplit(google_page.url).query)["state"][0]
    google_page.close()
    landed = f"https://www.google.com/?state={state}&code=4/abc"
    page.get_by_test_id("nest-address").fill(landed)
    page.get_by_test_id("nest-finish-submit").click()
    expect(page.get_by_test_id("status")).to_contain_text(
        "Google Nest signed in: 2 new"
    )
    expect(page.get_by_test_id("nest-state")).to_contain_text("Signed in")


def test_ui_camera_card_and_its_bell(open_page, db, owner, secrets_key, google):
    # Signed in already (without logging in here: the page logs in).
    features.set_integration(db, owner.home_id, "google_nest", True, None, None)
    nest_home._keep(
        db,
        owner.home_id,
        {
            "project_id": PROJECT,
            "client_id": CLIENT,
            "client_secret": "s3cret",
            "subscription": SUBSCRIPTION,
            "refresh_token": "r1",
            "access_token": "a1",
            "expires_at": 4e9,
            "problem": None,
        },
    )
    nest_home.sync(db, owner.home_id)
    google["events"] = [event("BELL1", "DoorbellChime.Chime", "s1")]
    nest_home.refresh(db, owner.home_id, now=0)
    page = open_page()
    _ui.ui_login(page, owner)
    card = _ui.card(page, "Front door")
    expect(card.get_by_test_id("camera-seen")).to_contain_text("Doorbell rang · ")
    section = _ui.go_settings(page, "devices")
    row = section.locator('[data-testid="device-alert-bell"][data-popup="true"]').first
    expect(row).to_be_visible()
