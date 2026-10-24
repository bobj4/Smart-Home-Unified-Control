"""Samsung TV contract: adding and pairing TVs, remote commands to real TVs.

Written by the reviewer (TV and two-factor phase). Do not edit, skip, mark or
delete these tests. If one looks wrong, stop and report the test name and its
full failure output instead of changing it.

Nothing here talks to a TV: the functions in app.integrations.samsung are
replaced by FakeTv. The owner tests a real TV by hand.
"""

import json

import pytest
from cryptography.fernet import Fernet

from app.integrations import samsung
from app.models import AuditEvent, Device

HOST = "192.168.1.50"
TOKEN = "tv-token-123"


def url(home_id, suffix):
    return f"/api/v1/homes/{home_id}{suffix}"


class FakeTv:
    def __init__(self):
        self.keys = []  # (host, protocol, token, [keys])
        self.apps = []
        self.wakes = []
        self.paired = []
        self.fail = None

    def _maybe_fail(self):
        if self.fail:
            error, self.fail = self.fail, None
            raise error

    def pair(self, host, protocol):
        self._maybe_fail()
        self.paired.append((host, protocol))
        return TOKEN if protocol == "tizen" else None

    def send_keys(self, host, protocol, token, keys):
        self._maybe_fail()
        self.keys.append((host, protocol, token, list(keys)))

    def launch_app(self, host, protocol, token, app):
        self._maybe_fail()
        if protocol != "tizen":
            raise samsung.TvUnsupported("no apps")
        self.apps.append((host, token, app))

    def wake(self, mac):
        self._maybe_fail()
        self.wakes.append(mac)


@pytest.fixture
def tv(monkeypatch):
    fake = FakeTv()
    for name in ("pair", "send_keys", "launch_app", "wake"):
        monkeypatch.setattr(samsung, name, getattr(fake, name))
    return fake


@pytest.fixture
def secrets_key(monkeypatch):
    monkeypatch.setenv("SECRETS_KEY", Fernet.generate_key().decode())


def turn_on(client, csrf, home_id, enabled=True):
    r = client.put(
        url(home_id, "/integrations/samsung_tv"),
        json={"enabled": enabled},
        headers=csrf(client),
    )
    assert r.status_code == 200, r.text


def add(client, csrf, home_id, **changes):
    body = {"name": "Living room TV", "host": HOST, **changes}
    return client.post(
        url(home_id, "/integrations/samsung_tv/tvs"), json=body, headers=csrf(client)
    )


def pair(client, csrf, home_id, device_id):
    return client.post(
        url(home_id, f"/integrations/samsung_tv/tvs/{device_id}/pair"),
        headers=csrf(client),
    )


def command(client, csrf, home_id, device_id, name, **payload):
    return client.post(
        url(home_id, f"/devices/{device_id}/command"),
        json={"command": name, "payload": payload},
        headers=csrf(client),
    )


def ready_tv(client, csrf, login, owner, tv, **changes):
    """Owner logged in, Samsung on, one paired TV that is on. Returns its id."""
    assert login(client, owner).status_code == 200
    turn_on(client, csrf, owner.home_id)
    device_id = add(client, csrf, owner.home_id, **changes).json()["device_id"]
    assert pair(client, csrf, owner.home_id, device_id).status_code == 200
    assert command(client, csrf, owner.home_id, device_id, "turn_on").status_code == 200
    tv.keys.clear()
    tv.wakes.clear()
    return device_id


# ------------------------------------------------------------ S1: adapter (reviewer's)


