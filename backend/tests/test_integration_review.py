# ruff: noqa: F811 (fixtures shared with test_rheem and test_hue)
"""The integration review's fixes: ratgdo on ESPHome 2026.7+, Rheem kept
through an empty EcoNet answer, Hue offline with its bridge, LG's power
state and stronger wake-up, Kasa's newer SMART API and white range,
Roku's USB, and the background refresh reading side by side with back-off
for devices that keep not answering."""

import json

import pytest

from app import (
    features,
    hue_home,
    integration_status,
    kasa_home,
    lg_home,
    probes,
    refresh,
    tv_power,
)
from app.integrations import hue, kasa, lg, ratgdo, roku
from app.models import Device
from tests.test_hue import BRIDGE, bridge  # noqa: F401
from tests.test_rheem import (  # noqa: F401
    econet,
    ready,
    rheem_devices,
    secrets_key,
    sync,
)

HOST = "192.168.1.80"


class Answer:
    def __init__(self, status=200, data=None, text=False):
        self.status_code, self._data, self._text = status, data, text

    def json(self):
        if self._text:
            raise ValueError("not JSON")
        return self._data


# ------------------------------------------------------------ ratgdo


def opener(paths, calls):
    def request(method, url, timeout):
        calls.append((method, url))
        path = url.split(HOST, 1)[1].rsplit("/", 1)
        path = (
            path[0] if path[-1] in ("open", "close", "stop") else url.split(HOST, 1)[1]
        )
        if path not in paths:
            return Answer(404)
        return Answer(
            200, {"state": "CLOSED", "value": 0.0, "current_operation": "IDLE"}
        )

    return request


def test_ratgdo_by_name_then_the_older_object_id(monkeypatch):
    calls = []
    ratgdo._door_path.clear()
    monkeypatch.setattr(ratgdo.requests, "request", opener({"/cover/Door"}, calls))
    assert ratgdo.door(HOST)["door"] == "closed"  # ESPHome 2026.7+
    ratgdo.act(HOST, "open")
    assert calls[-1] == ("POST", f"http://{HOST}/cover/Door/open")
    # Older firmware: only the object id answers; remembered after.
    ratgdo._door_path.clear()
    calls.clear()
    monkeypatch.setattr(ratgdo.requests, "request", opener({"/cover/door"}, calls))
    assert ratgdo.door(HOST)["door"] == "closed"
    assert [u for _, u in calls] == [
        f"http://{HOST}/cover/Door",
        f"http://{HOST}/cover/door",
    ]
    ratgdo.act(HOST, "close")
    assert calls[-1] == ("POST", f"http://{HOST}/cover/door/close")
    # Nothing answers: the plain reason.
    ratgdo._door_path.clear()
    monkeypatch.setattr(ratgdo.requests, "request", opener(set(), []))
    with pytest.raises(ratgdo.RatgdoError, match="ESPHome"):
        ratgdo.door(HOST)


def test_ratgdo_and_hue_say_so_when_the_answer_is_not_json(monkeypatch):
    ratgdo._door_path.clear()
    monkeypatch.setattr(
        ratgdo.requests, "request", lambda *a, **k: Answer(200, text=True)
    )
    with pytest.raises(ratgdo.RatgdoError, match="not as a ratgdo"):
        ratgdo.door(HOST)
    monkeypatch.setattr(hue.requests, "request", lambda *a, **k: Answer(200, text=True))
    with pytest.raises(hue.HueError, match="not as a Hue Bridge"):
        hue.pair(BRIDGE)


# ------------------------------------------------------------ Rheem


def test_rheem_refresh_keeps_heaters_through_an_empty_answer(
    client, db, owner, login, csrf, econet, secrets_key
):
    ready(client, csrf, login, owner)
    assert sync(client, csrf, owner.home_id).status_code == 200
    (device,) = rheem_devices(db, owner.home_id)
    econet.heaters = []
    assert refresh.refresh_rheem(db, owner.home_id, now=1e9) is True
    (kept,) = rheem_devices(db, owner.home_id)
    assert kept.id == device.id and kept.online is False


# ------------------------------------------------------------ Hue


def test_hue_lights_go_offline_with_their_bridge(
    client, db, owner, login, csrf, bridge, secrets_key, monkeypatch
):
    assert login(client, owner).status_code == 200
    base = f"/api/v1/homes/{owner.home_id}/integrations/hue"
    client.put(base, json={"enabled": True}, headers=csrf(client))
    assert (
        client.post(
            f"{base}/pair", json={"host": BRIDGE}, headers=csrf(client)
        ).status_code
        == 200
    )

    def down(host, key):
        raise hue.HueError("could not reach the Hue Bridge: ConnectTimeout")

    monkeypatch.setattr(hue, "lights", down)
    assert hue_home.refresh(db, owner.home_id) == 2  # no exception
    db.expire_all()
    assert all(not d.online for d in hue_home.list_lights(db, owner.home_id))
    assert hue_home.INTEGRATION in integration_status.for_home(owner.home_id)


