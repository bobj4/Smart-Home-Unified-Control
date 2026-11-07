"""A Samsung TV's power key goes only where it does the right thing: the
same key turns a TV on (from network standby) and off, so a TV that says it
is in standby is never "turned off" (which turned it on) and one that is on
is never "turned on" (which turned it off). The remote's power symbol is
drawn, as many fonts have no ⏻ glyph."""

import pytest
import requests
from playwright.sync_api import expect

from app import tv_power
from tests import test_samsung as _tv
from tests import test_ui as _ui

tv, secrets_key = _tv.tv, _tv.secrets_key


def test_plan():
    plan = tv_power.plan
    mac = "AA:BB:CC:DD:EE:FF"
    assert plan("turn_off", "on", mac) == "key"
    assert plan("turn_off", None, mac) == "key"  # a TV that does not say
    assert plan("turn_off", "standby", mac) == "nothing"  # the key would wake it
    assert plan("turn_on", "on", mac) == "nothing"  # the key would turn it off
    assert plan("turn_on", "standby", mac) == "key"  # wakes at once
    assert plan("turn_on", None, mac) == "wake"
    assert plan("turn_on", None, None) == "key"  # 2014-2017: no standby answer


class Answer:
    def __init__(self, body):
        self.body = body

    def json(self):
        if isinstance(self.body, Exception):
            raise self.body
        return self.body


@pytest.mark.parametrize(
    ("body", "expected"),
    [
        ({"device": {"PowerState": "on"}}, "on"),
        ({"device": {"PowerState": "standby"}}, "standby"),
        ({"device": {"name": "2017 TV"}}, "on"),  # only answers while on
        (ValueError("not JSON"), None),
        (requests.ConnectionError("off"), None),
    ],
)
def test_power_state(monkeypatch, body, expected):
    def get(url, timeout):
        assert url == "http://192.168.1.50:8001/api/v2/"
        if isinstance(body, requests.RequestException):
            raise body
        return Answer(body)

    monkeypatch.setattr(tv_power.requests, "get", get)
    assert tv_power.power_state("192.168.1.50", "tizen") == expected
    assert tv_power.power_state("192.168.1.50", "legacy") is None


def test_wake_reaches_the_tvs_own_network(monkeypatch):
    assert tv_power._targets("192.168.1.50") == ["192.168.1.255", "192.168.1.50"]
    assert tv_power._targets("tv.local") == []
    sent, woke = [], []

    class Sock:
        def __init__(self, *args):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def setsockopt(self, *args):
            pass

        def sendto(self, packet, target):
            assert packet == b"\xff" * 6 + bytes.fromhex("aabbccddeeff") * 16
            sent.append(target)

    monkeypatch.setattr(tv_power.socket, "socket", Sock)
    monkeypatch.setattr(tv_power.samsung, "wake", woke.append)
    tv_power.wake("AA:BB:CC:DD:EE:FF", "192.168.1.50")
    assert woke == ["AA:BB:CC:DD:EE:FF"]
    assert sent == [("192.168.1.255", 9), ("192.168.1.50", 9)]


def test_power_commands_follow_the_tvs_answer(
    client, owner, login, csrf, tv, secrets_key, monkeypatch
):
    device_id = _tv.ready_tv(client, csrf, login, owner, tv, mac="AA:BB:CC:DD:EE:FF")
    home = owner.home_id
    answer = ["standby"]
    monkeypatch.setattr(tv_power, "power_state", lambda host, protocol: answer[0])
    monkeypatch.setattr(tv_power, "wake", lambda mac, host: tv.wakes.append(mac))

    def power(command):
        r = _tv.command(client, csrf, home, device_id, command)
        assert r.status_code == 200
        return r.json()["state"]["on"]

    assert power("turn_off") is False and tv.keys == []  # already in standby
    assert power("turn_on") is True
    assert [k[3] for k in tv.keys] == [["KEY_POWER"]] and tv.wakes == []
    answer[0] = "on"
    assert power("turn_on") is True and len(tv.keys) == 1  # already on
    assert power("turn_off") is False and len(tv.keys) == 2
    answer[0] = None  # not answering: off, so the wake-up packet
    assert power("turn_on") is True and tv.wakes == ["AA:BB:CC:DD:EE:FF"]


def test_ui_remote_power_symbol_is_drawn(
    open_page, new_client, owner, make_user, login, csrf, tv, secrets_key
):
    _tv.ready_tv(new_client(), csrf, login, owner, tv)
    admin = make_user(owner.home_id, role="admin")
    page = open_page()
    _ui.ui_login(page, admin)
    _ui.card(page, "Living room TV").get_by_test_id("tv-remote-open").click()
    power = page.get_by_test_id("tv-remote").get_by_test_id("remote-power")
    expect(power).to_have_text("Power")
    expect(power.locator("svg.power-icon")).to_be_visible()
