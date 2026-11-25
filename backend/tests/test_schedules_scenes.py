"""Schedules and Scenes: scenes run device and group commands together;
schedules run them at a time, or at sunrise or sunset with an offset, on
chosen days in the home's time zone. Admins choose who may edit, the
home's time zone and location, and can pause every schedule."""

import json
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

from app import automation, federation, sun
from app.models import AuditEvent, Device, Schedule

NY = "America/New_York"


def base(home_id, path=""):
    return f"/api/v1/homes/{home_id}/automation{path}"


def state(db, device_id):
    db.expire_all()
    return json.loads(db.get(Device, device_id).state or "{}")


def step(device_id, command, **payload):
    return {"kind": "device", "id": device_id, "command": command, "payload": payload}


def test_sunrise_and_sunset_for_new_york():
    tz = ZoneInfo(NY)
    rise, sets = sun.times(date(2026, 6, 21), 40.7128, -74.006)
    assert rise.astimezone(tz).strftime("%H:%M") in ("05:24", "05:25", "05:26")
    assert sets.astimezone(tz).strftime("%H:%M") in ("20:30", "20:31", "20:32")
    assert sun.times(date(2026, 12, 21), 78.2, 15.6) == (None, None)  # polar night


def test_scene_made_checked_and_run(client, db, owner, login, csrf, make_device):
    lamp = make_device(owner.home_id, name="Lamp")
    kettle = make_device(owner.home_id, device_type="plug", name="Kettle")
    assert login(client, owner).status_code == 200
    body = {
        "name": "Movie night",
        "steps": [
            step(lamp, "set_brightness", brightness=20),
            step(kettle, "turn_off"),
        ],
    }
    r = client.post(base(owner.home_id, "/scenes"), json=body, headers=csrf(client))
    assert r.status_code == 201, r.text
    scene = r.json()
    # A step that does not fit is refused, saying which.
    bad = {"name": "Bad", "steps": [step(kettle, "set_brightness", brightness=5)]}
    r = client.post(base(owner.home_id, "/scenes"), json=bad, headers=csrf(client))
    assert r.status_code == 422 and "step 1 (Kettle)" in r.json()["detail"]
    r = client.post(
        base(owner.home_id, f"/scenes/{scene['id']}/run"), headers=csrf(client)
    )
    assert r.status_code == 200 and r.json() == {"done": 2, "failed": []}
    assert state(db, lamp)["brightness"] == 20 and state(db, kettle)["on"] is False
    assert db.query(AuditEvent).filter_by(event_type="automation_run").count() == 1


def test_steps_see_the_state_earlier_steps_leave(
    client, owner, login, csrf, make_device
):
    lamp = make_device(owner.home_id, name="Lamp")
    assert login(client, owner).status_code == 200
    body = {
        "name": "Warm",
        "steps": [step(lamp, "turn_off"), step(lamp, "set_color_temp", kelvin=2700)],
    }
    r = client.post(base(owner.home_id, "/scenes"), json=body, headers=csrf(client))
    assert r.status_code == 201, r.text


def test_group_step(client, db, owner, login, csrf, make_device):
    a = make_device(owner.home_id, name="A")
    b = make_device(owner.home_id, name="B")
    assert login(client, owner).status_code == 200
    group = client.post(
        f"/api/v1/homes/{owner.home_id}/groups",
        json={"name": "Hall", "device_ids": [a, b]},
        headers=csrf(client),
    ).json()
    body = {
        "name": "Hall on",
        "steps": [{"kind": "group", "id": group["id"], "command": "turn_on"}],
    }
    scene = client.post(
        base(owner.home_id, "/scenes"), json=body, headers=csrf(client)
    ).json()
    r = client.post(
        base(owner.home_id, f"/scenes/{scene['id']}/run"), headers=csrf(client)
    )
    assert r.json()["done"] == 2 and state(db, a)["on"] and state(db, b)["on"]


