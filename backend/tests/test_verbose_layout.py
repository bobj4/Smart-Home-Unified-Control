"""Verbose logging (off by default; integration detail in the activity log)
and each user's room order on the Devices page."""

import json

from app import refresh, rheem_home, verbose
from app.db_config import SessionLocal
from app.models import AuditEvent, Device, SystemSettings

VERBOSE = "/api/v1/admin/verbose-logging"


def verbose_events(db):
    db.expire_all()
    return [
        e for e in db.query(AuditEvent).all() if e.event_type.startswith("verbose_")
    ]


def turn_on(client, csrf):
    r = client.put(VERBOSE, json={"enabled": True}, headers=csrf(client))
    assert r.status_code == 200 and r.json() == {"enabled": True}


def test_off_by_default_records_nothing_extra(client, db, owner, login, csrf):
    assert login(client, owner).status_code == 200
    assert client.get(VERBOSE).json() == {"enabled": False}
    r = client.put(
        f"/api/v1/homes/{owner.home_id}/layout",
        json={"room_order": ["Kitchen"]},
        headers=csrf(client),
    )
    assert r.status_code == 200
    assert verbose_events(db) == []


def test_change_requests_are_recorded_when_on(client, db, owner, login, csrf):
    assert login(client, owner).status_code == 200
    turn_on(client, csrf)
    client.put(
        f"/api/v1/homes/{owner.home_id}/layout",
        json={"room_order": ["Kitchen"]},
        headers=csrf(client),
    )
    client.get(f"/api/v1/homes/{owner.home_id}/layout")  # reads are not recorded
    rows = [e for e in verbose_events(db) if e.event_type == "verbose_request"]
    paths = [json.loads(e.details)["path"] for e in rows]
    assert f"/api/v1/homes/{owner.home_id}/layout" in paths
    layout = next(e for e in rows if json.loads(e.details)["path"].endswith("/layout"))
    details = json.loads(layout.details)
    assert details["method"] == "PUT" and details["status"] == 200
    assert isinstance(details["ms"], int)
    assert layout.home_id == owner.home_id  # shows in that home's activity log
    assert layout.user_id == owner.id  # and who made it


def test_login_requests_never_record_secrets(client, db, owner, login, csrf):
    assert login(client, owner).status_code == 200
    turn_on(client, csrf)
    client.post(
        "/api/v1/auth/login",
        json={"email": owner.email, "password": "wrong password!"},
    )
    text = " ".join(e.details or "" for e in verbose_events(db))
    assert "wrong password!" not in text
    assert "/api/v1/auth/login" in text


def test_device_going_offline_and_back(db, owner, make_device):
    db.merge(SystemSettings(id=1, verbose_logging=True))
    db.commit()
    device_id = make_device(owner.home_id, name="Porch")
    device = db.get(Device, device_id)
    device.online = False
    db.commit()
    device.online = True
    db.commit()
    kinds = [e.event_type for e in verbose_events(db)]
    assert kinds == ["verbose_device_offline", "verbose_device_online"]
    assert json.loads(verbose_events(db)[0].details)["device"] == "Porch"


def test_refresh_failures_are_recorded(db, owner, make_device, monkeypatch):
    db.merge(SystemSettings(id=1, verbose_logging=True))
    db.commit()
    heater = db.get(Device, make_device(owner.home_id, device_type="water_heater"))
    heater.integration = rheem_home.INTEGRATION
    db.commit()

    def unavailable(_db, _home):
        raise rheem_home.RheemUnavailable(502, "EcoNet did not answer")

    monkeypatch.setattr(rheem_home, "sync", unavailable)
    refresh._rheem_read_at.clear()
    with SessionLocal() as session:
        assert refresh.refresh_rheem(session, owner.home_id) is False
    event = next(e for e in verbose_events(db) if e.event_type == "verbose_refresh")
    assert json.loads(event.details) == {
        "integration": "rheem_econet",
        "result": "failed",
        "reason": "EcoNet did not answer",
    }


def test_only_admins_switch_it(client, owner, make_user, login, csrf):
    member = make_user(owner.home_id, role="member")
    assert login(client, member).status_code == 200
    assert client.get(VERBOSE).status_code == 403
    assert (
        client.put(VERBOSE, json={"enabled": True}, headers=csrf(client)).status_code
        == 403
    )


def test_switch_must_be_a_boolean(client, owner, login, csrf):
    assert login(client, owner).status_code == 200
    r = client.put(VERBOSE, json={"enabled": "on"}, headers=csrf(client))
    assert r.status_code == 422


def test_note_is_silent_when_off(db):
    verbose.note(db, "refresh", details={"x": 1})
    assert verbose_events(db) == []


# ------------------------------------------------------------ room layout


def test_layout_defaults_to_thermostats_first(client, owner, login):
    assert login(client, owner).status_code == 200
    r = client.get(f"/api/v1/homes/{owner.home_id}/layout")
    assert r.json() == {
        "room_order": ["Thermostats"],
        "thermostats_room": "Thermostats",
    }


def test_layout_is_per_user(client, new_client, owner, make_user, login, csrf):
    member = make_user(owner.home_id, role="member")
    assert login(client, owner).status_code == 200
    url = f"/api/v1/homes/{owner.home_id}/layout"
    order = ["Kitchen", "Thermostats", "Kitchen", "Lab"]
    r = client.put(url, json={"room_order": order}, headers=csrf(client))
    assert r.json()["room_order"] == ["Kitchen", "Thermostats", "Lab"]  # no repeats
    theirs = new_client()
    assert login(theirs, member).status_code == 200
    assert theirs.get(url).json()["room_order"] == ["Thermostats"]  # untouched
    assert client.get(url).json()["room_order"] == ["Kitchen", "Thermostats", "Lab"]


def test_layout_needs_membership(client, owner, make_home, make_user, login, csrf):
    stranger = make_user(make_home("Elsewhere"), role="admin")
    assert login(client, stranger).status_code == 200
    url = f"/api/v1/homes/{owner.home_id}/layout"
    assert client.get(url).status_code == 404
    r = client.put(url, json={"room_order": []}, headers=csrf(client))
    assert r.status_code == 404


def test_layout_rejects_bad_input(client, owner, login, csrf):
    assert login(client, owner).status_code == 200
    url = f"/api/v1/homes/{owner.home_id}/layout"
    for bad in ({"room_order": ["x" * 51]}, {"room_order": "Kitchen"}, {"rooms": []}):
        assert client.put(url, json=bad, headers=csrf(client)).status_code == 422
