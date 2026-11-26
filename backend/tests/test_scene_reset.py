"""A scene's Reset puts back what its last run changed (just what its steps
change, only where it still differs), then is gone until it runs again;
color samples beside a scene step's color."""

import json
from datetime import timedelta

from playwright.sync_api import expect

from app import scene_reset
from app.models import Device, Scene
from tests import test_ui as _ui
from tests.test_schedules_scenes import base, state, step


def put_state(db, device_id, **values):
    device = db.get(Device, device_id)
    device.state = json.dumps({**json.loads(device.state or "{}"), **values})
    db.commit()


def scene(client, csrf, home_id, steps, name="Movie night"):
    r = client.post(
        base(home_id, "/scenes"),
        json={"name": name, "steps": steps},
        headers=csrf(client),
    )
    assert r.status_code == 201, r.text
    return r.json()


def test_reset_puts_back_what_the_scene_changed(
    client, db, owner, login, csrf, make_device
):
    lamp = make_device(owner.home_id, name="Lamp")
    strip = make_device(owner.home_id, name="Strip")
    kettle = make_device(owner.home_id, device_type="plug", name="Kettle")
    put_state(db, lamp, on=True, brightness=80, color_mode="temp", color_temp=3000)
    put_state(db, strip, on=False, brightness=60, color_mode="rgb", color="#00ff00")
    put_state(db, kettle, on=True)
    assert login(client, owner).status_code == 200
    made = scene(
        client,
        csrf,
        owner.home_id,
        [
            step(lamp, "set_brightness", brightness=20),
            step(strip, "set_color", color="#ff0000"),
            step(kettle, "turn_off"),
        ],
    )
    assert made["can_reset"] is False
    reset = base(owner.home_id, f"/scenes/{made['id']}/reset")
    assert client.post(reset, headers=csrf(client)).status_code == 409
    client.post(base(owner.home_id, f"/scenes/{made['id']}/run"), headers=csrf(client))
    assert state(db, strip)["on"] is True and state(db, kettle)["on"] is False
    listed = client.get(base(owner.home_id)).json()["scenes"][0]
    assert listed["can_reset"] is True
    # The lamp's color was not the scene's: changing it by hand stays.
    put_state(db, lamp, color_temp=4000)
    r = client.post(reset, headers=csrf(client))
    assert r.status_code == 200, r.text
    # Lamp: brightness. Strip: green again, then off. Kettle: on.
    assert r.json() == {"done": 4, "failed": []}
    lamp_now, strip_now = state(db, lamp), state(db, strip)
    assert lamp_now["brightness"] == 80 and lamp_now["color_temp"] == 4000
    assert strip_now["color"] == "#00ff00" and strip_now["on"] is False
    assert state(db, kettle)["on"] is True
    assert client.get(base(owner.home_id)).json()["scenes"][0]["can_reset"] is False
    assert client.post(reset, headers=csrf(client)).status_code == 409


def test_running_again_keeps_the_first_before(
    client, db, owner, login, csrf, make_device
):
    lamp = make_device(owner.home_id)
    put_state(db, lamp, on=True, brightness=90)
    assert login(client, owner).status_code == 200
    made = scene(
        client, csrf, owner.home_id, [step(lamp, "set_brightness", brightness=10)]
    )
    run = base(owner.home_id, f"/scenes/{made['id']}/run")
    client.post(run, headers=csrf(client))
    client.post(run, headers=csrf(client))
    client.post(
        base(owner.home_id, f"/scenes/{made['id']}/reset"), headers=csrf(client)
    )
    assert state(db, lamp)["brightness"] == 90
    # Much later, a run notes afresh.
    client.post(run, headers=csrf(client))
    row = db.get(Scene, made["id"])
    db.refresh(row)
    row.ran_at = row.ran_at - scene_reset.KEEP_FOR - timedelta(minutes=1)
    db.commit()
    put_state(db, lamp, brightness=50)
    client.post(run, headers=csrf(client))
    client.post(
        base(owner.home_id, f"/scenes/{made['id']}/reset"), headers=csrf(client)
    )
    assert state(db, lamp)["brightness"] == 50


