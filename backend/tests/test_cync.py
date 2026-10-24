"""GE Cync: logging in with the emailed code, finding lights and plugs,
commands. Written by the reviewer (Cync phase). Do not edit, skip, mark or
delete these tests. If one looks wrong, stop and report the test name and its
full failure output instead of changing it.

Nothing here talks to Cync: app.integrations.cync's functions are replaced by
FakeCync (and pycync's classes by fakes for the adapter tests).
"""

import json

import pytest
from cryptography.fernet import Fernet
from playwright.sync_api import expect

from app import cync_home
from app.integrations import cync
from app.models import AuditEvent, Device, IntegrationCredential
from tests import test_ui as _ui

card, go_settings, ui_login = _ui.card, _ui.go_settings, _ui.ui_login
EMAIL, PASSWORD, CODE = "me@example.com", "cync password 1", "123456"
TOKENS = {
    "access_token": "a1",
    "refresh_token": "r1",
    "authorize": "z1",
    "user_id": 42,
    "expires_at": 9e9,
}


def info(id_="77-1", kind="light", **changes):
    values = {
        "id": id_,
        "name": "Porch light",
        "kind": kind,
        "online": True,
        "dimming": kind == "light",
        "white": kind == "light",
        "color": False,
    }
    values.update(changes)
    return cync.CyncDeviceInfo(**values)


class FakeCync:
    def __init__(self):
        self.devices = [info(), info("77-2", "plug", name="Fan plug")]
        self.sent = []
        self.fail = None
        self.states = {}
        self.states_fail = None
        self.groups = []

    def list_groups(self, tokens):
        return list(self.groups), tokens

    def read_states(self, tokens):
        if self.states_fail:
            raise self.states_fail
        return dict(self.states)

    def login(self, email, password, code=None):
        if password != PASSWORD:
            raise cync.CyncLoginError("refused")
        if code is None:
            raise cync.CyncCodeSent("code sent")
        if code != CODE:
            raise cync.CyncLoginError("refused")
        return dict(TOKENS)

    def list_devices(self, tokens):
        assert tokens["access_token"].startswith("a")
        return list(self.devices), {**tokens, "access_token": "a2"}

    def send(self, tokens, device_id, action, value):
        if self.fail:
            error, self.fail = self.fail, None
            raise error
        self.sent.append((device_id, action, value))
        return tokens


@pytest.fixture
def fake(monkeypatch):
    f = FakeCync()
    for name in ("login", "list_devices", "send", "read_states", "list_groups"):
        monkeypatch.setattr(cync, name, getattr(f, name))
    return f


@pytest.fixture
def secrets_key(monkeypatch):
    monkeypatch.setenv("SECRETS_KEY", Fernet.generate_key().decode())


def url(home_id, suffix):
    return f"/api/v1/homes/{home_id}/integrations/cync{suffix}"


def turn_on(client, csrf, home_id):
    r = client.put(
        f"/api/v1/homes/{home_id}/integrations/cync",
        json={"enabled": True},
        headers=csrf(client),
    )
    assert r.status_code == 200, r.text


def log_in(client, csrf, home_id, code=None, password=PASSWORD):
    body = {"email": EMAIL, "password": password}
    if code is not None:
        body["code"] = code
    return client.put(url(home_id, "/account"), json=body, headers=csrf(client))


def ready(client, csrf, login, owner):
    assert login(client, owner).status_code == 200
    turn_on(client, csrf, owner.home_id)
    assert log_in(client, csrf, owner.home_id, CODE).json()["configured"] is True
    r = client.post(url(owner.home_id, "/sync"), headers=csrf(client))
    assert r.status_code == 200, r.text
    return r.json()


def device_id(db, home_id, external_id):
    db.expire_all()
    return (
        db.query(Device)
        .filter_by(home_id=home_id, integration="cync", external_id=external_id)
        .one()
        .id
    )


def command(client, csrf, home_id, device, name, **payload):
    return client.post(
        f"/api/v1/homes/{home_id}/devices/{device}/command",
        json={"command": name, "payload": payload},
        headers=csrf(client),
    )


