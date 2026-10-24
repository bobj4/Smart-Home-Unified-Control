"""Guests: below member, refused by every ordinary home route, allowed only
what their admin ticks in the Access window, checked on every request."""

import json

import pytest

from app.models import AuditEvent, Device, Home
from app.safety import apply_recommended


@pytest.fixture
def home(db, owner, make_user, make_device):
    apply_recommended(db, owner.home_id, None, None)
    ids = {
        "lamp": make_device(owner.home_id, name="Lamp"),
        "plug": make_device(owner.home_id, device_type="plug", name="Kettle"),
        "hall": make_device(owner.home_id, device_type="thermostat", name="Hall"),
        "den": make_device(owner.home_id, device_type="thermostat", name="Den"),
        "heater": make_device(owner.home_id, device_type="water_heater", name="Tank"),
        "tv": make_device(owner.home_id, device_type="tv", name="TV"),
    }
    guest = make_user(owner.home_id, role="guest")
    return {"ids": ids, "guest": guest, "home_id": owner.home_id}


def base(home_id):
    return f"/api/v1/homes/{home_id}"


def access_url(home_id, user_id):
    return f"{base(home_id)}/members/{user_id}/guest-access"


NONE = {
    "light_power": False,
    "light_settings": False,
    "cameras": False,
    "water_heater": False,
    "show_blocked": False,
    "thermostat_ids": [],
}


def grant(new_client, login, csrf, owner, home, **changes):
    admin = new_client()
    assert login(admin, owner).status_code == 200
    body = {**NONE, **changes}
    r = admin.put(
        access_url(home["home_id"], home["guest"].id), json=body, headers=csrf(admin)
    )
    assert r.status_code == 200, r.text
    return r.json()


def as_guest(client, login, home):
    assert login(client, home["guest"]).status_code == 200
    return client


def command(client, csrf, home, key, name, payload=None):
    return client.post(
        f"{base(home['home_id'])}/guest/devices/{home['ids'][key]}/command",
        json={"command": name, "payload": payload or {}},
        headers=csrf(client),
    )


def test_refused_by_every_ordinary_route(client, login, csrf, home):
    as_guest(client, login, home)
    h = base(home["home_id"])
    for path in (
        "/devices",
        "/safety-limits",
        "/members",
        "/groups",
        "/integrations",
        "/audit",
        f"/devices/{home['ids']['lamp']}",
    ):
        assert client.get(h + path).status_code == 403, path
    r = client.post(
        f"{h}/devices/{home['ids']['lamp']}/command",
        json={"command": "turn_on", "payload": {}},
        headers=csrf(client),
    )
    assert r.status_code == 403  # the member route stays closed to guests
    # Their own account and room order still work.
    assert client.get("/api/v1/account").json()["homes"][0]["role"] == "guest"
    assert client.get(f"{h}/layout").status_code == 200


def test_nothing_until_an_admin_allows_it(client, login, csrf, home):
    as_guest(client, login, home)
    page = client.get(f"{base(home['home_id'])}/guest").json()
    assert page["devices"] == [] and page["access"] == NONE
    assert command(client, csrf, home, "lamp", "turn_on").status_code == 404


def test_light_power_without_settings(client, new_client, login, csrf, owner, home, db):
    grant(new_client, login, csrf, owner, home, light_power=True)
    as_guest(client, login, home)
    page = client.get(f"{base(home['home_id'])}/guest").json()
    assert {d["name"] for d in page["devices"]} == {"Lamp", "Kettle"}
    assert all("network" not in d for d in page["devices"])
    assert command(client, csrf, home, "lamp", "turn_on").status_code == 200
    assert command(client, csrf, home, "plug", "turn_on").status_code == 200
    r = command(client, csrf, home, "lamp", "set_brightness", {"brightness": 40})
    assert r.status_code == 403
    refused = db.query(AuditEvent).filter_by(event_type="guest_command_refused").one()
    assert json.loads(refused.details)["command"] == "set_brightness"
    db.expire_all()
    assert json.loads(db.get(Device, home["ids"]["lamp"]).state)["on"] is True


def test_light_settings(client, new_client, login, csrf, owner, home):
    grant(new_client, login, csrf, owner, home, light_settings=True)
    as_guest(client, login, home)
    names = {
        d["name"]
        for d in client.get(f"{base(home['home_id'])}/guest").json()["devices"]
    }
    assert names == {"Lamp"}  # plugs have no settings
    r = command(client, csrf, home, "lamp", "set_brightness", {"brightness": 40})
    assert r.status_code == 200
    assert command(client, csrf, home, "lamp", "turn_on").status_code == 403


