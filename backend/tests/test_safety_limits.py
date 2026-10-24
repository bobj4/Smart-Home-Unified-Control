"""Safety limits: owner-only changes, hard bounds, units, enforcement, audit.
Written by the reviewer (Review 3)."""

import json

from app.models import AuditEvent, Device
from scripts.set_safety_limits import main as set_limits_cli

THERMOSTAT_F = {"unit": "F", "min_temperature": 60, "max_temperature": 80}


def limits_url(home_id, device_type=""):
    url = f"/api/v1/homes/{home_id}/safety-limits"
    return f"{url}/{device_type}" if device_type else url


def command(client, csrf, home_id, device_id, temperature):
    return client.post(
        f"/api/v1/homes/{home_id}/devices/{device_id}/command",
        json={"command": "set_temperature", "payload": {"temperature": temperature}},
        headers=csrf(client),
    )


def events(db, event_type):
    db.expire_all()
    return db.query(AuditEvent).filter(AuditEvent.event_type == event_type).all()


def test_owner_sets_limits_then_thermostat_obeys_them(
    client, db, owner, make_device, login, csrf
):
    device_id = make_device(owner.home_id, device_type="thermostat", name="Hall")
    assert login(client, owner).status_code == 200
    r = client.put(
        limits_url(owner.home_id, "thermostat"), json=THERMOSTAT_F, headers=csrf(client)
    )
    assert r.status_code == 200, r.text
    assert r.json() == {
        "device_type": "thermostat",
        "enabled": True,
        "default_target": None,
        **THERMOSTAT_F,
    }

    r = command(client, csrf, owner.home_id, device_id, 70)
    assert r.status_code == 200, r.text
    assert r.json()["state"] == {"target_temperature": 70, "unit": "F"}

    for outside in (59, 81, 120):
        assert (
            command(client, csrf, owner.home_id, device_id, outside).status_code == 422
        )
    db.expire_all()
    assert json.loads(db.get(Device, device_id).state)["target_temperature"] == 70
    assert len(events(db, "device_command_rejected")) == 3


def test_limit_changes_are_audited_with_old_and_new_values(
    client, db, owner, login, csrf
):
    assert login(client, owner).status_code == 200
    url = limits_url(owner.home_id, "thermostat")
    client.put(url, json=THERMOSTAT_F, headers=csrf(client))
    client.put(url, json={**THERMOSTAT_F, "max_temperature": 78}, headers=csrf(client))
    changes = events(db, "safety_limits_changed")
    assert len(changes) == 2
    second = json.loads(changes[-1].details)
    assert second["old"]["max_temperature"] == 80
    assert second["new"]["max_temperature"] == 78
    assert str(changes[-1].user_id) == owner.id


def test_only_owner_can_change_limits(client, owner, make_user, login, csrf):
    for role in ("operator", "member"):
        user = make_user(owner.home_id, role=role)
        client.cookies.clear()
        assert login(client, user).status_code == 200
        r = client.put(
            limits_url(owner.home_id, "thermostat"),
            json=THERMOSTAT_F,
            headers=csrf(client),
        )
        assert r.status_code == 403, role
        assert client.get(limits_url(owner.home_id)).status_code == 200


def test_other_homes_limits_are_not_reachable(
    client, owner, make_home, make_user, login, csrf
):
    other_home = make_home("Home B")
    make_user(other_home, role="owner")
    assert login(client, owner).status_code == 200
    assert client.get(limits_url(other_home)).status_code == 404
    r = client.put(
        limits_url(other_home, "thermostat"), json=THERMOSTAT_F, headers=csrf(client)
    )
    assert r.status_code == 404


def test_limits_require_csrf(client, owner, login):
    assert login(client, owner).status_code == 200
    r = client.put(limits_url(owner.home_id, "thermostat"), json=THERMOSTAT_F)
    assert r.status_code == 403


def test_invalid_limits_are_refused(client, owner, login, csrf):
    assert login(client, owner).status_code == 200
    url = limits_url(owner.home_id, "thermostat")
    bad = [
        {**THERMOSTAT_F, "min_temperature": 80, "max_temperature": 60},  # min > max
        {**THERMOSTAT_F, "max_temperature": 120},  # above hard bound
        {**THERMOSTAT_F, "min_temperature": 20},  # below hard bound
        {**THERMOSTAT_F, "unit": "K"},
        {**THERMOSTAT_F, "extra": 1},
    ]
    for body in bad:
        assert client.put(url, json=body, headers=csrf(client)).status_code == 422, body
    light = limits_url(owner.home_id, "light")
    assert client.put(light, json=THERMOSTAT_F, headers=csrf(client)).status_code == 422


def test_celsius_bounds_are_converted(client, owner, login, csrf):
    assert login(client, owner).status_code == 200
    url = limits_url(owner.home_id, "water_heater")
    ok = {"unit": "C", "min_temperature": 40, "max_temperature": 55}
    assert client.put(url, json=ok, headers=csrf(client)).status_code == 200
    too_hot = {"unit": "C", "min_temperature": 40, "max_temperature": 65}
    assert client.put(url, json=too_hot, headers=csrf(client)).status_code == 422


def test_cli_sets_limits_for_the_only_home(db, owner):
    assert set_limits_cli(["thermostat", "60", "80", "F"]) == 0
    change = events(db, "safety_limits_changed")[-1]
    assert change.home_id == owner.home_id
    assert json.loads(change.details)["new"]["min_temperature"] == 60
    assert set_limits_cli(["thermostat", "60", "100", "F"]) == 1  # above hard bound