def test_login_with_emailed_code(client, db, owner, login, csrf, fake, secrets_key):
    assert login(client, owner).status_code == 200
    turn_on(client, csrf, owner.home_id)
    r = log_in(client, csrf, owner.home_id)
    assert r.status_code == 200
    assert (r.json()["code_sent"], r.json()["configured"]) == (True, False)
    assert log_in(client, csrf, owner.home_id, "999999").status_code == 400
    assert log_in(client, csrf, owner.home_id, "12ab").status_code == 422
    r = log_in(client, csrf, owner.home_id, CODE)
    assert r.status_code == 200
    assert r.json() == {"configured": True, "email": EMAIL, "code_sent": False}
    (row,) = db.query(IntegrationCredential).filter_by(integration="cync").all()
    assert PASSWORD not in row.secret and "access_token" not in row.secret
    from app import credentials

    saved = credentials.load(db, owner.home_id, "cync")
    assert saved == {"email": EMAIL, "tokens": TOKENS}  # no password kept
    for e in db.query(AuditEvent).all():
        assert PASSWORD not in (e.details or "") and CODE not in (e.details or "")


def test_only_owner_logs_in(
    client, new_client, owner, make_user, login, csrf, fake, secrets_key
):
    assert login(client, owner).status_code == 200
    turn_on(client, csrf, owner.home_id)
    admin = make_user(owner.home_id, role="operator")
    a = new_client()
    assert login(a, admin).status_code == 200
    assert log_in(a, csrf, owner.home_id, CODE).status_code == 403
    assert a.get(url(owner.home_id, "/account")).status_code == 403


def test_sync_finds_lights_and_plugs(client, db, owner, login, csrf, fake, secrets_key):
    assert ready(client, csrf, login, owner) == {"created": 2, "updated": 0}
    lamp = db.get(Device, device_id(db, owner.home_id, "77-1"))
    plug = db.get(Device, device_id(db, owner.home_id, "77-2"))
    plug_id = plug.id
    assert (lamp.type, lamp.name, lamp.online) == ("light", "Porch light", True)
    assert json.loads(lamp.capabilities) == {
        "dimming": True,
        "white": True,
        "color": False,
        "mac": None,
    }
    assert plug.type == "plug"
    from app import credentials

    assert credentials.load(db, owner.home_id, "cync")["tokens"]["access_token"] == (
        "a2"
    )  # refreshed tokens are kept
    fake.devices = [info()]
    r = client.post(url(owner.home_id, "/sync"), headers=csrf(client))
    assert r.json() == {"created": 0, "updated": 1}
    db.expire_all()
    assert db.get(Device, plug_id) is None  # removed in the Cync app: deleted


def test_commands_reach_cync(client, db, owner, login, csrf, fake, secrets_key):
    ready(client, csrf, login, owner)
    home = owner.home_id
    lamp = device_id(db, home, "77-1")
    plug = device_id(db, home, "77-2")
    assert command(client, csrf, home, lamp, "turn_on").status_code == 200
    assert (
        command(client, csrf, home, lamp, "set_brightness", brightness=40).status_code
        == 200
    )
    assert (
        command(client, csrf, home, lamp, "set_color_temp", kelvin=6500).status_code
        == 200
    )
    assert (
        command(client, csrf, home, lamp, "set_color_temp", kelvin=2000).status_code
        == 200
    )
    assert command(client, csrf, home, plug, "turn_off").status_code == 200
    assert fake.sent == [
        ("77-1", "power", True),
        ("77-1", "brightness", 40),
        ("77-1", "color_temp", 1),
        ("77-1", "color_temp", 100),
        ("77-2", "power", False),
    ]
    r = command(client, csrf, home, lamp, "set_color", color="#ff8800")
    assert r.status_code == 422  # this bulb has no colour
    db.expire_all()
    assert json.loads(db.get(Device, lamp).state)["color_mode"] == "temp"