def test_samsung_command_keys():
    keys = samsung.command_keys
    assert keys("turn_off", {}) == ["KEY_POWER"]
    assert keys("volume_up", {}) == ["KEY_VOLUP"]
    assert keys("volume_down", {}) == ["KEY_VOLDOWN"]
    assert keys("toggle_mute", {}) == ["KEY_MUTE"]
    assert keys("channel_up", {}) == ["KEY_CHUP"]
    assert keys("channel_down", {}) == ["KEY_CHDOWN"]
    assert keys("set_channel", {"channel": 505}) == [
        "KEY_5",
        "KEY_0",
        "KEY_5",
        "KEY_ENTER",
    ]
    assert keys("set_input", {"source": "hdmi2"}) == ["KEY_HDMI2"]
    assert keys("press_key", {"key": "select"}) == ["KEY_ENTER"]
    assert keys("press_key", {"key": "back"}) == ["KEY_RETURN"]
    for command_name in ("set_volume", "launch_app", "turn_on"):
        with pytest.raises(samsung.TvUnsupported):
            keys(command_name, {})


def test_samsung_every_remote_key_and_app_is_mapped():
    from app.tv import APPS, INPUTS, KEYS

    assert set(samsung.PRESS_KEYS) == set(KEYS)
    assert set(samsung.INPUT_KEYS) == set(INPUTS)
    assert set(samsung.APP_IDS) == set(APPS)


def test_samsung_is_available(client, owner, login):
    assert login(client, owner).status_code == 200
    rows = {r["id"]: r for r in client.get(url(owner.home_id, "/integrations")).json()}
    assert rows["samsung_tv"]["available"] is True
    assert rows["samsung_tv"]["enabled"] is False


# ------------------------------------------------------------ S2: adding TVs


