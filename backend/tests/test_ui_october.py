"""Browser tests for: remember this device, approved devices (My account and
Admin), login times, verbose logging, the thermostat tile order, offline
tiles drawn off, and each user's room order with the Thermostats room."""

import json
import time

from playwright.sync_api import expect

from app.models import Device, TrustedDevice
from app.safety import apply_recommended
from tests import test_thermostat_tile as _tile
from tests import test_ui as _ui

card, ui_login, go_settings = _ui.card, _ui.ui_login, _ui.go_settings


def test_ui_remember_this_device(open_page, db, owner):
    page = open_page()
    page.get_by_test_id("login-remember-device").check()
    ui_login(page, owner)
    assert db.query(TrustedDevice).count() == 1
    page.get_by_test_id("logout").click()
    expect(page.get_by_test_id("login-page")).to_be_visible()
    expect(page.get_by_test_id("login-device-known")).to_be_visible()
    # Password only on this browser.
    page.get_by_test_id("login-email").fill(owner.email)
    page.get_by_test_id("login-password").fill(owner.password)
    page.get_by_test_id("login-code").fill("")
    page.get_by_test_id("login-submit").click()
    expect(page.get_by_test_id("app-shell")).to_be_visible()

    # My account > Approved devices: this one, removable.
    go_settings(page, "account")
    page.get_by_test_id("account-tab-approved").click()
    row = page.get_by_test_id("trusted-device")
    expect(row).to_have_count(1)
    expect(row).to_contain_text("(this device)")
    row.get_by_test_id("trusted-device-forget").click()
    expect(page.get_by_test_id("devices-none")).to_be_visible()
    db.expire_all()
    assert db.query(TrustedDevice).count() == 0


def test_ui_admin_login_times_and_devices(open_page, db, owner, make_user):
    member = make_user(owner.home_id, role="member")
    other = open_page()
    other.get_by_test_id("login-remember-device").check()
    ui_login(other, member)
    page = open_page()
    ui_login(page, owner, owner.totp.at(time.time() + 30))
    expect(page.get_by_test_id("login-keep-label")).to_have_count(1)
    go_settings(page, "admin")
    times = page.get_by_test_id("login-times")
    expect(times.get_by_test_id("login-time-keep_logged_in_days")).to_have_value("30")
    expect(times.get_by_test_id("login-time-remember_me_days")).to_have_value("365")
    expect(times.get_by_test_id("login-time-remember_device_days")).to_have_value("0")
    times.get_by_test_id("login-time-keep_logged_in_days").fill("14")
    times.get_by_test_id("login-times-save").click()
    expect(page.get_by_test_id("status")).to_contain_text("Login times saved")
    devices = page.get_by_test_id("admin-devices").get_by_test_id("trusted-device")
    expect(devices).to_have_count(1)
    expect(devices).to_contain_text(member.email)
    # The login page says the new time.
    page.get_by_test_id("logout").click()
    expect(page.get_by_test_id("login-keep-label")).to_have_text(
        "Keep me logged in for 14 days"
    )


def test_ui_verbose_logging(open_page, owner):
    page = open_page()
    ui_login(page, owner)
    go_settings(page, "activity")
    toggle = page.get_by_test_id("verbose-toggle")
    expect(toggle).not_to_be_checked()
    toggle.check()
    expect(page.get_by_test_id("status")).to_contain_text("Verbose logging turned on")
    page.get_by_test_id("activity-refresh").click()
    details = page.get_by_test_id("activity-details").first
    expect(details).to_contain_text("method: PUT")
    expect(details).to_contain_text("status: 200")


def test_ui_thermostat_fan_hold_schedule_order(open_page, db, owner, make_device):
    hall = make_device(owner.home_id, device_type="thermostat", name="Hallway")
    db.get(Device, hall).integration = "cync"
    db.commit()
    apply_recommended(db, owner.home_id, None, None)
    page = open_page()
    ui_login(page, owner)
    tile = _tile.show(page, db, hall, _tile.report(fan="auto", hold="schedule"))
    order = tile.evaluate(
        """t => ['thermo-mode', 'thermo-fan', 'thermo-hold', 'thermo-schedule-open',
        'thermo-info-open'].map(id => [...t.querySelectorAll('[data-testid]')]
        .findIndex(n => n.dataset.testid === id))"""
    )
    assert -1 not in order and order == sorted(order), order
    # The schedule button is inside the controls, right under the hold button.
    controls = tile.get_by_test_id("thermo-controls")
    expect(controls.get_by_test_id("thermo-schedule-open")).to_have_count(1)


