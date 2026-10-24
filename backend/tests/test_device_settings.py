"""Settings > Devices: one Save for many rows, Delete; safety limits only for
device types the home has. Written by the reviewer. Do not edit, skip, mark or
delete these tests. If one looks wrong, stop and report the test name and its
full failure output instead of changing it.
"""

from playwright.sync_api import expect

from app.models import Device
from tests import test_samsung as _tv
from tests import test_ui as _ui

tv, secrets_key = _tv.tv, _tv.secrets_key
card = _ui.card

go_settings, ui_login = _ui.go_settings, _ui.ui_login


def row(section, device_id):
    return section.locator(f'[data-testid="device-row"][data-device-id="{device_id}"]')


def test_ui_save_many_rows_at_once(open_page, db, owner, make_device):
    a = make_device(owner.home_id, name="Lamp A")
    b = make_device(owner.home_id, name="Lamp B")
    page = open_page()
    ui_login(page, owner)
    section = go_settings(page, "devices")
    row(section, a).get_by_test_id("device-room").fill("Office")
    row(section, b).get_by_test_id("device-name").fill("Reading lamp")
    section.get_by_test_id("device-save-top").click()
    expect(page.get_by_test_id("status")).to_contain_text("Saved 2 devices")
    db.expire_all()
    assert db.get(Device, a).room == "Office"
    assert db.get(Device, b).name == "Reading lamp"
    section.get_by_test_id("device-save-bottom").click()
    expect(page.get_by_test_id("status")).to_contain_text("Nothing to save")


def test_ui_delete_from_devices_settings(open_page, db, owner, make_device):
    lamp = make_device(owner.home_id, name="Old lamp")
    page = open_page()
    ui_login(page, owner)
    section = go_settings(page, "devices")
    row(section, lamp).get_by_test_id("device-delete").click()
    assert db.get(Device, lamp) is not None  # asks first
    row(section, lamp).get_by_test_id("device-delete-confirm").click()
    expect(page.get_by_test_id("status")).to_have_attribute("data-kind", "success")
    expect(row(section, lamp)).to_have_count(0)
    db.expire_all()
    assert db.get(Device, lamp) is None


def test_ui_safety_limits_only_for_present_types(open_page, owner, make_device):
    page = open_page()
    ui_login(page, owner)
    section = go_settings(page, "safety")
    expect(section.get_by_test_id("limits-none")).to_be_visible()
    make_device(owner.home_id, device_type="water_heater", name="Tank")
    page.reload()
    section = page.get_by_test_id("settings-safety")
    expect(section.get_by_test_id("limits-row")).to_have_count(1)
    expect(
        section.locator('[data-testid="limits-row"][data-device-type="water_heater"]')
    ).to_be_visible()


def test_ui_device_network_info(open_page, owner, make_device):
    make_device(owner.home_id, name="Lamp")
    page = open_page()
    ui_login(page, owner)
    section = go_settings(page, "integrations")
    item = section.get_by_test_id("integration-device")
    item.get_by_test_id("device-info").click()
    panel = page.get_by_test_id("device-info-panel")  # a window, like Light settings
    expect(panel).to_be_visible()
    expect(panel).to_contain_text("IP address")
    expect(panel).to_contain_text("not reported")
    panel.get_by_test_id("device-info-close").click()
    expect(page.get_by_test_id("device-info-panel")).to_have_count(0)
    section = go_settings(page, "devices")  # the same button in Settings > Devices
    section.get_by_test_id("device-row").get_by_test_id("device-info").click()
    expect(page.get_by_test_id("device-info-panel")).to_contain_text("Lamp")


def test_tv_network_and_protocol_in_device_list(
    client, owner, login, csrf, tv, secrets_key
):
    device_id = _tv.ready_tv(
        client, csrf, login, owner, tv, protocol="legacy", mac="aa:bb:cc:dd:ee:ff"
    )
    r = client.get(f"/api/v1/homes/{owner.home_id}/devices")
    out = next(d for d in r.json() if d["id"] == device_id)
    assert out["network"] == {"ip": _tv.HOST, "mac": "AA:BB:CC:DD:EE:FF"}
    assert out["protocol"] == "legacy"


def test_ui_older_tv_hides_app_buttons(
    open_page, new_client, owner, make_user, login, csrf, tv, secrets_key
):
    c = new_client()
    _tv.ready_tv(c, csrf, login, owner, tv, protocol="legacy")
    admin = make_user(
        owner.home_id, role="admin"
    )  # a second login: codes are single-use
    page = open_page()
    ui_login(page, admin)
    card(page, "Living room TV").get_by_test_id("tv-remote-open").click()
    remote = page.get_by_test_id("tv-remote")
    expect(remote.get_by_test_id("remote-power")).to_be_visible()
    expect(remote.get_by_test_id("remote-apps")).to_have_count(0)


def test_ui_remote_layout(open_page, owner, make_device):
    make_device(owner.home_id, device_type="tv", name="Den TV")
    page = open_page()
    ui_login(page, owner)
    card(page, "Den TV").get_by_test_id("tv-remote-open").click()
    remote = page.get_by_test_id("tv-remote")
    expect(remote).to_be_visible()

    def box(testid):
        return remote.get_by_test_id(testid).bounding_box()

    power, home, info, volume = (
        box("remote-power"),
        box("remote-key-home"),
        box("remote-key-info"),
        box("remote-volume-up"),
    )
    assert power["y"] < home["y"] < volume["y"]  # under Power, above volume
    assert abs(home["y"] - info["y"]) < 2 and home["x"] < info["x"]  # mirrored
    for key in ("rewind", "play", "pause", "stop", "fast_forward"):
        button = remote.get_by_test_id(f"remote-key-{key}")
        expect(button.locator("svg")).to_have_count(1)
        assert button.inner_text().strip() == ""  # an icon, not an emoji