def test_thermostats_one_by_one_within_limits(
    client, new_client, login, csrf, owner, home
):
    grant(new_client, login, csrf, owner, home, thermostat_ids=[home["ids"]["hall"]])
    as_guest(client, login, home)
    names = {
        d["name"]
        for d in client.get(f"{base(home['home_id'])}/guest").json()["devices"]
    }
    assert names == {"Hall"}
    ok = command(client, csrf, home, "hall", "set_temperature", {"temperature": 70})
    assert ok.status_code == 200, ok.text
    too_hot = command(
        client, csrf, home, "hall", "set_temperature", {"temperature": 120}
    )
    assert too_hot.status_code == 422  # the safety limits still apply
    assert (
        command(
            client, csrf, home, "den", "set_temperature", {"temperature": 70}
        ).status_code
        == 404
    )


def test_water_heater(client, new_client, login, csrf, owner, home):
    grant(new_client, login, csrf, owner, home, water_heater=True)
    as_guest(client, login, home)
    r = command(client, csrf, home, "heater", "set_temperature", {"temperature": 115})
    assert r.status_code == 200, r.text


def test_blocked_devices_shown_greyed_without_state(
    client, new_client, login, csrf, owner, home, db
):
    lamp = db.get(Device, home["ids"]["lamp"])
    lamp.state = json.dumps({"on": True, "brightness": 90})
    db.commit()
    grant(new_client, login, csrf, owner, home, show_blocked=True)
    as_guest(client, login, home)
    devices = client.get(f"{base(home['home_id'])}/guest").json()["devices"]
    assert len(devices) == 6 and all(d["blocked"] for d in devices)
    assert all(d["state"] == {} for d in devices)  # never a blocked device's state
    assert command(client, csrf, home, "lamp", "turn_on").status_code == 403
    assert command(client, csrf, home, "tv", "turn_on").status_code == 403


def test_cameras_need_the_permission(client, new_client, login, csrf, owner, home):
    as_guest(client, login, home)
    url = f"{base(home['home_id'])}/cameras"
    assert client.get(url).status_code == 403
    grant(new_client, login, csrf, owner, home, cameras=True)
    assert client.get(url).status_code != 403  # Frigate is not set up in tests


def test_only_admins_set_access(
    client, new_client, login, csrf, owner, home, make_user
):
    member = make_user(owner.home_id, role="member")
    c = new_client()
    assert login(c, member).status_code == 200
    url = access_url(home["home_id"], home["guest"].id)
    assert c.get(url).status_code == 403
    assert c.put(url, json=NONE, headers=csrf(c)).status_code == 403
    assert login(client, owner).status_code == 200
    not_guest = access_url(home["home_id"], member.id)
    assert client.get(not_guest).status_code == 409


def test_access_input_is_checked(
    client, login, csrf, owner, home, make_home, make_user, make_device
):
    other = make_device(make_home("Elsewhere"), device_type="thermostat", name="Theirs")
    assert login(client, owner).status_code == 200
    url = access_url(home["home_id"], home["guest"].id)
    for bad in (
        {**NONE, "thermostat_ids": [other]},
        {**NONE, "thermostat_ids": [home["ids"]["lamp"]]},
        {**NONE, "cameras": "yes"},
        {**NONE, "extra": True},
    ):
        assert client.put(url, json=bad, headers=csrf(client)).status_code == 422, bad


def test_role_changes_to_and_from_guest(client, login, csrf, owner, make_user):
    member = make_user(owner.home_id, role="member")
    assert login(client, owner).status_code == 200
    url = f"{base(owner.home_id)}/members/{member.id}"
    r = client.patch(url, json={"role": "guest"}, headers=csrf(client))
    assert r.status_code == 200, r.text
    rows = {
        m["user_id"]: m for m in client.get(f"{base(owner.home_id)}/members").json()
    }
    assert rows[member.id]["role"] == "guest"
    assert client.get(access_url(owner.home_id, member.id)).json() == NONE


def test_home_requiring_two_factor_still_applies(client, login, home, db):
    db.get(Home, home["home_id"]).require_two_factor = True
    db.commit()
    as_guest(client, login, home)  # the guest has two-factor on: allowed
    assert client.get(f"{base(home['home_id'])}/guest").status_code == 200


def test_guest_without_two_factor_refused_where_required(client, home, db):
    from app.models import User

    db.get(Home, home["home_id"]).require_two_factor = True
    db.get(User, home["guest"].id).is_totp_enabled = False
    db.commit()
    body = {"email": home["guest"].email, "password": home["guest"].password}
    assert client.post("/api/v1/auth/login", json=body).status_code == 200
    assert client.get(f"{base(home['home_id'])}/guest").status_code == 403