def test_ui_offline_device_is_drawn_off(open_page, db, owner, make_device):
    lamp = make_device(owner.home_id, name="Porch")
    device = db.get(Device, lamp)
    device.state = json.dumps({"on": True, "brightness": 80})
    device.online = False
    db.commit()
    page = open_page()
    ui_login(page, owner)
    tile = card(page, "Porch")
    expect(tile).to_have_class("device-card offline")  # off, and dimmed
    expect(tile.get_by_test_id("power-toggle")).not_to_have_class("toggle on")
    db.expire_all()
    db.get(Device, lamp).online = True
    db.commit()
    page.reload()
    expect(card(page, "Porch")).to_have_class("device-card on")  # its real state


def test_ui_room_order_per_user(open_page, db, owner, make_user, make_device):
    member = make_user(owner.home_id, role="member")
    for name, room, kind in (
        ("Counter", "Kitchen", "light"),
        ("Bed lamp", "Bedroom", "light"),
        ("Hallway", "Hall", "thermostat"),
    ):
        device = db.get(Device, make_device(owner.home_id, device_type=kind, name=name))
        device.room = room
    db.commit()
    page = open_page()
    ui_login(page, owner)
    rooms = page.get_by_test_id("room")
    # Thermostats get their own room, at the top by default.
    expect(rooms.first).to_have_attribute("data-room", "Thermostats")
    expect(rooms.first).to_contain_text("Hallway")
    names = [r.get_attribute("data-room") for r in rooms.all()]
    assert names == ["Thermostats", "Bedroom", "Kitchen"], names

    page.get_by_test_id("layout-open").click()
    panel = page.get_by_test_id("layout-panel")
    panel.locator('[data-room="Thermostats"]').get_by_test_id("layout-down").click()
    panel.locator('[data-room="Kitchen"]').get_by_test_id("layout-up").click()
    panel.locator('[data-room="Kitchen"]').get_by_test_id("layout-up").click()
    panel.get_by_test_id("layout-save").click()
    expect(page.get_by_test_id("status")).to_contain_text("Room order saved")
    expect(rooms.first).to_have_attribute("data-room", "Kitchen")
    page.reload()
    expect(page.get_by_test_id("room").first).to_have_attribute("data-room", "Kitchen")
    names = [r.get_attribute("data-room") for r in page.get_by_test_id("room").all()]
    assert names == ["Kitchen", "Bedroom", "Thermostats"], names

    # Someone else still has the default order.
    theirs = open_page()
    ui_login(theirs, member)
    expect(theirs.get_by_test_id("room").first).to_have_attribute(
        "data-room", "Thermostats"
    )

    # Reset puts Thermostats back on top.
    page.get_by_test_id("layout-open").click()
    page.get_by_test_id("layout-reset").click()
    expect(page.get_by_test_id("room").first).to_have_attribute(
        "data-room", "Thermostats"
    )


def test_ui_guest_access(open_page, db, owner, make_user, make_device):
    apply_recommended(db, owner.home_id, None, None)
    make_device(owner.home_id, name="Lamp")
    make_device(owner.home_id, device_type="thermostat", name="Hall")
    make_device(owner.home_id, device_type="thermostat", name="Den")
    make_device(owner.home_id, device_type="tv", name="TV")
    guest = make_user(owner.home_id, role="member")
    admin = open_page()
    ui_login(admin, owner)
    go_settings(admin, "members")
    row = admin.locator(f'[data-testid="member-row"][data-user-id="{guest.id}"]')
    row.get_by_test_id("member-role").select_option("guest")
    expect(admin.get_by_test_id("status")).to_contain_text("is now guest")
    row = admin.locator(f'[data-testid="member-row"][data-user-id="{guest.id}"]')
    row.get_by_test_id("guest-access-open").click()
    dialog = admin.get_by_test_id("guest-access")
    dialog.get_by_test_id("guest-light_power").check()
    dialog.get_by_test_id("guest-show_blocked").check()
    hall = db.query(Device).filter_by(name="Hall").one().id
    dialog.locator(f'[data-testid="guest-thermostat"][data-device-id="{hall}"]').check()
    dialog.get_by_test_id("guest-access-save").click()
    expect(admin.get_by_test_id("status")).to_contain_text("Saved what")

    page = open_page()
    ui_login(page, guest)
    lamp = card(page, "Lamp")
    expect(lamp.get_by_test_id("power-toggle")).to_be_enabled()
    expect(lamp.get_by_test_id("light-settings-open")).to_have_count(0)
    expect(card(page, "Hall").get_by_test_id("thermo-schedule-open")).to_have_count(0)
    for blocked in ("Den", "TV"):
        expect(card(page, blocked).get_by_test_id("device-blocked")).to_be_visible()
    lamp.get_by_test_id("power-toggle").click()
    expect(card(page, "Lamp")).to_have_class("device-card on")
    # Settings: only their own account.
    page.get_by_test_id("nav-settings").click()
    links = page.get_by_test_id("settings-menu").locator("a")
    expect(links).to_have_count(1)