def test_who_may_edit(client, new_client, owner, make_user, login, csrf, make_device):
    lamp = make_device(owner.home_id)
    member = make_user(owner.home_id, role="member")
    other = new_client()
    assert login(other, member).status_code == 200
    body = {"name": "S", "steps": [step(lamp, "turn_on")]}
    assert other.get(base(owner.home_id)).json()["can_edit"] is False
    r = other.post(base(owner.home_id, "/scenes"), json=body, headers=csrf(other))
    assert r.status_code == 403
    assert login(client, owner).status_code == 200
    r = client.put(
        base(owner.home_id, "/settings"),
        json={"editors": "member"},
        headers=csrf(client),
    )
    assert r.status_code == 200
    assert other.get(base(owner.home_id)).json()["can_edit"] is True
    r = other.post(base(owner.home_id, "/scenes"), json=body, headers=csrf(other))
    assert r.status_code == 201
    # Settings are for admins.
    r = other.put(
        base(owner.home_id, "/settings"), json={"paused": True}, headers=csrf(other)
    )
    assert r.status_code == 403


def make_schedule(client, csrf, home_id, trigger, days=(0, 1, 2, 3, 4, 5, 6), **more):
    body = {"name": "Porch", "trigger": trigger, "days": list(days), **more}
    return client.post(base(home_id, "/schedules"), json=body, headers=csrf(client))


def test_time_schedule_in_the_homes_time_zone(
    client, db, owner, login, csrf, make_device
):
    lamp = make_device(owner.home_id)
    assert login(client, owner).status_code == 200
    client.put(
        base(owner.home_id, "/settings"), json={"time_zone": NY}, headers=csrf(client)
    )
    r = make_schedule(
        client,
        csrf,
        owner.home_id,
        {"kind": "time", "at": "19:30"},
        steps=[step(lamp, "turn_on")],
    )
    assert r.status_code == 201, r.text
    out = r.json()
    when = datetime.fromisoformat(out["next_run_at"])
    assert (when.hour, when.minute) == (19, 30) and when.utcoffset() in (
        timedelta(hours=-4),
        timedelta(hours=-5),
    )
    # Its next run is the first 19:30 New York time after now.
    row = automation.settings_for(db, owner.home_id)
    schedule = db.get(Schedule, out["id"])
    after = datetime(2026, 11, 14, 23, 0, tzinfo=UTC)  # 18:00 in New York
    assert automation.next_run(schedule, row, after) == datetime(
        2026, 11, 15, 0, 30, tzinfo=UTC
    )
    # Days: only Mondays.
    schedule.days = "[0]"
    assert (
        automation.next_run(schedule, row, after).astimezone(ZoneInfo(NY)).weekday()
        == 0
    )
    bad = make_schedule(
        client,
        csrf,
        owner.home_id,
        {"kind": "time", "at": "7:30"},
        steps=[step(lamp, "turn_on")],
    )
    assert bad.status_code == 422
    none = make_schedule(client, csrf, owner.home_id, {"kind": "time", "at": "07:30"})
    assert none.status_code == 422  # no scene and no step


def test_sunset_needs_the_location_then_follows_the_sun(
    client, db, owner, login, csrf, make_device
):
    lamp = make_device(owner.home_id)
    assert login(client, owner).status_code == 200
    r = make_schedule(
        client,
        csrf,
        owner.home_id,
        {"kind": "sunset", "offset": -15},
        steps=[step(lamp, "turn_on")],
    )
    assert r.status_code == 201
    assert r.json()["next_run_at"] is None and "location" in r.json()["waiting"]
    r = client.put(
        base(owner.home_id, "/settings"),
        json={"time_zone": NY, "latitude": 40.7128, "longitude": -74.006},
        headers=csrf(client),
    )
    assert r.status_code == 200
    (listed,) = client.get(base(owner.home_id)).json()["schedules"]
    when = datetime.fromisoformat(listed["next_run_at"])
    rise, sets = sun.times(when.date(), 40.7128, -74.006)
    assert abs(when - (sets - timedelta(minutes=15))) < timedelta(seconds=1)
    r = client.put(
        base(owner.home_id, "/settings"), json={"latitude": 40.0}, headers=csrf(client)
    )
    assert r.status_code == 200  # still both
    r = client.put(
        base(owner.home_id, "/settings"),
        json={"latitude": None, "longitude": 5.0},
        headers=csrf(client),
    )
    assert r.status_code == 422
    r = client.put(
        base(owner.home_id, "/settings"),
        json={"time_zone": "Mars/Base"},
        headers=csrf(client),
    )
    assert r.status_code == 422