def test_colour_bulb_and_failures(client, db, owner, login, csrf, fake, secrets_key):
    fake.devices = [info(color=True)]
    ready(client, csrf, login, owner)
    home = owner.home_id
    lamp = device_id(db, home, "77-1")
    assert (
        command(client, csrf, home, lamp, "set_color", color="#FF8800").status_code
        == 200
    )
    assert fake.sent[-1] == ("77-1", "rgb", (255, 136, 0))
    before = db.get(Device, lamp).state
    fake.fail = cync.CyncError("no Cync device is on Wi-Fi to pass commands on")
    r = command(client, csrf, home, lamp, "turn_off")
    assert r.status_code == 502 and "Wi-Fi" in r.json()["detail"]
    fake.fail = cync.CyncLoginError("Cync refused the login: log in again")
    assert command(client, csrf, home, lamp, "turn_off").status_code == 409
    db.expire_all()
    assert db.get(Device, lamp).state == before  # unchanged after failures


def test_kelvin_scale():
    assert cync_home.kelvin_to_cync(6500) == 1
    assert cync_home.kelvin_to_cync(2000) == 100
    assert 45 <= cync_home.kelvin_to_cync(4250) <= 55


# ------------------------------------------------------------ the adapter


class FakeAuth:
    def __init__(self, session, user=None, username=None, password=None):
        self.user, self.password = user, password

    async def login(self, code=None):
        from pycync.exceptions import AuthFailedError, TwoFactorRequiredError

        if code is None:
            raise TwoFactorRequiredError("code sent")
        if code != CODE:
            raise AuthFailedError("bad code")
        return cync.User("a", "r", "z", 7, expires_at=123.0)


def test_adapter_login(monkeypatch):
    monkeypatch.setattr(cync, "Auth", FakeAuth)
    with pytest.raises(cync.CyncCodeSent):
        cync.login(EMAIL, PASSWORD)
    with pytest.raises(cync.CyncLoginError):
        cync.login(EMAIL, PASSWORD, "000000")
    assert cync.login(EMAIL, PASSWORD, CODE) == {
        "access_token": "a",
        "refresh_token": "r",
        "authorize": "z",
        "user_id": 7,
        "expires_at": 123.0,
    }


def test_adapter_times_out(monkeypatch):
    import asyncio

    class SlowAuth(FakeAuth):
        async def login(self, code=None):
            await asyncio.sleep(5)

    monkeypatch.setattr(cync, "Auth", SlowAuth)
    monkeypatch.setattr(cync, "TIMEOUT_SECONDS", 0.2)
    with pytest.raises(cync.CyncError, match="in time"):
        cync.login(EMAIL, PASSWORD, CODE)


# ------------------------------------------------------------ browser


def test_ui_cync_login_and_find_devices(open_page, db, owner, fake, secrets_key):
    page = open_page()
    ui_login(page, owner)
    section = go_settings(page, "integrations")
    row = section.locator('[data-testid="integration-row"][data-integration="cync"]')
    row.get_by_test_id("integration-toggle").check()
    panel = page.get_by_test_id("cync-account")
    expect(panel.get_by_test_id("cync-configured")).to_contain_text("No Cync account")
    expect(panel.get_by_test_id("cync-code")).to_be_hidden()
    panel.get_by_test_id("cync-email").fill(EMAIL)
    panel.get_by_test_id("cync-password").fill(PASSWORD)
    panel.get_by_test_id("cync-save").click()
    expect(panel.get_by_test_id("cync-code")).to_be_visible()
    panel.get_by_test_id("cync-code").fill(CODE)
    panel.get_by_test_id("cync-save").click()
    expect(page.get_by_test_id("status")).to_have_attribute("data-kind", "success")
    expect(panel.get_by_test_id("cync-configured")).to_contain_text(EMAIL)
    panel.get_by_test_id("cync-sync").click()
    expect(page.get_by_test_id("status")).to_contain_text("2 new")
    page.get_by_test_id("nav-devices").click()
    card(page, "Fan plug").get_by_test_id("power-toggle").click()
    expect(card(page, "Fan plug").get_by_test_id("power-toggle")).to_have_attribute(
        "aria-pressed", "true"
    )
    assert fake.sent == [("77-2", "power", True)]


