"""Rheem EcoNet contract: encrypted login, water-heater discovery, set points.

Written by the reviewer (Rheem phase). Do not edit, skip, mark or delete these
tests. If one looks wrong, stop and report the test name and its full failure
output instead of changing it.

Nothing here talks to Rheem: `app.integrations.rheem.connect` is replaced by
FakeEconet. The owner tests the real account by hand.
"""

import json

import pytest
from cryptography.fernet import Fernet
from pyeconet.equipment.water_heater import WaterHeater

from app.integrations import rheem
from app.integrations.rheem import RheemError, RheemHeater, RheemLoginError
from app.models import AuditEvent, Device

EMAIL = "owner@example.com"
PASSWORD = "econet password 1"
SERIAL = "40-11-AA-BB"


def url(home_id, suffix):
    return f"/api/v1/homes/{home_id}{suffix}"


def heater(**changes):
    values = {
        "serial": SERIAL,
        "name": "Garage water heater",
        "set_point": 120,
        "min_set_point": 110,
        "max_set_point": 140,
        "mode": "energy_saving",
        "enabled": True,
        "running": True,
        "connected": True,
    }
    values.update(changes)
    return RheemHeater(**values)


class FakeEconet:
    """Stands in for Rheem's cloud. `connect` checks the password like EcoNet."""

    def __init__(self):
        self.heaters = [heater()]
        self.set_points = []
        self.commands = []
        self.logins = []
        self.fail = None  # an exception to raise on the next call

    def connect(self, email, password):
        self.logins.append(email)
        fake = self

        class Client:
            def list_water_heaters(self):
                fake._check(password)
                return list(fake.heaters)

            def set_set_point(self, serial, set_point):
                fake._check(password)
                fake.set_points.append((serial, set_point))

            def set_mode(self, serial, mode):
                fake._check(password)
                fake.commands.append(("mode", serial, mode))

            def set_away(self, serial, away):
                fake._check(password)
                fake.commands.append(("away", serial, away))

            def resume_schedule(self, serial):
                fake._check(password)
                fake.commands.append(("resume", serial))

        return Client()

    def _check(self, password):
        if self.fail:
            error, self.fail = self.fail, None
            raise error
        if password != PASSWORD:
            raise RheemLoginError("refused")


@pytest.fixture
def econet(monkeypatch):
    fake = FakeEconet()
    monkeypatch.setattr(rheem, "connect", fake.connect)
    return fake


@pytest.fixture
def secrets_key(monkeypatch):
    key = Fernet.generate_key().decode()
    monkeypatch.setenv("SECRETS_KEY", key)
    return key


def turn_on(client, csrf, home_id):
    r = client.put(
        url(home_id, "/integrations/rheem_econet"),
        json={"enabled": True},
        headers=csrf(client),
    )
    assert r.status_code == 200, r.text


def save_login(client, csrf, home_id, password=PASSWORD):
    return client.put(
        url(home_id, "/integrations/rheem_econet/account"),
        json={"email": EMAIL, "password": password},
        headers=csrf(client),
    )


def ready(client, csrf, login, owner):
    """Owner logged in, Rheem on, login saved."""
    assert login(client, owner).status_code == 200
    turn_on(client, csrf, owner.home_id)
    assert save_login(client, csrf, owner.home_id).status_code == 200


def sync(client, csrf, home_id):
    return client.post(
        url(home_id, "/integrations/rheem_econet/sync"), headers=csrf(client)
    )


def rheem_devices(db, home_id):
    db.expire_all()
    return db.query(Device).filter_by(home_id=home_id, integration="rheem_econet").all()


def events(db, event_type):
    db.expire_all()
    return db.query(AuditEvent).filter_by(event_type=event_type).all()


# ------------------------------------------------------------ E1: vault