def test_group_steps_and_nothing_to_do(client, db, owner, login, csrf, make_device):
    a = make_device(owner.home_id, name="A")
    b = make_device(owner.home_id, name="B")
    assert login(client, owner).status_code == 200
    group = client.post(
        f"/api/v1/homes/{owner.home_id}/groups",
        json={"name": "Den", "device_ids": [a, b]},
        headers=csrf(client),
    ).json()
    made = scene(
        client,
        csrf,
        owner.home_id,
        [{"kind": "group", "id": group["id"], "command": "turn_on", "payload": {}}],
    )
    client.post(base(owner.home_id, f"/scenes/{made['id']}/run"), headers=csrf(client))
    assert state(db, a)["on"] is True and state(db, b)["on"] is True
    put_state(db, b, on=False)  # already back
    r = client.post(
        base(owner.home_id, f"/scenes/{made['id']}/reset"), headers=csrf(client)
    )
    assert r.json() == {"done": 1, "failed": []}
    assert state(db, a)["on"] is False


def test_commands_back_for_each_kind():
    back = scene_reset.commands_back
    # Thermostat: mode first, then its set point; Auto raises cooling first.
    assert back(
        "thermostat",
        {"mode": "heat", "heat_setpoint": 68, "fan": "auto"},
        {"mode": "cool", "heat_setpoint": 68, "fan": "on"},
        {"mode", "setpoints", "fan"},
    ) == [("set_mode", {"mode": "heat"}), ("set_fan", {"fan": "auto"})]
    assert back(
        "thermostat",
        {"mode": "auto", "heat_setpoint": 74, "cool_setpoint": 78},
        {"mode": "auto", "heat_setpoint": 66, "cool_setpoint": 72},
        {"setpoints"},
    ) == [
        ("set_cool_temperature", {"temperature": 78}),
        ("set_temperature", {"temperature": 74}),
    ]
    assert back(
        "thermostat",
        {"mode": "cool", "cool_setpoint": 75},
        {"mode": "cool", "cool_setpoint": 70},
        {"setpoints"},
    ) == [("set_temperature", {"temperature": 75})]
    # Water heater, garage door, TV.
    assert back(
        "water_heater",
        {
            "enabled": True,
            "mode": "heat_pump",
            "target_temperature": 120,
            "away": False,
        },
        {"enabled": False, "mode": None, "target_temperature": 110, "away": True},
        {"mode", "target", "away"},
    ) == [
        ("set_mode", {"mode": "heat_pump"}),
        ("set_temperature", {"temperature": 120}),
        ("set_away", {"away": False}),
    ]
    assert back(
        "garage_door",
        {"door": "closed", "light": False, "locked": True},
        {"door": "open", "light": True, "locked": False},
        {"door", "light", "locked"},
    ) == [("close", {}), ("light_off", {}), ("lock", {})]
    assert back("garage_door", {"door": "opening"}, {"door": "closed"}, {"door"}) == []
    assert back("tv", {"on": False}, {"on": True}, {"power"}) == [("turn_off", {})]
    # A light off then and now: nothing, whatever its color.
    assert (
        back(
            "light",
            {"on": False, "color_mode": "rgb", "color": "#00ff00"},
            {"on": False, "color_mode": "rgb", "color": "#ff0000"},
            {"color", "power"},
        )
        == []
    )


