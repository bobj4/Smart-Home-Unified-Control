# ruff: noqa: F811 (fixtures shared with test_frigate)
"""Guests kept to some cameras; Kasa power monitoring and the Energy
window; Hue rooms, scenes (as steps in Schedules and Scenes) and the
bridge's event stream."""

import json

from playwright.sync_api import expect

from app import features, hue_events, hue_home, kasa_home, probes
from app.integrations import hue, kasa
from app.models import Device
from tests import test_ui as _ui
from tests.test_frigate import frigate_fake, ready, secrets_key  # noqa: F401

FRONT, DRIVE = "1700000100.5-abc", "1700000000.1-def"


# ------------------------------------------------------------ cameras


def test_a_guest_sees_only_their_cameras(
    client, new_client, owner, make_user, login, csrf, frigate_fake, secrets_key
):
    ready(client, csrf, login, owner)
    guest = make_user(owner.home_id, role="guest")
    access = {
        "light_power": False,
        "light_settings": False,
        "cameras": True,
        "water_heater": False,
        "show_blocked": False,
        "thermostat_ids": [],
        "camera_names": ["front_door"],
    }
    url = f"/api/v1/homes/{owner.home_id}"
    r = client.put(
        f"{url}/members/{guest.id}/guest-access", json=access, headers=csrf(client)
    )
    assert r.status_code == 200 and r.json()["camera_names"] == ["front_door"]
    them = new_client()
    assert login(them, guest).status_code == 200
    assert them.get(f"{url}/cameras").json() == ["front_door"]
    assert [e["id"] for e in them.get(f"{url}/cameras/events").json()] == [FRONT]
    assert (
        them.get(f"{url}/cameras/events", params={"camera": "driveway"}).status_code
        == 403
    )
    assert them.get(f"{url}/cameras/events/{FRONT}/thumbnail").status_code == 200
    assert them.get(f"{url}/cameras/events/{DRIVE}/thumbnail").status_code == 404
    assert them.get(f"{url}/cameras/events/{DRIVE}/clip").status_code == 404
    # Every camera when none are ticked; bad names are refused.
    r = client.put(
        f"{url}/members/{guest.id}/guest-access",
        json={**access, "camera_names": []},
        headers=csrf(client),
    )
    assert them.get(f"{url}/cameras").json() == ["driveway", "front_door"]
    assert them.get(f"{url}/cameras/events/{DRIVE}/thumbnail").status_code == 200
    r = client.put(
        f"{url}/members/{guest.id}/guest-access",
        json={**access, "camera_names": ["../x"]},
        headers=csrf(client),
    )
    assert r.status_code == 422


# ------------------------------------------------------------ energy


def test_kasa_power_readings(monkeypatch):
    def request(host, body, login=None):
        if "system" in body:
            return {
                "system": {
                    "get_sysinfo": {
                        "model": "KP115",
                        "alias": "Kettle",
                        "relay_state": 1,
                        "feature": "TIM:ENE",
                    }
                }
            }
        emeter = body["emeter"]
        if "get_realtime" in emeter:
            return {"emeter": {"get_realtime": {"power_mw": 1534.2, "err_code": 0}}}
        import time

        return {
            "emeter": {
                "get_daystat": {
                    "day_list": [{"day": time.localtime().tm_mday, "energy_wh": 420}],
                    "err_code": 0,
                }
            }
        }

    monkeypatch.setattr(kasa, "request", request)
    kasa._today.clear()
    [plug] = kasa.devices("10.0.0.5")
    assert plug["energy"] is True
    assert kasa.energy("10.0.0.5") == {"power_w": 1.5, "today_kwh": 0.42}