def test_vault_encrypts_with_secrets_key(monkeypatch):
    from app import vault  # added in step E1

    monkeypatch.delenv("SECRETS_KEY", raising=False)
    with pytest.raises(vault.VaultError):
        vault.encrypt({"password": "x"})
    monkeypatch.setenv("SECRETS_KEY", "not a key")
    with pytest.raises(vault.VaultError):
        vault.encrypt({"password": "x"})

    key = Fernet.generate_key().decode()
    monkeypatch.setenv("SECRETS_KEY", key)
    token = vault.encrypt({"email": EMAIL, "password": PASSWORD})
    assert isinstance(token, str)
    assert PASSWORD not in token and EMAIL not in token
    assert vault.decrypt(token) == {"email": EMAIL, "password": PASSWORD}
    assert json.loads(Fernet(key.encode()).decrypt(token.encode())) == {
        "email": EMAIL,
        "password": PASSWORD,
    }

    monkeypatch.setenv("SECRETS_KEY", Fernet.generate_key().decode())
    with pytest.raises(vault.VaultError):
        vault.decrypt(token)  # another key cannot read it


def test_vault_key_script_prints_a_usable_key(capsys):
    from scripts.make_secrets_key import main

    assert main() == 0
    key = capsys.readouterr().out.strip()
    Fernet(key.encode())  # raises if it is not a valid key


# ------------------------------------------------------------ E2: adapter


def test_rheem_heater_from_pyeconet_equipment():
    """The adapter reads pyeconet's WaterHeater the way pyeconet 0.3.1 exposes it."""
    info = {
        "device_name": "econet_wh_1",
        "serial_number": SERIAL,
        "device_type": "WH",
        "@TYPE": "heatpumpWaterHeaterGen4",
        "@NAME": {"value": "Garage water heater"},
        "@SETPOINT": {
            "value": 120,
            "constraints": {"lowerLimit": 110, "upperLimit": 140},
        },
        "@MODE": {
            "value": 1,
            "status": "Energy Saver",
            "constraints": {
                "enumText": [
                    "Off",
                    "Energy Saver",
                    "Heat Pump",
                    "High Demand",
                    "Electric",
                ]
            },
        },
        "@ENABLED": {"value": 1},
        "@RUNNING": "Running",
        "@CONNECTED": True,
    }
    read = rheem.heater_from_equipment(WaterHeater(info, None))
    core = (
        "serial",
        "name",
        "set_point",
        "min_set_point",
        "max_set_point",
        "mode",
        "enabled",
        "running",
        "connected",
    )
    assert {k: getattr(read, k) for k in core} == {
        k: getattr(heater(), k) for k in core
    }
    assert "energy_saving" in read.modes and "off" in read.modes  # from @MODE
    assert read.status == "heating"

    info["@ENABLED"] = {"value": 0}
    info["@RUNNING"] = ""
    info["@CONNECTED"] = False
    off = rheem.heater_from_equipment(WaterHeater(info, None))
    assert (off.mode, off.enabled, off.running, off.connected) == (
        "off",
        False,
        False,
        False,
    )


def test_rheem_heater_state():
    assert heater().state() == {
        "target_temperature": 120,
        "unit": "F",
        "min_set_point": 110,
        "max_set_point": 140,
        "mode": "energy_saving",
        "enabled": True,
        "running": True,
        "modes": [],
        "away": None,
        "schedule": None,
        "hot_water": None,
        "energy_today": None,
        "energy_unit": None,
        "water_today": None,
        "wifi": None,
        "alerts": 0,
        "activity": None,
        "status": "heating",
    }
    assert heater(enabled=False).status == "off"
    assert heater(running=False).status == "idle"


def test_rheem_connect_returns_the_pyeconet_client():
    client = rheem.connect(EMAIL, PASSWORD)  # no network until a method is called
    assert callable(client.list_water_heaters) and callable(client.set_set_point)


def test_rheem_is_available(client, owner, login):
    assert login(client, owner).status_code == 200
    rows = {r["id"]: r for r in client.get(url(owner.home_id, "/integrations")).json()}
    assert rows["rheem_econet"]["available"] is True
    assert (
        rows["rheem_econet"]["enabled"] is False
    )  # still off until the owner turns it on