def test_ui_reset_and_color_samples(open_page, db, owner, make_device):
    lamp = make_device(owner.home_id, name="Porch light")
    put_state(db, lamp, on=True, brightness=100, color_mode="temp", color_temp=2700)
    page = open_page()
    _ui.ui_login(page, owner)
    page.get_by_test_id("nav-schedules").click()
    page.get_by_test_id("scene-new").click()
    editor = page.get_by_test_id("scene-editor")
    editor.get_by_test_id("scene-name").fill("Party")
    editor.get_by_test_id("step-command").select_option("set_color")
    swatches = editor.get_by_test_id("step-swatch")
    expect(swatches).to_have_count(12)
    blue = editor.get_by_role("button", name="Blue")
    blue.click()
    expect(blue).to_have_attribute("aria-pressed", "true")
    expect(editor.locator('input[type="color"]')).to_have_value("#2962ff")
    editor.get_by_test_id("scene-editor-save").click()
    card = page.get_by_test_id("scene-card")
    expect(card.get_by_test_id("scene-reset")).to_have_count(0)
    card.get_by_test_id("scene-run").click()
    expect(page.get_by_test_id("status")).to_contain_text("Party ran (1 done)")
    db.expire_all()
    assert json.loads(db.get(Device, lamp).state)["color"] == "#2962ff"
    card.get_by_test_id("scene-reset").click()
    expect(page.get_by_test_id("status")).to_contain_text(
        "Party: put back as before (1 change)"
    )
    expect(card.get_by_test_id("scene-reset")).to_have_count(0)
    db.expire_all()
    now = json.loads(db.get(Device, lamp).state)
    assert now["color_mode"] == "temp" and now["color_temp"] == 2700
    # Opening the scene again shows its sample chosen.
    page.get_by_test_id("scene-edit").click()
    expect(
        page.get_by_test_id("scene-editor").get_by_role("button", name="Blue")
    ).to_have_attribute("aria-pressed", "true")


def test_reset_leaves_what_someone_changed_since(
    client, db, owner, login, csrf, make_device
):
    lamp = make_device(owner.home_id, name="Lamp")
    fan = make_device(owner.home_id, device_type="plug", name="Fan")
    put_state(db, lamp, on=True, brightness=90)
    put_state(db, fan, on=False)
    assert login(client, owner).status_code == 200
    made = scene(
        client,
        csrf,
        owner.home_id,
        [step(lamp, "set_brightness", brightness=20), step(fan, "turn_on")],
    )
    client.post(base(owner.home_id, f"/scenes/{made['id']}/run"), headers=csrf(client))
    put_state(db, lamp, brightness=55)  # dimmed by hand afterwards
    r = client.post(
        base(owner.home_id, f"/scenes/{made['id']}/reset"), headers=csrf(client)
    )
    assert r.json() == {"done": 1, "failed": []}
    assert state(db, lamp)["brightness"] == 55  # left as they set it
    assert state(db, fan)["on"] is False  # the scene's own change: put back


def test_hue_scene_resets_only_its_own_lights(
    client, db, owner, login, csrf, make_device, monkeypatch
):
    from app import features, hue_home

    features.set_integration(db, owner.home_id, "hue", True, None, None)
    desk = make_device(owner.home_id, name="Desk")
    hall = make_device(owner.home_id, name="Hall")
    other = make_device(owner.home_id, name="Porch")
    for device_id in (desk, hall, other):
        put_state(db, device_id, on=False, brightness=40)
    sets = {desk: {"on": True, "brightness": 80}, hall: {"on": True, "brightness": 30}}

    def recall(db_, home_id, ref):  # the bridge shows the scene
        for device_id, values in sets.items():
            put_state(db_, device_id, **values)

    monkeypatch.setattr(hue_home, "scene_states", lambda db_, home_id, ref: sets)
    monkeypatch.setattr(hue_home, "recall_scene", recall)
    assert login(client, owner).status_code == 200
    made = scene(
        client,
        csrf,
        owner.home_id,
        [{"kind": "hue_scene", "id": "3/AbC-123", "command": "recall", "payload": {}}],
    )
    client.post(base(owner.home_id, f"/scenes/{made['id']}/run"), headers=csrf(client))
    put_state(db, other, on=True)  # not in the scene: turned on by hand
    put_state(db, hall, brightness=70)  # in it, but dimmed by hand since
    r = client.post(
        base(owner.home_id, f"/scenes/{made['id']}/reset"), headers=csrf(client)
    )
    assert r.status_code == 200, r.text
    assert state(db, desk) == {**state(db, desk), "on": False}
    assert state(db, desk)["brightness"] == 40
    assert state(db, hall)["on"] is False and state(db, hall)["brightness"] == 70
    assert state(db, other)["on"] is True
