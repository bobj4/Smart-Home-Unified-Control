"""Device groups: made here or imported from Cync, controlled together, and
live Cync state. Written by the reviewer (groups phase). Do not edit, skip,
mark or delete these tests. If one looks wrong, stop and report the test name
and its full failure output instead of changing it.
"""

import asyncio
import concurrent.futures
import json

from playwright.sync_api import expect

from app import cync_live
from app.integrations import cync
from app.models import Device, DeviceGroup
from tests import test_cync as _cync
from tests import test_ui as _ui

fake, secrets_key = _cync.fake, _cync.secrets_key
card, go_settings, ui_login = _ui.card, _ui.go_settings, _ui.ui_login


def url(home_id, suffix=""):
    return f"/api/v1/homes/{home_id}/groups{suffix}"


def state(db, device_id):
    db.expire_all()
    return json.loads(db.get(Device, device_id).state)


def test_groups_are_made_by_operators_and_used_by_everyone(
    client, new_client, db, owner, make_user, make_device, make_home, login, csrf
):
    home = owner.home_id
    a = make_device(home, name="Ceiling 1")
    b = make_device(home, name="Ceiling 2")
    plug = make_device(home, device_type="plug", name="Lamp plug")
    elsewhere = make_device(make_home("Home B"), name="Not ours")
    operator, member = make_user(home, role="operator"), make_user(home, role="member")
    o, m = new_client(), new_client()
    assert login(o, operator).status_code == 200
    assert login(m, member).status_code == 200

    body = {"name": "Ceiling lights", "device_ids": [a, b, plug]}
    assert m.post(url(home), json=body, headers=csrf(m)).status_code == 403
    bad = {"name": "X", "device_ids": [a, elsewhere]}
    assert o.post(url(home), json=bad, headers=csrf(o)).status_code == 422
    r = o.post(url(home), json=body, headers=csrf(o))
    assert r.status_code == 201, r.text
    group = r.json()
    assert (group["device_ids"], group["on"], group["has_lights"]) == (
        [a, b, plug],
        False,
        True,
    )

    def command(c, name, **payload):
        return c.post(
            url(home, f"/{group['id']}/command"),
            json={"command": name, "payload": payload},
            headers=csrf(c),
        )

    r = command(m, "turn_on")  # members use groups
    assert r.status_code == 200, r.text
    assert all(x["ok"] for x in r.json()["results"])
    assert r.json()["group"]["on"] is True
    assert state(db, a)["on"] and state(db, b)["on"] and state(db, plug)["on"]
    r = command(m, "set_brightness", brightness=30)
    results = {x["device_id"]: x["ok"] for x in r.json()["results"]}
    assert results == {a: True, b: True, plug: None}  # plugs have no brightness
    assert state(db, a)["brightness"] == state(db, b)["brightness"] == 30
    assert command(m, "set_temperature", temperature=70).status_code == 422

    r = o.patch(
        url(home, f"/{group['id']}"),
        json={"name": "Ceiling", "device_ids": [a]},
        headers=csrf(o),
    )
    assert r.json()["name"] == "Ceiling" and r.json()["device_ids"] == [a]
    assert m.get(url(home)).json()[0]["name"] == "Ceiling"
    assert o.delete(url(home, f"/{group['id']}"), headers=csrf(o)).status_code == 200
    assert m.get(url(home)).json() == []


def test_one_failing_device_does_not_stop_the_group(
    client, db, owner, make_device, login, csrf
):
    home = owner.home_id
    good = make_device(home, name="Good")
    off = make_device(home, name="Brand off")
    device = db.get(Device, off)
    device.integration = "cync"  # turned off in this home
    db.commit()
    assert login(client, owner).status_code == 200
    group = client.post(
        url(home),
        json={"name": "Mixed", "device_ids": [good, off]},
        headers=csrf(client),
    ).json()
    r = client.post(
        url(home, f"/{group['id']}/command"),
        json={"command": "turn_on", "payload": {}},
        headers=csrf(client),
    )
    assert r.status_code == 200
    by_id = {x["device_id"]: x for x in r.json()["results"]}
    assert by_id[good]["ok"] is True
    assert by_id[off]["ok"] is False and "turned off" in by_id[off]["detail"]
    assert state(db, good)["on"] is True