# ------------------------------------------------------------ E3: account


def test_rheem_owner_saves_login_encrypted(
    client,
    new_client,
    db,
    owner,
    make_user,
    login,
    csrf,
    econet,
    secrets_key,
    monkeypatch,
):
    from app import vault  # added in step E1
    from app.models import IntegrationCredential  # added in step E2

    account = url(owner.home_id, "/integrations/rheem_econet/account")
    admin = make_user(owner.home_id, role="operator")
    admin_client = new_client()
    assert login(admin_client, admin).status_code == 200
    assert save_login(admin_client, csrf, owner.home_id).status_code == 403
    assert admin_client.get(account).status_code == 403

    assert login(client, owner).status_code == 200
    assert client.get(account).json() == {"configured": False, "email": None}
    assert (
        client.put(account, json={"email": EMAIL, "password": PASSWORD}).status_code
        == 403
    )
    assert save_login(client, csrf, owner.home_id, password="wrong").status_code == 400
    assert db.query(IntegrationCredential).count() == 0

    monkeypatch.delenv("SECRETS_KEY")
    assert (
        save_login(client, csrf, owner.home_id).status_code == 409
    )  # no key: not stored
    assert db.query(IntegrationCredential).count() == 0
    monkeypatch.setenv("SECRETS_KEY", secrets_key)

    r = save_login(client, csrf, owner.home_id)
    assert r.status_code == 200, r.text
    assert r.json() == {"configured": True, "email": EMAIL}
    assert PASSWORD not in client.get(account).text

    db.expire_all()
    row = db.query(IntegrationCredential).one()
    assert (row.home_id, row.integration, row.label) == (
        owner.home_id,
        "rheem_econet",
        EMAIL,
    )
    assert PASSWORD not in row.secret
    assert vault.decrypt(row.secret) == {"email": EMAIL, "password": PASSWORD}
    saved = events(db, "integration_account_saved")
    assert saved and PASSWORD not in (saved[-1].details or "")

    r = client.delete(account, headers=csrf(client))
    assert r.status_code == 200 and r.json() == {"configured": False, "email": None}
    assert db.query(IntegrationCredential).count() == 0
    assert events(db, "integration_account_removed")


def test_rheem_login_is_per_home(
    client, new_client, owner, make_home, make_user, login, csrf, econet, secrets_key
):
    ready(client, csrf, login, owner)
    other_owner = make_user(make_home("Home B"), role="owner")
    other = new_client()
    assert login(other, other_owner).status_code == 200
    b_account = url(other_owner.home_id, "/integrations/rheem_econet/account")
    assert other.get(b_account).json() == {"configured": False, "email": None}
    assert (
        other.get(url(owner.home_id, "/integrations/rheem_econet/account")).status_code
        == 404
    )


# ------------------------------------------------------------ E4: sync


def test_rheem_sync_creates_then_updates_water_heaters(
    client, new_client, db, owner, make_user, login, csrf, econet, secrets_key
):
    assert login(client, owner).status_code == 200
    assert sync(client, csrf, owner.home_id).status_code == 409  # integration off
    turn_on(client, csrf, owner.home_id)
    assert sync(client, csrf, owner.home_id).status_code == 409  # no login saved
    assert save_login(client, csrf, owner.home_id).status_code == 200

    member = make_user(owner.home_id, role="member")
    member_client = new_client()
    assert login(member_client, member).status_code == 200
    assert sync(member_client, csrf, owner.home_id).status_code == 403
    assert (
        client.post(url(owner.home_id, "/integrations/rheem_econet/sync")).status_code
        == 403
    )

    r = sync(client, csrf, owner.home_id)
    assert r.status_code == 200, r.text
    assert r.json() == {"created": 1, "updated": 0}
    [device] = rheem_devices(db, owner.home_id)
    assert (device.type, device.external_id, device.name, device.online) == (
        "water_heater",
        SERIAL,
        "Garage water heater",
        True,
    )
    assert json.loads(device.state) == heater().state()
    listed = client.get(url(owner.home_id, "/devices")).json()
    assert [d["name"] for d in listed if d["integration"] == "rheem_econet"] == [
        "Garage water heater"
    ]
    assert events(db, "integration_synced")

    econet.heaters = [heater(set_point=115, running=False)]
    assert sync(client, csrf, owner.home_id).json() == {"created": 0, "updated": 1}
    [device] = rheem_devices(db, owner.home_id)
    assert json.loads(device.state)["target_temperature"] == 115
    assert json.loads(device.state)["running"] is False

    admin = make_user(owner.home_id, role="admin")
    admin_client = new_client()
    assert login(admin_client, admin).status_code == 200
    econet.heaters = []
    assert sync(admin_client, csrf, owner.home_id).json() == {
        "created": 0,
        "updated": 0,
    }
    assert rheem_devices(db, owner.home_id) == []  # removed in EcoNet: deleted