# ------------------------------------------------------------ LG


def lg_tv(db, owner, make_device, mac=None):
    features.set_integration(db, owner.home_id, lg_home.INTEGRATION, True, None, None)
    device = db.get(Device, make_device(owner.home_id, device_type="tv", name="Den"))
    device.integration = lg_home.INTEGRATION
    device.capabilities = json.dumps({"paired": True, "mac": mac})
    device.external_id = "192.168.1.70"
    db.commit()
    return device


def test_lg_standby_is_off_not_offline(db, owner, make_device, monkeypatch):
    device = lg_tv(db, owner, make_device)
    state = {"now": "standby"}
    monkeypatch.setattr(lg, "power_state", lambda host, key: state["now"])
    lg_home.refresh(db, owner.home_id)
    db.expire_all()
    stored = json.loads(db.get(Device, device.id).state)
    assert (stored["on"], stored["reachable"]) == (False, True)


def test_lg_power_state_reads_the_tv(monkeypatch):
    monkeypatch.setattr(lg, "is_on", lambda host: True)

    class Session:
        def __init__(self, host, key):
            pass

        def request(self, uri):
            assert uri.endswith("getPowerState")
            return {"state": answer["state"]}

        def close(self):
            pass

    monkeypatch.setattr(lg, "_Session", Session)
    answer = {"state": "Active Standby"}
    assert lg.power_state("h", "KEY") == "standby"
    answer["state"] = "Screen Off"
    assert lg.power_state("h", "KEY") == "on"
    monkeypatch.setattr(lg, "is_on", lambda host: False)
    assert lg.power_state("h", "KEY") is None


def test_lg_wakes_everywhere_the_tv_may_hear(
    client, db, owner, login, csrf, make_device, monkeypatch
):
    device = lg_tv(db, owner, make_device, mac="AA:BB:CC:DD:EE:FF")
    woken = []
    monkeypatch.setattr(tv_power, "wake", lambda mac, host: woken.append((mac, host)))
    lg_home.send_tv_command(db, device, "turn_on", {})
    assert woken == [("AA:BB:CC:DD:EE:FF", "192.168.1.70")]


# ------------------------------------------------------------ Kasa


def test_kasa_white_range_by_model():
    body = kasa.body_for(
        "set_color_temp", {"color_temp": 2000}, True, None, kasa.ct_range("KL120(US)")
    )
    light = body[kasa.BULB]["transition_light_state"]
    assert light["color_temp"] == 2700
    body = kasa.body_for(
        "set_color_temp", {"color_temp": 6500}, True, None, (2700, 5000)
    )
    assert body[kasa.BULB]["transition_light_state"]["color_temp"] == 5000
    assert kasa.smart_params("set_color_temp", {"color_temp": 2000}, [2500, 6500]) == {
        "device_on": True,
        "color_temp": 2500,
    }


def smart_device(monkeypatch, info, children=None):
    asked = []

    def request(host, body, login=None):
        asked.append(body)
        if "system" in body:
            return {"error_code": -1}  # a SMART device does not take the old JSON
        method = body["method"]
        if method == "get_device_info":
            return {"error_code": 0, "result": info}
        if method == "get_child_device_list":
            return {"error_code": 0, "result": {"child_device_list": children or []}}
        return {"error_code": 0, "result": {}}

    monkeypatch.setattr(kasa, "request", request)
    return asked


def b64(text):
    import base64

    return base64.b64encode(text.encode()).decode()


def test_kasa_smart_plug_bulb_and_strip(monkeypatch):
    smart_device(
        monkeypatch,
        {
            "type": "SMART.KASAPLUG",
            "model": "KP125M",
            "nickname": b64("Kettle"),
            "device_on": True,
        },
    )
    [plug] = kasa.devices(HOST)
    assert (plug["name"], plug["kind"], plug["smart"], plug["on"]) == (
        "Kettle",
        "plug",
        True,
        True,
    )
    smart_device(
        monkeypatch,
        {
            "type": "SMART.TAPOBULB",
            "model": "L530",
            "nickname": b64("Lamp"),
            "device_on": False,
            "brightness": 40,
            "color_temp": 2700,
            "color_temp_range": [2500, 6500],
            "hue": 0,
        },
    )
    [bulb] = kasa.devices(HOST)
    assert bulb["kind"] == "light" and bulb["white"] and bulb["color"]
    assert bulb["ct_range"] == [2500, 6500] and bulb["brightness"] == 40
    smart_device(
        monkeypatch,
        {"type": "SMART.KASAPLUG", "model": "EP40M", "nickname": b64("Strip")},
        [
            {"device_id": "C1", "nickname": b64("Lamp"), "device_on": True},
            {"device_id": "C2", "nickname": b64("Fan"), "device_on": False},
        ],
    )
    outlets = kasa.devices(HOST)
    assert [(o["id"], o["name"], o["child"]) for o in outlets] == [
        (f"{HOST}/C1", "Lamp", "C1"),
        (f"{HOST}/C2", "Fan", "C2"),
    ]