def test_cync_rooms_become_rooms_and_groups_become_groups(
    client, db, owner, login, csrf, fake, secrets_key
):
    fake.groups = [
        cync.CyncGroupInfo("room:9-1", "Living room", "Living room", ("77-1", "77-2")),
        cync.CyncGroupInfo("group:9-5", "Ceiling", "Living room", ("77-1",)),
    ]
    _cync.ready(client, csrf, login, owner)
    home = owner.home_id
    groups = {g["name"]: g for g in client.get(url(home)).json()}
    assert set(groups) == {"Ceiling"}  # the Cync room is a room, not a group
    lamp = _cync.device_id(db, home, "77-1")
    ceiling = groups["Ceiling"]
    assert (ceiling["device_ids"], ceiling["source"], ceiling["room"]) == (
        [lamp],
        "cync",
        "Living room",
    )
    db.expire_all()
    assert db.get(Device, lamp).room == "Living room"  # had no room
    assert "Living room" in client.get(f"/api/v1/homes/{home}/rooms").json()
    # Edits stay; a deleted import does not come back on the next sync.
    client.patch(
        url(home, f"/{ceiling['id']}"),
        json={"name": "Ceiling lights"},
        headers=csrf(client),
    )
    sync = f"/api/v1/homes/{home}/integrations/cync/sync"
    assert client.post(sync, headers=csrf(client)).status_code == 200
    assert [g["name"] for g in client.get(url(home)).json()] == ["Ceiling lights"]
    client.delete(url(home, f"/{ceiling['id']}"), headers=csrf(client))
    client.post(sync, headers=csrf(client))
    assert client.get(url(home)).json() == []
    assert db.query(DeviceGroup).filter_by(home_id=home).count() == 1  # kept as deleted


def test_rooms_device_group_choice_and_display(
    client, new_client, db, owner, make_user, make_device, login, csrf
):
    home = owner.home_id
    a = make_device(home, name="Ceiling 1")
    b = make_device(home, name="Ceiling 2")
    assert login(client, owner).status_code == 200
    rooms = f"/api/v1/homes/{home}/rooms"
    r = client.post(rooms, json={"name": "Kitchen"}, headers=csrf(client))
    assert r.json() == ["Kitchen", "Lab"]  # Lab: the test devices' room
    group = client.post(
        url(home), json={"name": "Ceiling", "room": "Kitchen"}, headers=csrf(client)
    ).json()
    assert group["room"] == "Kitchen" and group["device_ids"] == []
    choose = f"/api/v1/homes/{home}/devices/{{}}/group"
    for device in (a, b):
        r = client.put(
            choose.format(device), json={"group_id": group["id"]}, headers=csrf(client)
        )
        assert r.status_code == 200, r.text
    assert client.get(url(home)).json()[0]["device_ids"] == [a, b]
    other = client.post(url(home), json={"name": "Other"}, headers=csrf(client)).json()
    client.put(choose.format(b), json={"group_id": other["id"]}, headers=csrf(client))
    by_name = {g["name"]: g for g in client.get(url(home)).json()}
    assert by_name["Ceiling"]["device_ids"] == [a]  # moved, not copied
    assert by_name["Other"]["device_ids"] == [b]
    client.put(choose.format(b), json={"group_id": None}, headers=csrf(client))
    by_name = {g["name"]: g for g in client.get(url(home)).json()}
    assert by_name["Other"]["device_ids"] == []
    # Deleting a room moves its groups to "No room" (then: their devices' room).
    assert (
        "Kitchen" not in client.delete(f"{rooms}/Kitchen", headers=csrf(client)).json()
    )
    by_name = {g["name"]: g for g in client.get(url(home)).json()}
    assert by_name["Ceiling"]["room"] == "Lab"
    display = f"/api/v1/homes/{home}/display"
    assert client.get(display).json() == {"show_grouped_devices": False}
    operator = make_user(home, role="operator")
    o = new_client()
    assert login(o, operator).status_code == 200
    body = {"show_grouped_devices": True}
    assert o.put(display, json=body, headers=csrf(o)).status_code == 403
    assert client.put(display, json=body, headers=csrf(client)).json() == body