def test_rheem_sync_reports_econet_failures(
    client, db, owner, login, csrf, econet, secrets_key
):
    ready(client, csrf, login, owner)
    econet.fail = RheemError("EcoNet request failed: TimeoutError")
    r = sync(client, csrf, owner.home_id)
    assert r.status_code == 502
    econet.fail = RheemLoginError("refused")
    assert sync(client, csrf, owner.home_id).status_code == 502
    failed = events(db, "integration_sync_failed")
    assert len(failed) == 2
    assert PASSWORD not in (failed[-1].details or "")
    assert rheem_devices(db, owner.home_id) == []


# ------------------------------------------------------------ E5: commands


def set_temperature(client, csrf, home_id, device_id, temperature):
    return client.post(
        url(home_id, f"/devices/{device_id}/command"),
        json={"command": "set_temperature", "payload": {"temperature": temperature}},
        headers=csrf(client),
    )


def test_rheem_set_point_goes_to_econet(
    client, new_client, db, owner, make_user, login, csrf, econet, secrets_key
):
    from app.safety import apply_recommended

    ready(client, csrf, login, owner)
    apply_recommended(db, owner.home_id, None, None)  # 110-120 F
    econet.heaters = [heater(min_set_point=115)]
    assert sync(client, csrf, owner.home_id).status_code == 200
    [device] = rheem_devices(db, owner.home_id)

    r = set_temperature(client, csrf, owner.home_id, device.id, 118)
    assert r.status_code == 200, r.text
    assert econet.set_points == [(SERIAL, 118)]
    assert isinstance(econet.set_points[0][1], int)
    assert (
        json.loads(rheem_devices(db, owner.home_id)[0].state)["target_temperature"]
        == 118
    )

    member = make_user(owner.home_id, role="member")
    member_client = new_client()
    assert login(member_client, member).status_code == 200
    assert (
        set_temperature(member_client, csrf, owner.home_id, device.id, 119).status_code
        == 200
    )
    assert econet.set_points[-1] == (SERIAL, 119)

    for refused in (
        125,
        117.5,
        112,
    ):  # over the safety limit, half degree, below the heater's range
        r = set_temperature(client, csrf, owner.home_id, device.id, refused)
        assert r.status_code == 422, (refused, r.text)
    assert len(econet.set_points) == 2  # nothing refused reached EcoNet


