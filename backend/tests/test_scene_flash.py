"""A scene step that flashes lights: how many times, how long a flash
lasts and how long between, after the scene's other steps, in the
background; each light ends on or off as it was. (The flashing itself is
run here without waiting.)"""

import json

import pytest
from playwright.sync_api import expect

from app import flash
from app.models import Device
from tests import test_ui as _ui
from tests.test_scene_reset import put_state, scene
from tests.test_schedules_scenes import base, state

FLASH = {"times": 2, "on_seconds": 1.5, "off_seconds": 0.5}


@pytest.fixture
def flashes(monkeypatch):
    """Flashing runs at once, in the test (no thread, no waiting), with the
    switching it did and the pauses it took."""
    seen = {"pauses": [], "switches": []}
    real_switch = flash._switch

    def switch(db, device, on):
        seen["switches"].append((device.name, on))
        return real_switch(db, device, on)

    def now(home_id, ids, payload, user_id):
        flash._flash(home_id, ids, payload, user_id, sleep=seen["pauses"].append)

    class Inline:
        def __init__(self, target, args, daemon):
            self.target, self.args = target, args

        def start(self):
            now(*self.args)

    monkeypatch.setattr(flash, "_switch", switch)
    monkeypatch.setattr(flash.threading, "Thread", Inline)
    flash._busy.clear()
    return seen


def test_flash_step_checks():
    assert flash.check({"times": 3, "on_seconds": 1, "off_seconds": 2.25}) == {
        "times": 3,
        "on_seconds": 1.0,
        "off_seconds": 2.2,
    }
    for bad in (
        {"times": 0, "on_seconds": 1, "off_seconds": 1},
        {"times": 21, "on_seconds": 1, "off_seconds": 1},
        {"times": 2, "on_seconds": 0.1, "off_seconds": 1},
        {"times": 2, "on_seconds": 1, "off_seconds": 11},
        {"times": True, "on_seconds": 1, "off_seconds": 1},
        {"times": 20, "on_seconds": 10, "off_seconds": 10},  # 400 s in all
        {"times": 2, "on_seconds": 1},
    ):
        with pytest.raises(flash.FlashError):
            flash.check(bad)


def test_scene_flashes_after_its_other_steps(
    client, db, owner, login, csrf, make_device, flashes
):
    lamp = make_device(owner.home_id, name="Lamp")
    porch = make_device(owner.home_id, name="Porch")
    kettle = make_device(owner.home_id, device_type="plug", name="Kettle")
    put_state(db, lamp, on=True, brightness=80)
    put_state(db, porch, on=False)
    assert login(client, owner).status_code == 200
    too_many = {"times": 99, "on_seconds": 1, "off_seconds": 1}
    r = client.post(
        base(owner.home_id, "/scenes"),
        json={
            "name": "Bad",
            "steps": [
                {"kind": "device", "id": lamp, "command": "flash", "payload": too_many}
            ],
        },
        headers=csrf(client),
    )
    assert r.status_code == 422 and "times must be" in r.text
    r = client.post(
        base(owner.home_id, "/scenes"),
        json={
            "name": "Plug flash",
            "steps": [
                {"kind": "device", "id": kettle, "command": "flash", "payload": FLASH}
            ],
        },
        headers=csrf(client),
    )
    assert r.status_code == 422 and "only lights flash" in r.text
    made = scene(
        client,
        csrf,
        owner.home_id,
        [
            {"kind": "device", "id": lamp, "command": "flash", "payload": FLASH},
            {"kind": "device", "id": porch, "command": "flash", "payload": FLASH},
            {
                "kind": "device",
                "id": lamp,
                "command": "set_brightness",
                "payload": {"brightness": 30},
            },
        ],
    )
    r = client.post(
        base(owner.home_id, f"/scenes/{made['id']}/run"), headers=csrf(client)
    )
    assert r.json()["failed"] == []
    # The brightness came first; the lamp (on) went off first, then two flashes.
    assert state(db, lamp)["brightness"] == 30
    lamp_switches = [on for name, on in flashes["switches"] if name == "Lamp"]
    assert lamp_switches == [False, True, False, True, False, True]
    porch_switches = [on for name, on in flashes["switches"] if name == "Porch"]
    assert porch_switches == [True, False, True, False]
    assert flashes["pauses"] == [0.5, 1.5, 0.5, 1.5]
    # Back as they were: the lamp on, the porch off.
    assert state(db, lamp)["on"] is True and state(db, porch)["on"] is False
    assert flash._busy == set()


def test_a_light_already_flashing_is_left_to_finish(monkeypatch):
    started = []
    flash._busy.clear()
    flash._busy.add("a")

    class Noted:
        def __init__(self, target, args, daemon):
            self.args = args

        def start(self):
            started.append(self.args)

    monkeypatch.setattr(flash.threading, "Thread", Noted)
    assert flash.start("h", ["a", "b", "b"], FLASH, None) == ["b"]
    assert started[0][1] == ["b"]
    flash._busy.clear()


def test_group_flash(client, db, owner, login, csrf, make_device, flashes):
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
        [{"kind": "group", "id": group["id"], "command": "flash", "payload": FLASH}],
    )
    r = client.post(
        base(owner.home_id, f"/scenes/{made['id']}/run"), headers=csrf(client)
    )
    assert (r.json()["done"], r.json()["failed"]) == (2, [])
    assert sorted({name for name, _ in flashes["switches"]}) == ["A", "B"]


def test_ui_flash_step(open_page, db, owner, make_device):
    make_device(owner.home_id, name="Porch light")
    page = open_page()
    _ui.ui_login(page, owner)
    page.get_by_test_id("nav-schedules").click()
    page.get_by_test_id("scene-new").click()
    editor = page.get_by_test_id("scene-editor")
    editor.get_by_test_id("scene-name").fill("Alarm")
    editor.get_by_test_id("step-command").select_option("flash")
    expect(editor.get_by_test_id("step-flash-times")).to_have_value("3")
    editor.get_by_test_id("step-flash-times").fill("5")
    editor.get_by_test_id("step-flash-on_seconds").fill("2")
    editor.get_by_test_id("step-flash-off_seconds").fill("0.5")
    editor.get_by_test_id("scene-editor-save").click()
    expect(page.get_by_test_id("scene-card")).to_contain_text("Alarm")
    db.expire_all()
    from app.models import Scene

    saved = json.loads(db.query(Scene).one().steps)
    assert saved[0]["command"] == "flash"
    assert saved[0]["payload"] == {"times": 5, "on_seconds": 2.0, "off_seconds": 0.5}
    assert db.query(Device).count() == 1