def test_kasa_smart_commands_and_login(monkeypatch):
    asked = smart_device(monkeypatch, {})
    kasa.send_smart(HOST, {"device_on": True}, "C2")
    assert asked[-1]["method"] == "control_child"
    assert asked[-1]["params"] == {
        "device_id": "C2",
        "requestData": {"method": "set_device_info", "params": {"device_on": True}},
    }
    kasa.send_smart(HOST, {"device_on": False}, None)
    assert asked[-1]["method"] == "set_device_info"
    monkeypatch.setattr(
        kasa, "request", lambda host, body, login=None: {"error_code": -1501}
    )
    with pytest.raises(kasa.KasaLogin):
        kasa.smart(HOST, "get_device_info")


def test_smart_commands_skip_the_old_protocol(monkeypatch):
    tried = []
    monkeypatch.setattr(kasa, "_xor_request", lambda host, body: tried.append("xor"))

    class Klap:
        def __init__(self, host, logins):
            tried.append("klap")

        def request(self, body):
            return {"error_code": 0, "result": {}}

    monkeypatch.setattr(kasa, "_Klap", Klap)
    kasa.smart(HOST, "get_device_info")
    assert tried == ["klap"]


def test_kasa_home_sends_smart_commands(
    client, db, owner, login, csrf, monkeypatch, secrets_key
):
    sent = []
    monkeypatch.setattr(
        kasa,
        "send_smart",
        lambda host, params, child, login=None: sent.append((host, params, child)),
    )
    features.set_integration(db, owner.home_id, kasa_home.INTEGRATION, True, None, None)
    device = Device(
        home_id=owner.home_id,
        integration="kasa",
        external_id=HOST,
        type="light",
        name="Lamp",
        capabilities=json.dumps(
            {"host": HOST, "smart": True, "bulb": True, "ct_range": [2500, 6500]}
        ),
        state="{}",
        online=True,
    )
    db.add(device)
    db.commit()
    kasa_home.send_command(db, device, "set_color_temp", {"color_temp": 2000})
    assert sent == [(HOST, {"device_on": True, "color_temp": 2500}, None)]


# ------------------------------------------------------------ Roku


def test_roku_usb_opens_the_media_player(monkeypatch):
    done = []
    monkeypatch.setattr(roku, "launch", lambda host, app: done.append(("launch", app)))
    monkeypatch.setattr(roku, "keypress", lambda host, key: done.append(("key", key)))
    roku.command(HOST, "set_input", {"source": "usb"})
    roku.command(HOST, "set_input", {"source": "hdmi2"})
    assert done == [("launch", "2213"), ("key", "InputHDMI2")]


# ------------------------------------------------------------ refresh


def test_back_off_after_two_misses_in_a_row():
    key = "test:back-off"
    probes._misses.pop(key, None)
    assert probes.due(key, now=0)
    probes.answered(key, False, now=0)
    assert probes.due(key, now=1)  # one miss: asked again next pass
    probes.answered(key, False, now=1)
    assert not probes.due(key, now=30) and probes.due(key, now=62)
    probes.answered(key, False, now=62)
    assert not probes.due(key, now=150) and probes.due(key, now=183)
    for when in (183, 500, 900):
        probes.answered(key, False, now=when)
    assert not probes.due(key, now=1100) and probes.due(key, now=1201)  # 5 minutes
    probes.answered(key, True)
    assert probes.due(key, now=1201)


def test_reads_run_side_by_side():
    import threading
    import time

    barrier = threading.Barrier(3, timeout=2)

    def read(n):
        barrier.wait()  # only returns if all three run at once
        return n

    started = time.monotonic()
    found = probes.gather({str(n): (lambda n=n: read(n)) for n in range(3)})
    assert found == {"0": 0, "1": 1, "2": 2} and time.monotonic() - started < 2
    boom = probes.gather({"x": lambda: 1 / 0})
    assert isinstance(boom["x"], ZeroDivisionError)


def test_an_offline_kasa_plug_is_asked_less_often(db, owner, monkeypatch, secrets_key):
    features.set_integration(db, owner.home_id, kasa_home.INTEGRATION, True, None, None)
    db.add(
        Device(
            home_id=owner.home_id,
            integration="kasa",
            external_id="10.0.0.9",
            type="plug",
            name="Far plug",
            capabilities=json.dumps({"host": "10.0.0.9"}),
            state="{}",
            online=True,
        )
    )
    db.commit()
    probes._misses.pop("kasa:10.0.0.9", None)
    asked = []

    def gone(host, login=None):
        asked.append(host)
        raise kasa.KasaError("could not reach the device: timed out")

    monkeypatch.setattr(kasa, "devices", gone)
    for _ in range(4):
        kasa_home.refresh(db, owner.home_id)
    assert asked == ["10.0.0.9", "10.0.0.9"]  # then it waits a minute
    probes._misses.pop("kasa:10.0.0.9", None)
