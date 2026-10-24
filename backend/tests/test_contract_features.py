"""Feature contract: integration on/off switches, the TV remote, and QR codes
for authenticator setup.

Written by the reviewer (UI and settings phase). Do not edit, skip, mark or
delete these tests. If one looks wrong, stop and report the test name and its
full failure output instead of changing it.
"""

import json
import urllib.parse

import segno

from app.models import AuditEvent, Device

ACCOUNT = "/api/v1/account"
INTEGRATION_IDS = ["simulated", "cync", "samsung_tv", "rheem_econet", "frigate"]


def home_url(home_id, suffix=""):
    return f"/api/v1/homes/{home_id}{suffix}"


def events(db, event_type):
    db.expire_all()
    return db.query(AuditEvent).filter(AuditEvent.event_type == event_type).all()


def state_of(db, device_id):
    db.expire_all()
    return json.loads(db.get(Device, device_id).state or "{}")


# ------------------------------------------------------------ integrations


def test_integrations_list_and_defaults(client, owner, make_user, login):
    member = make_user(owner.home_id, role="member")
    assert client.get(home_url(owner.home_id, "/integrations")).status_code == 401
    assert login(client, member).status_code == 200
    r = client.get(home_url(owner.home_id, "/integrations"))
    assert r.status_code == 200, r.text
    rows = r.json()
    assert [row["id"] for row in rows] == INTEGRATION_IDS
    for row in rows:
        assert set(row) == {"id", "name", "description", "enabled", "available"}
        assert row["name"] and row["description"]
    by_id = {row["id"]: row for row in rows}
    assert by_id["simulated"]["enabled"] is True
    assert by_id["simulated"]["available"] is True
    for other in INTEGRATION_IDS[1:]:
        assert by_id[other]["enabled"] is False, (
            other
        )  # no outbound calls until switched on
        assert by_id[other]["available"] is True, other  # all built
    assert by_id["cync"]["name"] == "GE Cync"


def test_only_owner_toggles_integrations(
    client, new_client, db, owner, make_user, make_home, login, csrf
):
    url = home_url(owner.home_id, "/integrations/cync")
    admin = make_user(owner.home_id, role="operator")
    admin_client = new_client()
    assert login(admin_client, admin).status_code == 200
    assert (
        admin_client.put(
            url, json={"enabled": True}, headers=csrf(admin_client)
        ).status_code
        == 403
    )

    assert login(client, owner).status_code == 200
    assert client.put(url, json={"enabled": True}).status_code == 403  # no CSRF
    assert (
        client.put(
            home_url(owner.home_id, "/integrations/acme"),
            json={"enabled": True},
            headers=csrf(client),
        ).status_code
        == 404
    )
    for bad in ({"enabled": "maybe"}, {"enabled": 1}, {}, {"enabled": True, "x": 1}):
        assert client.put(url, json=bad, headers=csrf(client)).status_code == 422, bad
    r = client.put(url, json={"enabled": True}, headers=csrf(client))
    assert r.status_code == 200, r.text
    assert r.json()["id"] == "cync" and r.json()["enabled"] is True
    rows = {
        row["id"]: row
        for row in client.get(home_url(owner.home_id, "/integrations")).json()
    }
    assert rows["cync"]["enabled"] is True
    toggled = events(db, "integration_toggled")
    assert toggled and toggled[-1].home_id == owner.home_id

    other_owner = make_user(make_home("Home B"), role="owner")
    other = new_client()
    assert login(other, other_owner).status_code == 200
    other_rows = {
        row["id"]: row
        for row in other.get(home_url(other_owner.home_id, "/integrations")).json()
    }
    assert other_rows["cync"]["enabled"] is False  # per home
    assert other.get(home_url(owner.home_id, "/integrations")).status_code == 404