def test_due_schedules_run_and_missed_or_paused_ones_do_not(
    client, db, owner, login, csrf, make_device
):
    lamp = make_device(owner.home_id)
    assert login(client, owner).status_code == 200
    out = make_schedule(
        client,
        csrf,
        owner.home_id,
        {"kind": "time", "at": "06:00"},
        steps=[step(lamp, "turn_on")],
    ).json()
    schedule = db.get(Schedule, out["id"])
    planned = (
        schedule.next_run_at.replace(tzinfo=UTC)
        if schedule.next_run_at.tzinfo is None
        else schedule.next_run_at
    )
    assert automation.run_due(db, planned - timedelta(seconds=1)) == 0
    assert automation.run_due(db, planned + timedelta(seconds=5)) == 1
    db.expire_all()
    schedule = db.get(Schedule, out["id"])
    assert state(db, lamp)["on"] is True and schedule.last_result.startswith("Done")
    nxt = (
        schedule.next_run_at
        if schedule.next_run_at.tzinfo
        else schedule.next_run_at.replace(tzinfo=UTC)
    )
    assert nxt - planned == timedelta(days=1)  # tomorrow, not again now
    # Missed by more than the grace: skipped, not run late.
    assert automation.run_due(db, nxt + timedelta(hours=1)) == 0
    db.expire_all()
    assert db.get(Schedule, out["id"]).last_result.startswith("Missed")
    # Paused: skipped.
    client.put(
        base(owner.home_id, "/settings"), json={"paused": True}, headers=csrf(client)
    )
    db.expire_all()
    schedule = db.get(Schedule, out["id"])
    due = (
        schedule.next_run_at
        if schedule.next_run_at.tzinfo
        else schedule.next_run_at.replace(tzinfo=UTC)
    )
    assert automation.run_due(db, due + timedelta(seconds=1)) == 0
    db.expire_all()
    assert "paused" in db.get(Schedule, out["id"]).last_result


def test_a_schedule_runs_a_scene_and_run_now(
    client, db, owner, login, csrf, make_device
):
    lamp = make_device(owner.home_id)
    plug = make_device(owner.home_id, device_type="plug", name="Fan")
    assert login(client, owner).status_code == 200
    scene = client.post(
        base(owner.home_id, "/scenes"),
        json={"name": "Fan on", "steps": [step(plug, "turn_on")]},
        headers=csrf(client),
    ).json()
    out = make_schedule(
        client,
        csrf,
        owner.home_id,
        {"kind": "sunrise", "offset": 30},
        scene_id=scene["id"],
        steps=[step(lamp, "turn_off")],
    ).json()
    r = client.post(
        base(owner.home_id, f"/schedules/{out['id']}/run"), headers=csrf(client)
    )
    assert r.json() == {"done": 2, "failed": []}
    assert state(db, plug)["on"] is True and state(db, lamp)["on"] is False


def test_a_failing_step_does_not_stop_the_others(
    client, db, owner, login, csrf, make_device
):
    lamp = make_device(owner.home_id, name="Lamp")
    gone = make_device(owner.home_id, name="Gone")
    assert login(client, owner).status_code == 200
    scene = client.post(
        base(owner.home_id, "/scenes"),
        json={"name": "Both", "steps": [step(gone, "turn_on"), step(lamp, "turn_on")]},
        headers=csrf(client),
    ).json()
    db.delete(db.get(Device, gone))
    db.commit()
    r = client.post(
        base(owner.home_id, f"/scenes/{scene['id']}/run"), headers=csrf(client)
    )
    assert r.json()["done"] == 1 and r.json()["failed"][0]["reason"] == "no longer here"
    assert automation.summary(r.json()).startswith("1 done; a removed device")