def test_refresh_stores_power_and_the_energy_window(
    open_page, db, owner, monkeypatch, secrets_key
):
    features.set_integration(db, owner.home_id, kasa_home.INTEGRATION, True, None, None)
    plug = Device(
        home_id=owner.home_id,
        integration="kasa",
        external_id="10.0.0.6",
        type="plug",
        name="Kettle",
        room="Kitchen",
        capabilities=json.dumps({"host": "10.0.0.6", "energy": True}),
        state="{}",
        online=True,
    )
    db.add(plug)
    db.commit()
    probes._misses.pop("kasa:10.0.0.6", None)
    monkeypatch.setattr(
        kasa,
        "devices",
        lambda host, login=None: [
            {
                "id": host,
                "name": "Kettle",
                "kind": "plug",
                "model": "KP115",
                "on": True,
                "energy": True,
            }
        ],
    )
    monkeypatch.setattr(
        kasa,
        "energy",
        lambda host, login=None, child=None, is_smart=False: {
            "power_w": 1500.0,
            "today_kwh": 0.8,
        },
    )
    kasa_home.refresh(db, owner.home_id)
    db.expire_all()
    state = json.loads(db.get(Device, plug.id).state)
    assert (state["power_w"], state["today_kwh"]) == (1500.0, 0.8)
    page = open_page()
    _ui.ui_login(page, owner)
    button = page.get_by_test_id("energy-open")
    expect(button).to_have_text("⚡ 1500 W now")
    button.click()
    expect(page.get_by_test_id("energy-plug")).to_contain_text(
        "1500.0 W · 0.80 kWh today"
    )
    page.keyboard.press("Escape")
    expect(page.get_by_test_id("energy-overlay")).to_have_count(0)


# ------------------------------------------------------------ Hue


def test_hue_rooms_and_scenes(monkeypatch):
    groups = {
        "1": {"name": "Living room", "type": "Room", "lights": ["1", "2"]},
        "5": {"name": "Downstairs", "type": "Zone", "lights": ["1", "3"]},
    }
    scenes = {
        "AbC-12": {"name": "Relax", "type": "GroupScene", "group": "1"},
        "zz": {"name": "Old", "type": "LightScene"},
    }
    calls = []

    def call(method, url, body=None):
        calls.append((method, url, body))
        if url.endswith("/groups"):
            return groups
        if url.endswith("/scenes"):
            return scenes
        return [{"success": {}}]

    monkeypatch.setattr(hue, "_call", call)
    assert hue.rooms("h", "k") == {
        "1": "Living room",
        "2": "Living room",
        "3": "Downstairs",
    }
    assert hue.scenes("h", "k") == [
        {"id": "1/AbC-12", "name": "Relax", "room": "Living room"}
    ]
    hue.recall("h", "k", "1/AbC-12")
    assert calls[-1] == ("PUT", "http://h/api/k/groups/1/action", {"scene": "AbC-12"})


def test_hue_scene_steps(client, db, owner, login, csrf, monkeypatch, secrets_key):
    recalled = []
    monkeypatch.setattr(
        hue_home, "recall_scene", lambda db, home_id, scene: recalled.append(scene)
    )
    assert login(client, owner).status_code == 200
    base = f"/api/v1/homes/{owner.home_id}/automation/scenes"
    step = {"kind": "hue_scene", "id": "1/AbC-12", "command": "recall"}
    r = client.post(base, json={"name": "Relax", "steps": [step]}, headers=csrf(client))
    assert r.status_code == 422 and "Hue is turned off" in r.json()["detail"]
    features.set_integration(db, owner.home_id, "hue", True, None, None)
    bad = {**step, "id": "../x"}
    assert (
        client.post(
            base, json={"name": "X", "steps": [bad]}, headers=csrf(client)
        ).status_code
        == 422
    )
    scene = client.post(
        base, json={"name": "Relax", "steps": [step]}, headers=csrf(client)
    ).json()
    r = client.post(f"{base}/{scene['id']}/run", headers=csrf(client))
    assert r.json() == {"done": 1, "failed": []} and recalled == ["1/AbC-12"]


def test_hue_events_read_the_lights_again(monkeypatch):
    class Stream:
        status_code = 200

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def iter_lines(self):
            yield b": hi"
            yield b"id: 1"
            yield b'data: [{"type":"update"}]'
            hue_events._stop.set()  # end the test after one event
            yield b'data: [{"type":"update"}]'

    read = []
    monkeypatch.setattr(hue_events, "_bridges", lambda: {"home": ("10.0.0.2", "KEY")})
    monkeypatch.setattr(hue_events, "open_stream", lambda host, key: Stream())
    monkeypatch.setattr(hue_events, "changed", lambda home_id: read.append(home_id))
    hue_events._stop.clear()
    try:
        hue_events.follow("home", "10.0.0.2", "KEY")
    finally:
        hue_events._stop.clear()
    assert read == ["home"]