def test_sync_reads_current_state(client, db, owner, login, csrf, fake, secrets_key):
    fake.devices = [info(color=True, mac="A4:C1:38:AA:BB:CC"), info("77-2", "plug")]
    fake.states = {
        "77-1": {"on": True, "brightness": 30, "color_temp": 1},
        "77-2": {"on": True},
    }
    ready(client, csrf, login, owner)
    lamp = db.get(Device, device_id(db, owner.home_id, "77-1"))
    state = json.loads(lamp.state)
    assert (state["on"], state["brightness"], state["color_temp"]) == (True, 30, 6500)
    assert json.loads(lamp.capabilities)["mac"] == "A4:C1:38:AA:BB:CC"
    plug = db.get(Device, device_id(db, owner.home_id, "77-2"))
    assert json.loads(plug.state)["on"] is True
    fake.states = {"77-1": {"on": False, "rgb": (255, 0, 16)}}
    client.post(url(owner.home_id, "/sync"), headers=csrf(client))
    db.expire_all()
    state = json.loads(db.get(Device, lamp.id).state)
    assert (state["on"], state["color_mode"], state["color"]) == (
        False,
        "rgb",
        "#ff0010",
    )
    fake.states_fail = cync.CyncError("no Cync device is on Wi-Fi to pass commands on")
    r = client.post(url(owner.home_id, "/sync"), headers=csrf(client))
    assert r.status_code == 200  # the device list still syncs; state is kept
    r = client.get(f"/api/v1/homes/{owner.home_id}/devices")
    lamp_out = next(d for d in r.json() if d["id"] == lamp.id)
    assert lamp_out["network"] == {"ip": None, "mac": "A4:C1:38:AA:BB:CC"}


def test_cync_state_scale():
    assert cync._mac("a4c138aabbcc") == "A4:C1:38:AA:BB:CC"
    assert cync._mac("not a mac") is None
    assert cync_home.cync_to_kelvin(1) == 6500
    assert cync_home.cync_to_kelvin(100) == 2000
    for kelvin in (2000, 2700, 4000, 6500):
        back = cync_home.cync_to_kelvin(cync_home.kelvin_to_cync(kelvin))
        assert abs(back - kelvin) <= 100


def test_background_refresh_resyncs_cync(
    client, db, owner, login, csrf, fake, secrets_key
):
    from app import refresh

    refresh._cync_read_at.clear()
    ready(client, csrf, login, owner)
    fake.devices.append(info("77-3", "plug", name="New plug"))
    fake.states = {"77-1": {"on": True, "brightness": 55}}
    assert refresh.refresh_cync(db, owner.home_id, now=1000) is True
    db.expire_all()
    assert device_id(db, owner.home_id, "77-3")  # set up in the Cync app: appears
    lamp = db.get(Device, device_id(db, owner.home_id, "77-1"))
    assert json.loads(lamp.state)["brightness"] == 55
    assert refresh.refresh_cync(db, owner.home_id, now=1000 + 60) is False  # too soon
    assert refresh.refresh_cync(db, owner.home_id, now=1000 + 300) is True


def test_adapter_reads_only_reported_devices(monkeypatch):
    import asyncio

    from pycync import CyncLight
    from pycync.devices.capabilities import CyncCapability

    def light(mesh_id, on, brightness, temp):
        device = CyncLight.__new__(CyncLight)
        device.parent_home_id, device.mesh_device_id = 7, mesh_id
        device._capabilities = frozenset(
            {CyncCapability.ON_OFF, CyncCapability.DIMMING, CyncCapability.CCT_COLOR}
        )
        device._is_on, device._brightness, device._color_temp = on, brightness, temp
        device._rgb = (0, 0, 0)
        return device

    seen, silent = light(1, True, 40, 100), light(2, False, 0, 0)

    class FakeApi:
        def __init__(self):
            self.callback = None
            self._command_client = self

        @classmethod
        async def create(cls, auth):
            return cls()

        def set_update_callback(self, callback):
            self.callback = callback

        async def update_mesh_devices(self):
            async def report():
                await asyncio.sleep(0.05)
                self.callback({seen.unique_id: seen})

            asyncio.get_running_loop().create_task(report())

        def get_devices(self):
            return [seen, silent]

        async def shut_down(self):
            return None

    monkeypatch.setattr(cync, "Cync", FakeApi)
    monkeypatch.setattr(
        cync, "Auth", lambda web, user=None: type("A", (), {"user": user})()
    )
    monkeypatch.setattr(cync, "STATE_SETTLE_SECONDS", 0.05)
    states = cync.read_states(TOKENS)
    assert states == {"7-1": {"on": True, "brightness": 40, "color_temp": 100}}
