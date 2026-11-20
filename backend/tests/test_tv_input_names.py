"""TV inputs named by people (HDMI 2 = "PlayStation"): the remote's Input
list without SmartThings (switched by remote key on the home network)."""

import json

from playwright.sync_api import expect

from app.models import Device
from tests import test_ui as _ui


def url(owner, device_id):
    return f"/api/v1/homes/{owner.home_id}/devices/{device_id}/input-names"


def test_naming_inputs(
    client, new_client, db, owner, make_user, make_device, login, csrf
):
    tv = make_device(owner.home_id, device_type="tv", name="Den TV")
    lamp = make_device(owner.home_id, device_type="light", name="Lamp")
    assert login(client, owner).status_code == 200
    r = client.put(
        url(owner, tv),
        json={"names": {"hdmi2": "  PlayStation  5 ", "hdmi1": "", "usb": "Photos"}},
        headers=csrf(client),
    )
    assert r.status_code == 200, r.text
    assert r.json()["input_names"] == {"hdmi2": "PlayStation 5", "usb": "Photos"}
    db.expire_all()
    caps = json.loads(db.get(Device, tv).capabilities)
    assert caps["input_names"] == {"hdmi2": "PlayStation 5", "usb": "Photos"}
    shown = {
        d["id"]: d for d in client.get(f"/api/v1/homes/{owner.home_id}/devices").json()
    }
    assert shown[tv]["input_names"]["hdmi2"] == "PlayStation 5"
    assert shown[lamp]["input_names"] is None
    for bad in ({"tv": "Antenna"}, {"hdmi9": "x"}, {"hdmi1": "x" * 31}):
        r = client.put(url(owner, tv), json={"names": bad}, headers=csrf(client))
        assert r.status_code == 422, bad
    r = client.put(url(owner, lamp), json={"names": {}}, headers=csrf(client))
    assert r.status_code == 422
    r = client.put(url(owner, tv), json={"names": {}}, headers=csrf(client))
    assert r.json()["input_names"] == {}  # all blank: cleared
    member = make_user(owner.home_id, role="member")
    other = new_client()
    assert login(other, member).status_code == 200
    r = other.put(
        url(owner, tv), json={"names": {"hdmi1": "Xbox"}}, headers=csrf(other)
    )
    assert r.status_code == 403


def test_ui_name_inputs_and_switch(open_page, db, owner, make_device):
    tv = make_device(owner.home_id, device_type="tv", name="Living room TV")
    page = open_page()
    _ui.ui_login(page, owner)
    _ui.card(page, "Living room TV").get_by_test_id("tv-quick-menu").click()
    menu = page.get_by_test_id("tv-menu")
    expect(menu.get_by_test_id("tv-menu-quick-apps")).to_have_count(0)  # not a Samsung
    menu.get_by_test_id("tv-menu-input-names").click()
    form = page.get_by_test_id("input-names-form")
    form.get_by_test_id("input-name-hdmi2").fill("PlayStation")
    form.get_by_test_id("input-names-save").click()
    expect(page.get_by_test_id("status")).to_contain_text("input names saved")
    expect(page.get_by_test_id("tv-menu")).to_be_hidden()
    remote = _ui.open_remote(page, "Living room TV")
    remote.get_by_test_id("remote-power").click()
    choice = remote.get_by_test_id("remote-input")
    expect(choice).to_be_enabled(timeout=15000)  # on (a slower computer: give it time)
    expect(choice.locator('option[value="hdmi2"]')).to_have_text("PlayStation (HDMI 2)")
    expect(choice.locator('option[value="hdmi1"]')).to_have_text("HDMI 1")
    choice.select_option("hdmi2")
    expect(remote.get_by_test_id("remote-screen")).to_contain_text(
        "PlayStation (HDMI 2)"
    )
    assert _ui.device_state(db, tv)["input"] == "hdmi2"
    remote.get_by_test_id("remote-close").click()
    # Again: the names are filled in.
    _ui.card(page, "Living room TV").get_by_test_id("tv-quick-menu").click()
    page.get_by_test_id("tv-menu-input-names").click()
    expect(page.get_by_test_id("input-name-hdmi2")).to_have_value("PlayStation")


def test_ui_members_do_not_name_inputs(open_page, db, owner, make_user, make_device):
    make_device(owner.home_id, device_type="tv", name="Den TV")
    member = make_user(owner.home_id, role="member")
    page = open_page()
    _ui.ui_login(page, member)
    expect(_ui.card(page, "Den TV")).to_be_visible()
    expect(_ui.card(page, "Den TV").get_by_test_id("tv-quick-menu")).to_have_count(0)
