"""Alerts in the browser: My account > Alerts (each person's choices),
Admin > Alerts (what the home watches), and the garage card's light,
remote lockout and obstruction warning."""

import json

from playwright.sync_api import expect

from app.models import AlertPrefs, AlertSettings, Device
from tests import test_ui as _ui


def test_ui_my_alerts_and_admin_alerts(open_page, db, owner):
    page = open_page()
    _ui.ui_login(page, owner)
    mine = _ui.go_settings(page, "account").get_by_test_id("my-alerts")
    mine.get_by_test_id("alert-kind-garage_open").check()
    expect(page.get_by_test_id("status")).to_contain_text("Alerts saved")
    expect(mine.get_by_test_id("alert-email")).to_be_disabled()  # no email server yet
    db.expire_all()
    prefs = db.get(AlertPrefs, (owner.id, owner.home_id))
    assert json.loads(prefs.kinds) == ["garage_open"]
    panel = _ui.go_settings(page, "admin").get_by_test_id("alert-settings")
    panel.get_by_test_id("alert-auto-close").fill("20")
    panel.get_by_test_id("alert-offline-tv").check()
    panel.get_by_test_id("alert-camera-labels").fill("person, car")
    panel.get_by_test_id("alert-settings-save").click()
    expect(page.get_by_test_id("status")).to_contain_text("Alert settings saved")
    db.expire_all()
    row = db.get(AlertSettings, owner.home_id)
    assert row.auto_close_minutes == 20 and "tv" in row.offline_types
    assert row.frigate_labels == "person,car"


def test_ui_garage_light_lock_and_obstruction(open_page, db, owner, make_device):
    door = db.get(
        Device, make_device(owner.home_id, device_type="garage_door", name="Garage")
    )
    door.state = json.dumps(
        {"door": "closed", "light": False, "locked": False, "obstruction": True}
    )
    db.commit()
    page = open_page()
    _ui.ui_login(page, owner)
    card = _ui.card(page, "Garage")
    expect(card.get_by_test_id("garage-obstruction")).to_have_text(
        "Something is in the way"
    )
    card.get_by_test_id("garage-light").click()
    expect(_ui.card(page, "Garage").get_by_test_id("garage-light")).to_have_text(
        "Light on"
    )
    _ui.card(page, "Garage").get_by_test_id("garage-lock").click()
    expect(_ui.card(page, "Garage").get_by_test_id("garage-lock")).to_have_text(
        "Remotes locked"
    )


def test_ui_the_bell(open_page, db, owner):
    from app import alerts

    page = open_page()
    _ui.ui_login(page, owner)
    bell = page.get_by_test_id("alert-bell")
    expect(bell).to_be_visible()
    order = page.locator("header.topbar > *").evaluate_all(
        "nodes => nodes.filter(n => !n.hidden).map(n => n.dataset.testid || n.className)"
    )
    assert order.index("alert-bell-slot") < order.index("home-badge-slot")
    nav = page.get_by_test_id("logout").bounding_box()
    box = bell.bounding_box()
    home = page.get_by_test_id("home-badge").bounding_box()
    assert nav["x"] < box["x"] < home["x"]  # between Log out and the home's icon
    expect(page.get_by_test_id("alert-bell-count")).to_be_hidden()
    alerts.remember(
        db, owner.home_id, "garage_open", "Garage is open", "Open 15 minutes."
    )
    alerts.remember(db, owner.home_id, "offline", "Hall is offline", "Not answering.")
    page.evaluate("window.alertBell.check(window.smartHomeApp.home.id)")
    count = page.get_by_test_id("alert-bell-count")
    expect(count).to_have_text("2")
    color = count.evaluate("n => getComputedStyle(n).backgroundColor")
    assert color == "rgb(217, 48, 37)"  # red, with white numbers
    bell.click()
    expect(page.get_by_test_id("alert-bell-item")).to_have_count(2)
    expect(page.get_by_test_id("alert-bell-item").first).to_contain_text(
        "Hall is offline"
    )
    expect(count).to_be_hidden()
    page.keyboard.press("Escape")
    expect(page.get_by_test_id("alert-bell-menu")).to_be_hidden()