def test_turned_off_integration_refuses_commands_and_new_devices(
    client, db, owner, make_device, login, csrf
):
    lamp = make_device(owner.home_id, name="Lamp")
    assert login(client, owner).status_code == 200
    toggle = home_url(owner.home_id, "/integrations/simulated")
    command = home_url(owner.home_id, f"/devices/{lamp}/command")
    on = {"command": "turn_on", "payload": {}}

    assert (
        client.put(toggle, json={"enabled": False}, headers=csrf(client)).status_code
        == 200
    )
    # Turning Demo devices off deletes them (and turning it on adds them).
    assert client.post(command, json=on, headers=csrf(client)).status_code == 404
    db.expire_all()
    assert db.get(Device, lamp) is None
    new = {"name": "Lamp 2", "type": "light", "integration": "simulated"}
    assert (
        client.post(
            home_url(owner.home_id, "/devices"), json=new, headers=csrf(client)
        ).status_code
        == 409
    )

    assert (
        client.put(toggle, json={"enabled": True}, headers=csrf(client)).status_code
        == 200
    )
    demo = (
        db.query(Device).filter_by(home_id=owner.home_id, integration="simulated").all()
    )
    assert {d.name for d in demo} == {
        "Living room lamp",
        "Coffee maker plug",
        "Hall thermostat",
        "Living room TV",
        "Water heater",
    }
    lamp = next(d.id for d in demo if d.type == "light")
    command = home_url(owner.home_id, f"/devices/{lamp}/command")
    assert client.post(command, json=on, headers=csrf(client)).status_code == 200
    assert state_of(db, lamp)["on"] is True


# ------------------------------------------------------------ TV remote


def tv_command(client, csrf, home_id, device_id, command, **payload):
    return client.post(
        home_url(home_id, f"/devices/{device_id}/command"),
        json={"command": command, "payload": payload},
        headers=csrf(client),
    )


def test_tv_remote_commands(client, db, owner, make_device, login, csrf):
    tv = make_device(owner.home_id, device_type="tv", name="Living room TV")
    assert login(client, owner).status_code == 200

    def send(command, **payload):
        r = tv_command(client, csrf, owner.home_id, tv, command, **payload)
        assert r.status_code == 200, (command, payload, r.text)
        assert r.json()["state"] == state_of(db, tv)
        return r.json()["state"]

    state = send("turn_on")
    assert state == {
        "on": True,
        "volume": 10,
        "muted": False,
        "channel": 1,
        "input": "tv",
        "app": None,
        "last_key": None,
    }
    assert send("volume_up")["volume"] == 11
    send("volume_down")
    assert send("volume_down")["volume"] == 9
    assert send("set_volume", level=30)["volume"] == 30
    assert send("toggle_mute")["muted"] is True
    state = send("volume_up")
    assert (state["volume"], state["muted"]) == (31, False)
    assert send("set_volume", level=100)["volume"] == 100
    assert send("volume_up")["volume"] == 100  # stays at the top
    assert send("set_volume", level=0)["volume"] == 0
    assert send("volume_down")["volume"] == 0

    assert send("channel_up")["channel"] == 2
    assert send("channel_down")["channel"] == 1
    assert send("channel_down")["channel"] == 1  # never below 1
    assert send("set_channel", channel=505)["channel"] == 505

    state = send("set_input", source="hdmi2")
    assert state["input"] == "hdmi2"
    assert send("launch_app", app="netflix")["app"] == "netflix"
    state = send("press_key", key="up")
    assert (state["last_key"], state["app"]) == ("up", "netflix")
    assert send("press_key", key="home")["app"] is None
    state = send("set_channel", channel=7)
    assert (state["input"], state["channel"]) == ("tv", 7)  # channels switch back to TV

    for key in (
        "down",
        "left",
        "right",
        "select",
        "back",
        "menu",
        "info",
        "guide",
        "play",
        "pause",
        "stop",
        "rewind",
        "fast_forward",
    ):
        assert send("press_key", key=key)["last_key"] == key
    for source in ("tv", "hdmi1", "hdmi3", "hdmi4", "usb"):
        assert send("set_input", source=source)["input"] == source
    for app in ("youtube", "prime_video", "disney_plus", "hulu", "spotify"):
        assert send("launch_app", app=app)["app"] == app
    assert send("turn_off")["on"] is False