def test_rheem_command_failures_change_nothing(
    client, db, owner, login, csrf, econet, secrets_key, monkeypatch
):
    from app.safety import apply_recommended

    ready(client, csrf, login, owner)
    apply_recommended(db, owner.home_id, None, None)
    assert sync(client, csrf, owner.home_id).status_code == 200
    [device] = rheem_devices(db, owner.home_id)

    econet.fail = RheemError("EcoNet request failed: TimeoutError")
    assert (
        set_temperature(client, csrf, owner.home_id, device.id, 118).status_code == 502
    )
    assert (
        json.loads(rheem_devices(db, owner.home_id)[0].state)["target_temperature"]
        == 120
    )
    assert events(db, "device_command_rejected")

    client.delete(
        url(owner.home_id, "/integrations/rheem_econet/account"), headers=csrf(client)
    )
    assert (
        set_temperature(client, csrf, owner.home_id, device.id, 118).status_code == 409
    )

    assert save_login(client, csrf, owner.home_id).status_code == 200
    monkeypatch.setenv("SECRETS_KEY", Fernet.generate_key().decode())  # key changed
    assert (
        set_temperature(client, csrf, owner.home_id, device.id, 118).status_code == 409
    )

    client.put(
        url(owner.home_id, "/integrations/rheem_econet"),
        json={"enabled": False},
        headers=csrf(client),
    )
    assert (
        set_temperature(client, csrf, owner.home_id, device.id, 118).status_code == 409
    )
    assert econet.set_points == []


# ------------------------------------------------------------ adapter: logins


class FakeEcoNetApi:
    """Stands in for pyeconet's EcoNetApiInterface inside the real adapter."""

    logins = 0
    fail_login = None
    fail_equipment = []

    def __init__(self, email, password, account_id=None, user_token=None):
        self.user_token, self.account_id = user_token, account_id

    @classmethod
    async def login(cls, email, password):
        cls.logins += 1
        if cls.fail_login:
            raise cls.fail_login
        return cls(email, password, account_id="acct", user_token=f"token-{cls.logins}")

    async def get_equipment_by_type(self, types):
        if FakeEcoNetApi.fail_equipment:
            raise FakeEcoNetApi.fail_equipment.pop(0)
        return {types[0]: []}


def test_rheem_adapter_reuses_logins(monkeypatch):
    from pyeconet.errors import GenericHTTPError

    monkeypatch.setattr(rheem, "EcoNetApiInterface", FakeEcoNetApi)
    monkeypatch.setattr(rheem, "_sessions", {})
    FakeEcoNetApi.logins, FakeEcoNetApi.fail_login, FakeEcoNetApi.fail_equipment = (
        0,
        None,
        [],
    )
    client = rheem.PyeconetClient(EMAIL, PASSWORD)
    assert client.list_water_heaters() == []
    assert rheem.PyeconetClient(EMAIL, PASSWORD).list_water_heaters() == []
    assert FakeEcoNetApi.logins == 1  # the second call reused the login

    rheem.PyeconetClient(EMAIL, "another password").list_water_heaters()
    assert FakeEcoNetApi.logins == 2  # a different password never reuses a login

    FakeEcoNetApi.fail_equipment = [GenericHTTPError(401)]
    assert client.list_water_heaters() == []
    assert FakeEcoNetApi.logins == 3  # expired login: logged in again once

    FakeEcoNetApi.fail_equipment = [GenericHTTPError(429)]
    with pytest.raises(RheemError, match="Wait 15 minutes"):
        client.list_water_heaters()
    assert FakeEcoNetApi.logins == 3  # rate limited: no extra login


def test_rheem_adapter_reports_rate_limit_and_bad_login(monkeypatch):
    from pyeconet.errors import GenericHTTPError, InvalidCredentialsError

    monkeypatch.setattr(rheem, "EcoNetApiInterface", FakeEcoNetApi)
    monkeypatch.setattr(rheem, "_sessions", {})
    FakeEcoNetApi.logins, FakeEcoNetApi.fail_equipment = 0, []
    FakeEcoNetApi.fail_login = GenericHTTPError(429)
    with pytest.raises(RheemError, match="Wait 15 minutes"):
        rheem.PyeconetClient(EMAIL, PASSWORD).list_water_heaters()
    FakeEcoNetApi.fail_login = InvalidCredentialsError("bad")
    with pytest.raises(RheemLoginError):
        rheem.PyeconetClient(EMAIL, PASSWORD).list_water_heaters()
    FakeEcoNetApi.fail_login = None
    assert rheem._sessions == {}  # failed logins are not saved