def test_ui_guest_camera_choices(
    open_page, client, db, owner, make_user, login, csrf, frigate_fake, secrets_key
):
    from app.models import GuestAccess

    ready(client, csrf, login, owner)
    guest = make_user(owner.home_id, role="guest")
    page = open_page()
    _ui.ui_login(page, owner, owner.totp.at(__import__("time").time() + 30))
    section = _ui.go_settings(page, "admin")
    row = section.get_by_test_id("member-row").filter(has_text=guest.email)
    row.get_by_test_id("guest-access-open").click()
    dialog = page.get_by_test_id("guest-access")
    expect(dialog.get_by_test_id("guest-camera-list")).to_be_hidden()
    dialog.get_by_test_id("guest-cameras").check()  # "See the cameras"
    expect(dialog.get_by_test_id("guest-camera-list")).to_be_visible()
    dialog.get_by_test_id("guest-camera").first.check()
    dialog.get_by_test_id("guest-access-save").click()
    expect(page.get_by_test_id("status")).to_contain_text("Saved what")
    db.expire_all()
    access = db.query(GuestAccess).filter_by(user_id=guest.id).one()
    assert json.loads(access.camera_names) == ["driveway"]


# ------------------------------------------------------------ ratgdo parking assist


def test_ratgdo_parking_assist(monkeypatch):
    from app.integrations import ratgdo

    answers = {
        "/switch/LASER": {"state": "OFF"},
        "/binary_sensor/Vehicle%20detected": {"state": "ON"},
        "/sensor/Vehicle%20distance%20actual%20filtered": {"value": 1234.6},
        "/number/Vehicle%20distance%20target": {"value": 600},
    }
    calls = []

    class Answer:
        def __init__(self, status, data=None):
            self.status_code, self._data = status, data

        def json(self):
            return self._data

    def request(method, url, timeout):
        path = url.split("10.0.0.9", 1)[1]
        calls.append((method, path))
        base = path.split("/set?")[0] if "/set?" in path else path
        base = (
            base.rsplit("/", 1)[0] if method == "POST" and "/set?" not in path else base
        )
        return Answer(200, answers[base]) if base in answers else Answer(404)

    ratgdo._extra_path.clear()
    monkeypatch.setattr(ratgdo.requests, "request", request)
    extras = ratgdo.extras("10.0.0.9")
    assert (extras["laser"], extras["vehicle"]) == (False, True)
    assert ratgdo.measures("10.0.0.9") == {
        "vehicle_distance_mm": 1235,
        "parking_target_mm": 600,
    }
    ratgdo.act("10.0.0.9", "laser_on")
    assert calls[-1] == ("POST", "/switch/LASER/turn_on")
    ratgdo.act("10.0.0.9", "set_parking_target", {"mm": 750})
    assert calls[-1] == ("POST", "/number/Vehicle%20distance%20target/set?value=750")


def test_ui_parking_controls(open_page, db, owner, make_device):
    door = db.get(
        Device, make_device(owner.home_id, device_type="garage_door", name="Garage")
    )
    door.state = json.dumps(
        {
            "door": "closed",
            "laser": False,
            "vehicle": True,
            "vehicle_distance_mm": 1230,
            "parking_target_mm": 600,
        }
    )
    db.commit()
    page = open_page()
    _ui.ui_login(page, owner)
    card = _ui.card(page, "Garage")
    expect(card.get_by_test_id("garage-vehicle")).to_have_text("Car in · 123 cm away")
    card.get_by_test_id("garage-laser").click()
    expect(_ui.card(page, "Garage").get_by_test_id("garage-laser")).to_have_text(
        "Parking laser on"
    )
    card = _ui.card(page, "Garage")
    card.get_by_test_id("garage-parking-target").fill("75")
    with page.expect_response(lambda r: r.url.endswith("/command") and r.ok):
        card.get_by_test_id("garage-parking-set").click()
    expect(
        _ui.card(page, "Garage").get_by_test_id("garage-parking-target")
    ).to_have_value("75")
    db.expire_all()
    assert json.loads(db.get(Device, door.id).state)["parking_target_mm"] == 750