def test_group_is_offline_when_no_device_is(
    client, db, owner, make_device, login, csrf
):
    a = make_device(owner.home_id, name="Ceiling 1")
    db.get(Device, a).online = False
    db.commit()
    assert login(client, owner).status_code == 200
    body = {"name": "G", "device_ids": [a]}
    assert (
        client.post(url(owner.home_id), json=body, headers=csrf(client)).json()[
            "online"
        ]
        is False
    )


def test_live_cync_stores_reports(
    client, db, owner, login, csrf, fake, secrets_key, monkeypatch
):
    _cync.ready(client, csrf, login, owner)
    lamp = _cync.device_id(db, owner.home_id, "77-1")
    started = []

    async def listen(tokens, on_states, poll_seconds=30, on_open=None):
        started.append(tokens["access_token"])
        await on_states({"77-1": {"on": True, "brightness": 12}})
        await asyncio.sleep(3600)

    monkeypatch.setattr(cync, "listen", listen)

    async def run():
        await cync_live.check_once()
        await asyncio.sleep(0.3)
        assert list(cync_live._listeners) == [owner.home_id]
        await cync_live.check_once()  # already listening: not started twice
        for task in cync_live._listeners.values():
            task.cancel()
        cync_live._listeners.clear()

    # In its own thread: the browser tests keep an event loop running here.
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        pool.submit(asyncio.run, run()).result()
    assert len(started) == 1
    assert state(db, lamp)["brightness"] == 12


# ------------------------------------------------------------ browser


def test_ui_group_card_and_window(open_page, db, owner, make_device):
    a = make_device(owner.home_id, name="Ceiling 1")
    b = make_device(owner.home_id, name="Ceiling 2")
    db.add(
        DeviceGroup(
            home_id=owner.home_id, name="Ceiling lights", device_ids=json.dumps([a, b])
        )
    )
    db.commit()
    page = open_page()
    ui_login(page, owner)
    group = page.get_by_test_id("group-card")
    expect(group).to_contain_text("Ceiling lights")
    expect(page.get_by_test_id("device-card")).to_have_count(
        0
    )  # its devices are inside it
    group.get_by_test_id("power-toggle").click()
    expect(
        page.get_by_test_id("group-card").get_by_test_id("power-toggle")
    ).to_have_attribute("aria-pressed", "true")
    assert state(db, a)["on"] and state(db, b)["on"]
    page.get_by_test_id("group-card").get_by_test_id("group-menu").click()
    panel = page.get_by_test_id("group-panel")
    expect(panel.get_by_test_id("device-card")).to_have_count(2)
    panel.locator('[data-testid="device-card"]').filter(
        has_text="Ceiling 2"
    ).get_by_test_id("power-toggle").click()
    expect(
        page.get_by_test_id("group-panel")
        .locator('[data-testid="device-card"]')
        .filter(has_text="Ceiling 2")
        .get_by_test_id("power-toggle")
    ).to_have_attribute("aria-pressed", "false")
    assert state(db, a)["on"] is True and state(db, b)["on"] is False


def test_ui_make_a_group_in_settings(open_page, db, owner, make_device):
    a = make_device(owner.home_id, name="Ceiling 1")
    b = make_device(owner.home_id, name="Ceiling 2")
    make_device(owner.home_id, device_type="tv", name="Den TV")
    page = open_page()
    ui_login(page, owner)
    page.get_by_test_id("groups-make").click()  # from the Devices page
    section = page.get_by_test_id("settings-devices")
    expect(section).to_be_visible()
    section.get_by_test_id("room-new-name").fill("Kitchen")
    section.get_by_test_id("room-create").click()
    expect(
        section.locator('[data-testid="room-row"][data-room="Kitchen"]')
    ).to_be_visible()
    new = section.get_by_test_id("group-new")
    new.get_by_test_id("group-new-name").fill("Ceiling lights")
    new.get_by_test_id("group-new-room").select_option("Kitchen")
    new.get_by_test_id("group-create").click()
    expect(section.get_by_test_id("group-row")).to_have_count(1)
    for device in (a, b):
        row = section.locator(f'[data-testid="device-row"][data-device-id="{device}"]')
        row.get_by_test_id("device-group").select_option(label="Ceiling lights")
    section.get_by_test_id("device-save-top").click()
    expect(page.get_by_test_id("status")).to_contain_text("Saved 2 devices")
    section.get_by_test_id("device-filter").select_option("tv")
    expect(section.locator('[data-testid="device-row"]:visible')).to_have_count(1)
    page.get_by_test_id("nav-devices").click()
    kitchen = page.locator('[data-testid="room"][data-room="Kitchen"]')
    expect(kitchen.get_by_test_id("group-card")).to_contain_text("2 devices")
    expect(page.get_by_test_id("device-card")).to_have_count(1)  # only the TV