def test_guests_run_scenes_only_when_allowed(
    client, new_client, owner, make_user, login, csrf, make_device
):
    lamp = make_device(owner.home_id)
    guest = make_user(owner.home_id, role="guest")
    assert login(client, owner).status_code == 200
    scene = client.post(
        base(owner.home_id, "/scenes"),
        json={"name": "Lamp on", "steps": [step(lamp, "turn_on")]},
        headers=csrf(client),
    ).json()
    them = new_client()
    assert login(them, guest).status_code == 200
    guest_base = f"/api/v1/homes/{owner.home_id}/guest/scenes"
    assert them.get(guest_base).status_code == 403
    assert them.get(base(owner.home_id)).status_code in (403, 404)
    access = {
        "light_power": False,
        "light_settings": False,
        "cameras": False,
        "water_heater": False,
        "show_blocked": False,
        "scenes": True,
        "thermostat_ids": [],
    }
    r = client.put(
        f"/api/v1/homes/{owner.home_id}/members/{guest.id}/guest-access",
        json=access,
        headers=csrf(client),
    )
    assert r.status_code == 200, r.text
    listed = [{"id": scene["id"], "name": "Lamp on", "can_reset": False}]
    assert them.get(guest_base).json() == listed
    r = them.post(f"{guest_base}/{scene['id']}/run", headers=csrf(them))
    assert r.json() == {"done": 1, "failed": 0}
    # They can put it back too.
    assert them.get(guest_base).json()[0]["can_reset"] is True
    r = them.post(f"{guest_base}/{scene['id']}/reset", headers=csrf(them))
    assert r.json() == {"done": 1, "failed": 0}


def test_scenes_of_a_home_at_another_site_run_there():
    assert "automation" in federation.FORWARDED


# ------------------------------------------------- location from the address


def test_census_then_nominatim_rounded(monkeypatch):
    from app import geocode

    asked = []

    def get(url, params):
        asked.append(url)
        if "census" in url:
            return {"result": {"addressMatches": []}}
        return [{"lat": "40.712776", "lon": "-74.005974"}]

    monkeypatch.setattr(geocode, "get", get)
    assert geocode.locate("1 Main St, New York") == (40.713, -74.006)
    assert asked == [geocode.CENSUS, geocode.NOMINATIM]

    def down(url, params):
        raise geocode.requests.ConnectionError("offline")

    monkeypatch.setattr(geocode, "get", down)
    assert geocode.locate("1 Main St") is None


def test_the_location_follows_the_address(client, db, owner, login, csrf, monkeypatch):
    from app import geocode

    found = {"x": -74.006, "y": 40.7128}

    def get(url, params):
        if "census" not in url:
            return []
        return {
            "result": {
                "addressMatches": [{"coordinates": dict(found)}] if found else []
            }
        }

    monkeypatch.setattr(geocode, "get", get)
    assert login(client, owner).status_code == 200
    settings = base(owner.home_id, "/settings")

    def shown():
        return client.get(base(owner.home_id)).json()["settings"]

    r = client.post(f"{settings}/locate", headers=csrf(client))
    assert r.status_code == 422  # no address yet
    home = f"/api/v1/homes/{owner.home_id}"
    r = client.patch(home, json={"address": "1 Main St"}, headers=csrf(client))
    assert r.status_code == 200, r.text
    s = shown()
    assert (s["latitude"], s["longitude"], s["location_source"]) == (
        40.713,
        -74.006,
        "address",
    )
    assert s["sun_today"] is not None
    found.update(x=-71.06, y=42.36)
    client.patch(home, json={"address": "2 Elm St"}, headers=csrf(client))
    assert shown()["latitude"] == 42.36  # followed
    # Typed in: a new address leaves it alone, until asked.
    client.put(
        settings, json={"latitude": 30.0, "longitude": -90.0}, headers=csrf(client)
    )
    assert shown()["location_source"] == "manual"
    client.patch(home, json={"address": "3 Oak St"}, headers=csrf(client))
    assert shown()["latitude"] == 30.0
    r = client.post(f"{settings}/locate", headers=csrf(client))
    assert r.status_code == 200 and r.json()["latitude"] == 42.36
    found.clear()
    r = client.post(f"{settings}/locate", headers=csrf(client))
    assert r.status_code == 502 and "found" in r.json()["detail"]