def test_samsung_admin_adds_tv(
    client, new_client, db, owner, make_user, login, csrf, tv
):
    member = make_user(owner.home_id, role="member")
    member_client = new_client()
    assert login(member_client, member).status_code == 200
    assert login(client, owner).status_code == 200
    assert add(client, csrf, owner.home_id).status_code == 409  # integration off
    turn_on(client, csrf, owner.home_id)
    assert add(member_client, csrf, owner.home_id).status_code == 403
    assert (
        member_client.get(
            url(owner.home_id, "/integrations/samsung_tv/tvs")
        ).status_code
        == 403
    )

    for bad in (
        {"host": "8.8.8.8"},  # not on the home network
        {"host": "127.0.0.1"},
        {"host": "tv.example.com"},
        {"protocol": "webos"},  # not a Samsung protocol
        {"mac": "not-a-mac"},
        {"name": ""},
        {"secret": "x"},
    ):
        assert add(client, csrf, owner.home_id, **bad).status_code == 422, bad

    admin = make_user(owner.home_id, role="admin")
    admin_client = new_client()
    assert login(admin_client, admin).status_code == 200
    r = add(
        admin_client, csrf, owner.home_id, mac="aa-bb-cc-dd-ee-ff", room="Living room"
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body == {
        "device_id": body["device_id"],
        "name": "Living room TV",
        "host": HOST,
        "protocol": "tizen",
        "mac": "AA:BB:CC:DD:EE:FF",
        "paired": False,
    }
    assert add(client, csrf, owner.home_id).status_code == 409  # same address again
    legacy = add(
        client,
        csrf,
        owner.home_id,
        name="Bedroom TV",
        host="192.168.1.51",
        protocol="legacy",
    )
    assert legacy.status_code == 201 and legacy.json()["protocol"] == "legacy"

    listed = client.get(url(owner.home_id, "/integrations/samsung_tv/tvs")).json()
    assert [t["name"] for t in listed] == ["Bedroom TV", "Living room TV"]
    db.expire_all()
    device = db.get(Device, body["device_id"])
    assert (device.type, device.integration, device.external_id, device.room) == (
        "tv",
        "samsung_tv",
        HOST,
        "Living room",
    )
    assert db.query(AuditEvent).filter_by(event_type="tv_added").count() == 2
    assert tv.paired == []  # adding does not contact the TV


def test_samsung_tvs_are_per_home(
    client, new_client, owner, make_home, make_user, login, csrf, tv
):
    assert login(client, owner).status_code == 200
    turn_on(client, csrf, owner.home_id)
    device_id = add(client, csrf, owner.home_id).json()["device_id"]
    other_owner = make_user(make_home("Home B"), role="owner")
    other = new_client()
    assert login(other, other_owner).status_code == 200
    turn_on(other, csrf, other_owner.home_id)
    assert (
        other.get(url(other_owner.home_id, "/integrations/samsung_tv/tvs")).json() == []
    )
    assert pair(other, csrf, other_owner.home_id, device_id).status_code == 404
    gone = other.delete(
        url(other_owner.home_id, f"/integrations/samsung_tv/tvs/{device_id}"),
        headers=csrf(other),
    )
    assert gone.status_code == 404


# ------------------------------------------------------------ S3: pairing


def test_samsung_pairing_keeps_token_encrypted(
    client, db, owner, login, csrf, tv, secrets_key
):
    from app.models import IntegrationCredential

    assert login(client, owner).status_code == 200
    turn_on(client, csrf, owner.home_id)
    device_id = add(client, csrf, owner.home_id).json()["device_id"]
    r = pair(client, csrf, owner.home_id, device_id)
    assert r.status_code == 200, r.text
    assert r.json()["paired"] is True and TOKEN not in r.text
    assert tv.paired == [(HOST, "tizen")]
    db.expire_all()
    assert db.get(Device, device_id).online is True
    row = db.query(IntegrationCredential).one()
    assert TOKEN not in row.secret
    assert db.query(AuditEvent).filter_by(event_type="tv_paired").count() == 1

    gone = client.delete(
        url(owner.home_id, f"/integrations/samsung_tv/tvs/{device_id}"),
        headers=csrf(client),
    )
    assert gone.status_code == 200
    db.expire_all()
    assert db.get(Device, device_id) is None
    assert db.query(IntegrationCredential).count() == 0  # its token goes too


def test_samsung_pairing_failures(
    client, db, owner, login, csrf, tv, secrets_key, monkeypatch
):
    assert login(client, owner).status_code == 200
    turn_on(client, csrf, owner.home_id)
    device_id = add(client, csrf, owner.home_id).json()["device_id"]
    tv.fail = samsung.TvDenied("denied")
    assert pair(client, csrf, owner.home_id, device_id).status_code == 409
    tv.fail = samsung.TvError("could not reach the TV: TimeoutError")
    assert pair(client, csrf, owner.home_id, device_id).status_code == 502
    monkeypatch.delenv("SECRETS_KEY")
    assert (
        pair(client, csrf, owner.home_id, device_id).status_code == 409
    )  # token cannot be kept
    db.expire_all()
    assert json.loads(db.get(Device, device_id).capabilities)["paired"] is False
    assert db.query(AuditEvent).filter_by(event_type="tv_pair_failed").count() == 3


def test_samsung_legacy_pairs_without_a_token(
    client, db, owner, login, csrf, tv, monkeypatch
):
    monkeypatch.delenv("SECRETS_KEY", raising=False)  # legacy TVs need no stored token
    assert login(client, owner).status_code == 200
    turn_on(client, csrf, owner.home_id)
    device_id = add(client, csrf, owner.home_id, protocol="legacy").json()["device_id"]
    r = pair(client, csrf, owner.home_id, device_id)
    assert r.status_code == 200 and r.json()["paired"] is True
    assert tv.paired == [(HOST, "legacy")]


# ------------------------------------------------------------ S4: commands


def test_samsung_remote_sends_keys(
    client, new_client, owner, make_user, login, csrf, tv, secrets_key
):
    device_id = ready_tv(client, csrf, login, owner, tv)
    home = owner.home_id
    assert command(client, csrf, home, device_id, "volume_up").status_code == 200
    assert (
        command(client, csrf, home, device_id, "set_channel", channel=42).status_code
        == 200
    )
    assert (
        command(client, csrf, home, device_id, "press_key", key="home").status_code
        == 200
    )
    assert tv.keys == [
        (HOST, "tizen", TOKEN, ["KEY_VOLUP"]),
        (HOST, "tizen", TOKEN, ["KEY_4", "KEY_2", "KEY_ENTER"]),
        (HOST, "tizen", TOKEN, ["KEY_HOME"]),
    ]
    r = command(client, csrf, home, device_id, "launch_app", app="netflix")
    assert r.status_code == 200 and tv.apps == [(HOST, TOKEN, "netflix")]
    assert r.json()["state"]["app"] == "netflix"

    member = make_user(home, role="member")
    member_client = new_client()
    assert login(member_client, member).status_code == 200
    assert (
        command(member_client, csrf, home, device_id, "toggle_mute").status_code == 200
    )
    assert tv.keys[-1][3] == ["KEY_MUTE"]

    assert command(client, csrf, home, device_id, "turn_off").status_code == 200
    assert tv.keys[-1][3] == ["KEY_POWER"]


def test_samsung_power_on_uses_wake_on_lan_when_mac_is_known(
    client, owner, login, csrf, tv, secrets_key
):
    device_id = ready_tv(client, csrf, login, owner, tv, mac="AA:BB:CC:DD:EE:FF")
    home = owner.home_id
    assert command(client, csrf, home, device_id, "turn_off").status_code == 200
    assert command(client, csrf, home, device_id, "turn_on").status_code == 200
    assert tv.wakes == ["AA:BB:CC:DD:EE:FF"]
    assert tv.keys[-1][3] == ["KEY_POWER"]  # only from turn_off; turn_on woke it


def test_samsung_refusals_change_nothing(
    client, db, owner, login, csrf, tv, secrets_key
):
    device_id = ready_tv(client, csrf, login, owner, tv)
    home = owner.home_id

    def state():
        db.expire_all()
        return json.loads(db.get(Device, device_id).state)

    before = state()
    assert (
        command(client, csrf, home, device_id, "set_volume", level=20).status_code
        == 422
    )
    tv.fail = samsung.TvError("could not reach the TV: TimeoutError")
    assert command(client, csrf, home, device_id, "volume_up").status_code == 502
    tv.fail = samsung.TvDenied("denied")
    assert command(client, csrf, home, device_id, "volume_up").status_code == 409
    assert state() == before
    assert tv.keys == []
    rejected = (
        db.query(AuditEvent).filter_by(event_type="device_command_rejected").count()
    )
    assert rejected == 3

    turn_on(client, csrf, home, enabled=False)
    assert command(client, csrf, home, device_id, "volume_up").status_code == 409


def test_samsung_unpaired_and_legacy_limits(
    client, owner, login, csrf, tv, secrets_key
):
    assert login(client, owner).status_code == 200
    turn_on(client, csrf, owner.home_id)
    unpaired = add(client, csrf, owner.home_id).json()["device_id"]
    r = command(client, csrf, owner.home_id, unpaired, "turn_on")
    assert r.status_code == 409 and "pair" in r.json()["detail"]

    legacy = add(
        client,
        csrf,
        owner.home_id,
        name="Old TV",
        host="192.168.1.60",
        protocol="legacy",
    ).json()["device_id"]
    assert pair(client, csrf, owner.home_id, legacy).status_code == 200
    assert command(client, csrf, owner.home_id, legacy, "turn_on").status_code == 200
    assert tv.keys[-1] == ("192.168.1.60", "legacy", None, ["KEY_POWER"])
    assert (
        command(
            client, csrf, owner.home_id, legacy, "launch_app", app="netflix"
        ).status_code
        == 422
    )
    assert command(client, csrf, owner.home_id, legacy, "channel_up").status_code == 200
    assert tv.keys[-1] == ("192.168.1.60", "legacy", None, ["KEY_CHUP"])