def test_ui_show_grouped_devices_apart(open_page, db, owner, make_device):
    a = make_device(owner.home_id, name="Ceiling 1")
    db.add(
        DeviceGroup(home_id=owner.home_id, name="Ceiling", device_ids=json.dumps([a]))
    )
    db.commit()
    page = open_page()
    ui_login(page, owner)
    section = go_settings(page, "admin")
    section.get_by_test_id("show-grouped-toggle").check()
    expect(page.get_by_test_id("status")).to_have_attribute("data-kind", "success")
    page.get_by_test_id("nav-devices").click()
    expect(page.get_by_test_id("groups").get_by_test_id("group-card")).to_have_count(1)
    expect(page.get_by_test_id("device-card")).to_have_count(1)  # in its room too


def test_ui_group_light_settings(open_page, db, owner, make_device):
    a = make_device(owner.home_id, name="Ceiling 1")
    b = make_device(owner.home_id, name="Ceiling 2")
    db.add(
        DeviceGroup(
            home_id=owner.home_id, name="Ceiling", device_ids=json.dumps([a, b])
        )
    )
    db.commit()
    page = open_page()
    ui_login(page, owner)
    page.get_by_test_id("group-card").get_by_test_id("light-settings-open").click()
    panel = page.get_by_test_id("light-panel")
    panel.get_by_test_id("light-brightness").fill("25")
    expect(page.get_by_test_id("status")).to_have_attribute("data-kind", "success")
    assert state(db, a)["brightness"] == state(db, b)["brightness"] == 25


def test_commands_share_the_live_cync_connection(
    client, db, owner, login, csrf, fake, secrets_key, monkeypatch
):
    """Cync allows one connection per account: with the live connection open,
    commands go through it instead of logging in again."""
    _cync.ready(client, csrf, login, owner)
    lamp = _cync.device_id(db, owner.home_id, "77-1")
    used = []
    monkeypatch.setitem(cync_live._open, owner.home_id, ("api", "loop"))
    monkeypatch.setattr(
        cync,
        "act_on_open",
        lambda api, loop, device_id, action, value: used.append(
            (api, device_id, action, value)
        ),
    )
    r = client.post(
        f"/api/v1/homes/{owner.home_id}/devices/{lamp}/command",
        json={"command": "turn_on", "payload": {}},
        headers=csrf(client),
    )
    assert r.status_code == 200, r.text
    assert used == [("api", "77-1", "power", True)]
    assert fake.sent == []  # no second login


def test_thermostat_probe_decodes_data_points():
    import importlib.util
    from pathlib import Path

    path = (
        Path(__file__).resolve().parent.parent / "scripts" / "cync_thermostat_probe.py"
    )
    spec = importlib.util.spec_from_file_location("probe", path)
    probe = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(probe)
    entries = bytes.fromhex("0b900537322e3046") + bytes.fromhex("05400400000033")
    lines = probe.decode_entries(entries)
    assert "Setpoint_heat_set" in lines[0] and "'72.0F'" in lines[0]
    assert "RealtimeHumidity" in lines[1] and "51" in lines[1]
    assert (
        probe.packet(10, b"\x00\x00\x00\x07\x00\x01\x00").hex()
        == "a3000000070000000700" + "0100"
    )