def test_tv_remote_validates_input(client, db, owner, make_device, login, csrf):
    tv = make_device(owner.home_id, device_type="tv", name="TV")
    assert login(client, owner).status_code == 200
    assert tv_command(client, csrf, owner.home_id, tv, "turn_on").status_code == 200
    before = state_of(db, tv)
    bad = [
        ("set_volume", {"level": 101}),
        ("set_volume", {"level": -1}),
        ("set_volume", {"level": "5"}),
        ("set_volume", {"level": True}),
        ("set_volume", {"level": 5.5}),
        ("set_volume", {}),
        ("set_channel", {"channel": 0}),
        ("set_channel", {"channel": 10000}),
        ("set_input", {"source": "vga"}),
        ("press_key", {"key": "explode"}),
        ("launch_app", {"app": "anything"}),
        ("volume_up", {"step": 5}),
        ("rewind_time", {}),
    ]
    for command, payload in bad:
        r = tv_command(client, csrf, owner.home_id, tv, command, **payload)
        assert r.status_code == 422, (command, payload, r.status_code)
    assert state_of(db, tv) == before


def test_tv_that_is_off_only_turns_on(client, db, owner, make_device, login, csrf):
    tv = make_device(owner.home_id, device_type="tv", name="TV")
    assert login(client, owner).status_code == 200
    for command, payload in (
        ("volume_up", {}),
        ("set_channel", {"channel": 3}),
        ("press_key", {"key": "up"}),
    ):
        r = tv_command(client, csrf, owner.home_id, tv, command, **payload)
        assert r.status_code == 409, command
    assert state_of(db, tv) == {}
    assert tv_command(client, csrf, owner.home_id, tv, "turn_on").status_code == 200


def test_remote_commands_are_only_for_tvs(client, owner, make_device, login, csrf):
    lamp = make_device(owner.home_id, name="Lamp")
    assert login(client, owner).status_code == 200
    assert tv_command(client, csrf, owner.home_id, lamp, "turn_on").status_code == 200
    assert tv_command(client, csrf, owner.home_id, lamp, "volume_up").status_code == 422


# ------------------------------------------------------------ QR codes


def expected_qr(otpauth_uri):
    """Exactly how the backend must draw it (app/auth.py totp_qr_svg)."""
    return segno.make(otpauth_uri, error="m").svg_data_uri(
        scale=4, border=2, dark="#000000", light="#ffffff"
    )


def assert_is_svg_data_uri(value):
    assert value.startswith("data:image/svg+xml")
    svg = urllib.parse.unquote(value.split(",", 1)[1])
    assert svg.lstrip().startswith("<svg") or svg.lstrip().startswith("<?xml")
    for banned in ("<script", "href=", "javascript:"):
        assert banned not in svg


def test_authenticator_setup_includes_qr_code(client, owner, login, csrf):
    assert login(client, owner).status_code == 200
    r = client.post(
        f"{ACCOUNT}/totp/setup", json={"password": owner.password}, headers=csrf(client)
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert_is_svg_data_uri(body["qr_svg"])
    assert body["qr_svg"] == expected_qr(body["otpauth_uri"])
    assert body["secret"] in urllib.parse.unquote(body["otpauth_uri"])


def test_enrollment_includes_qr_code_for_new_accounts(
    client, new_client, owner, make_home, make_user, login, csrf
):
    assert login(client, owner).status_code == 200
    url = home_url(owner.home_id, "/members/enrollments")
    code = client.post(
        url, json={"email": "qr@example.com", "role": "member"}, headers=csrf(client)
    ).json()["enrollment_code"]
    start = new_client().post("/api/v1/enroll/start", json={"code": code}).json()
    assert_is_svg_data_uri(start["qr_svg"])
    assert start["qr_svg"] == expected_qr(start["otpauth_uri"])

    existing = make_user(make_home("Home B"), role="owner")
    code = client.post(
        url, json={"email": existing.email, "role": "member"}, headers=csrf(client)
    ).json()["enrollment_code"]
    start = new_client().post("/api/v1/enroll/start", json={"code": code}).json()
    assert start["existing_account"] is True and "qr_svg" not in start
