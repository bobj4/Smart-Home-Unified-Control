"""Web app behaviour, tested in a real browser (Playwright + Chromium).

Written by the reviewer (UI and settings phase). Do not edit, skip, mark or
delete these tests. If one looks wrong, stop and report the test name and its
full failure output instead of changing it.

The tests start the app on a random local port in a background thread; never
start a server yourself. Elements are found by their data-testid attribute
(page.get_by_test_id), so markup and styling are free to change. The full
list of required data-testid values is in docs/PLAN-UI.md.

Browser: PLAYWRIGHT_CHROMIUM_EXECUTABLE if set, otherwise the Chromium that
`python -m playwright install chromium` downloaded.
"""

import json
import re
import time
import urllib.parse
import uuid
from pathlib import Path

import pyotp
from playwright.sync_api import expect

from app.auth import verify_password
from app.models import Device, DeviceSafetyLimits, HomeMembership, User

BACKEND_DIR = Path(__file__).resolve().parents[1]
WEB_DIR = BACKEND_DIR.parent / "web"
API = "/api/v1"


# ------------------------------------------------------------ static checks


def web_scripts():
    return sorted((WEB_DIR / "js").glob("*.js"))


def test_ui_static_scripts_are_safe_and_small():
    """No HTML injection, no browser storage, no eval; files stay under 300 lines."""
    assert web_scripts()
    banned = re.compile(
        r"innerHTML|outerHTML|insertAdjacentHTML|document\.write|"
        r"localStorage|sessionStorage|\beval\(|new Function\(|"
        r"\balert\(|\bconfirm\(|\bprompt\("
    )
    for path in web_scripts():
        text = path.read_text(encoding="utf-8")
        found = banned.search(text)
        assert found is None, f"{path.name}: {found.group(0) if found else ''}"
        assert len(text.splitlines()) <= 300, f"{path.name} is over 300 lines"


def test_ui_static_index_loads_only_served_files(client):
    html = (WEB_DIR / "public" / "index.html").read_text(encoding="utf-8")
    assert not re.search(r"\son[a-z]+\s*=", html, re.I), "inline event handler"
    assert not re.search(r"<script(?![^>]*\bsrc=)[^>]*>", html), "inline script"
    assert not re.search(r"\sstyle\s*=", html), "inline style"
    scripts = re.findall(r'<script[^>]*\bsrc="([^"]+)"', html)
    styles = re.findall(r'<link[^>]*rel="stylesheet"[^>]*href="([^"]+)"', html)
    assert "/js/api.js" in scripts and len(scripts) >= 2
    for url in scripts + styles:
        r = client.get(url)
        assert r.status_code == 200, url
    for path in web_scripts():
        assert f"/js/{path.name}" in scripts, f"{path.name} is not loaded by index.html"
    assert client.get("/js/..%2Fpublic%2Findex.html").status_code == 404
    assert client.get("/js/missing.js").status_code == 404


def next_step_code(secret):
    return pyotp.TOTP(secret).at(int(time.time()) + 30)


def ui_login(page, user, code=None):
    page.get_by_test_id("login-email").fill(user.email)
    page.get_by_test_id("login-password").fill(user.password)
    page.get_by_test_id("login-code").fill(code or user.totp.now())
    page.get_by_test_id("login-submit").click()
    expect(page.get_by_test_id("app-shell")).to_be_visible()


def go_settings(page, section):
    """Open Settings, then one category from the menu."""
    page.get_by_test_id("nav-settings").click()
    expect(page.get_by_test_id("view-settings")).to_be_visible()
    # Users lives inside the Admin category.
    menu_entry = "admin" if section == "members" else section
    page.get_by_test_id("settings-menu").get_by_test_id(
        f"settings-nav-{menu_entry}"
    ).click()
    panel = page.get_by_test_id(f"settings-{section}")
    expect(panel).to_be_visible()
    return panel


def device_state(db, device_id):
    db.expire_all()
    return json.loads(db.get(Device, device_id).state or "{}")


def set_state(db, device_id, **values):
    device = db.get(Device, device_id)
    device.state = json.dumps(values)
    db.commit()


def recommended_limits(db, home_id):
    from app.safety import apply_recommended

    apply_recommended(db, home_id, None, None)


def api_client(new_client, user, code=None):
    c = new_client()
    body = {"email": user.email, "password": user.password}
    code = code or user.totp.now()
    body["recovery_code" if len(code) == 8 else "totp_code"] = code
    assert c.post(f"{API}/auth/login", json=body).status_code == 200
    return c


# ------------------------------------------------------------ U8: shell


def test_ui_shell_login_and_logout(open_page, owner):
    page = open_page()
    expect(page.get_by_test_id("login-form")).to_be_visible()
    expect(page.get_by_test_id("app-shell")).to_be_hidden()

    page.get_by_test_id("login-email").fill(owner.email)
    page.get_by_test_id("login-password").fill("wrong password here")
    page.get_by_test_id("login-code").fill("000000")
    page.get_by_test_id("login-submit").click()
    expect(page.get_by_test_id("login-error")).not_to_be_empty()
    expect(page.get_by_test_id("app-shell")).to_be_hidden()

    ui_login(page, owner)
    expect(page.get_by_test_id("home-name")).to_have_text("Home A")
    expect(page.get_by_test_id("view-devices")).to_be_visible()
    expect(page.get_by_test_id("login-password")).to_have_value("")
    page.reload()
    expect(page.get_by_test_id("app-shell")).to_be_visible()

    page.get_by_test_id("logout").click()
    expect(page.get_by_test_id("login-form")).to_be_visible()
    page.reload()
    expect(page.get_by_test_id("login-form")).to_be_visible()
    expect(page.get_by_test_id("app-shell")).to_be_hidden()


def test_ui_shell_recovery_code_login(open_page, owner):
    page = open_page()
    ui_login(page, owner, code=owner.recovery_codes[0])
    expect(page.get_by_test_id("home-name")).to_have_text("Home A")


def test_ui_shell_navigation_and_deep_link(open_page, owner):
    page = open_page()
    ui_login(page, owner)
    page.get_by_test_id("nav-settings").click()
    expect(page.get_by_test_id("view-settings")).to_be_visible()
    expect(page.get_by_test_id("view-devices")).to_be_hidden()
    assert page.url.endswith("#/settings")
    page.reload()
    expect(page.get_by_test_id("view-settings")).to_be_visible()
    page.get_by_test_id("nav-devices").click()
    expect(page.get_by_test_id("view-devices")).to_be_visible()
    assert page.url.endswith("#/devices")


def test_ui_shell_home_switcher(open_page, db, owner, make_home, make_device):
    make_device(owner.home_id, name="Lamp in A")
    home_b = make_home("Home B")
    make_device(home_b, name="Lamp in B")
    db.add(
        HomeMembership(
            id=str(uuid.uuid4()), user_id=owner.id, home_id=home_b, role="member"
        )
    )
    db.commit()
    page = open_page()
    ui_login(page, owner)
    select = page.get_by_test_id("home-select")
    expect(select).to_be_visible()
    expect(select.locator("option")).to_have_count(2)
    expect(page.get_by_test_id("device-card")).to_have_count(1)
    select.select_option(label="Home B")
    expect(page.get_by_test_id("home-name")).to_have_text("Home B")
    expect(page.get_by_test_id("device-card")).to_have_text(re.compile("Lamp in B"))


def test_ui_shell_single_home_has_no_switcher(open_page, owner):
    page = open_page()
    ui_login(page, owner)
    expect(page.get_by_test_id("home-select")).to_be_hidden()


def test_ui_shell_fits_a_phone_screen(open_page, db, owner, make_device):
    recommended_limits(db, owner.home_id)
    for device_type in (
        "light",
        "thermostat",
        "water_heater",
        "tv",
        "sensor",
        "camera",
    ):
        make_device(
            owner.home_id,
            device_type=device_type,
            name=f"A long device name {device_type}",
        )
    page = open_page(width=390, height=844)
    ui_login(page, owner)

    def no_sideways_scroll(where):
        overflow = page.evaluate(
            "document.documentElement.scrollWidth - document.documentElement.clientWidth"
        )
        assert overflow <= 0, f"{where} scrolls sideways by {overflow}px"

    for view in ("devices", "settings"):
        page.get_by_test_id(f"nav-{view}").click()
        expect(page.get_by_test_id(f"view-{view}")).to_be_visible()
        no_sideways_scroll(f"{view} view")
    page.get_by_test_id("nav-devices").click()
    card(page, "A long device name tv").get_by_test_id("tv-remote-open").click()
    remote = page.get_by_test_id("tv-remote")
    expect(remote).to_be_visible()
    no_sideways_scroll("TV remote")
    box = remote.bounding_box()
    assert box and box["x"] >= 0 and box["x"] + box["width"] <= 390, box


# ------------------------------------------------------------ U8: devices


def card(page, name):
    return page.get_by_test_id("device-card").filter(has_text=name)


def test_ui_devices_grouped_by_room(open_page, db, owner, make_device):
    kitchen = make_device(owner.home_id, name="Counter light")
    db.get(Device, kitchen).room = "Kitchen"
    db.commit()
    make_device(owner.home_id, name="Bench light")  # room "Lab"
    page = open_page()
    ui_login(page, owner)
    rooms = page.get_by_test_id("room")
    expect(rooms).to_have_count(2)
    kitchen_room = page.locator('[data-testid="room"][data-room="Kitchen"]')
    expect(kitchen_room).to_contain_text("Kitchen")
    expect(kitchen_room.get_by_test_id("device-card")).to_have_text(
        re.compile("Counter light")
    )
    expect(page.locator('[data-testid="room"][data-room="Lab"]')).to_contain_text(
        "Bench light"
    )


def test_ui_devices_empty_home_says_so(open_page, owner):
    page = open_page()
    ui_login(page, owner)
    expect(page.get_by_test_id("devices-empty")).to_be_visible()


def test_ui_devices_light_toggle(open_page, db, owner, make_device):
    lamp = make_device(owner.home_id, name="Reading lamp")
    page = open_page()
    ui_login(page, owner)
    c = card(page, "Reading lamp")
    expect(c).to_have_attribute("data-device-type", "light")
    toggle = c.get_by_test_id("power-toggle")
    expect(toggle).to_have_attribute("aria-pressed", "false")
    toggle.click()
    expect(card(page, "Reading lamp").get_by_test_id("power-toggle")).to_have_attribute(
        "aria-pressed", "true"
    )
    assert device_state(db, lamp).get("on") is True
    card(page, "Reading lamp").get_by_test_id("power-toggle").click()
    expect(card(page, "Reading lamp").get_by_test_id("power-toggle")).to_have_attribute(
        "aria-pressed", "false"
    )
    assert device_state(db, lamp).get("on") is False


def test_ui_devices_member_controls_devices(
    open_page, db, owner, make_user, make_device
):
    lamp = make_device(owner.home_id, name="Hall lamp")
    member = make_user(owner.home_id, role="member")
    page = open_page()
    ui_login(page, member)
    card(page, "Hall lamp").get_by_test_id("power-toggle").click()
    expect(card(page, "Hall lamp").get_by_test_id("power-toggle")).to_have_attribute(
        "aria-pressed", "true"
    )
    assert device_state(db, lamp).get("on") is True


def test_ui_devices_thermostat_dial(open_page, db, owner, make_device):
    recommended_limits(db, owner.home_id)
    thermostat = make_device(
        owner.home_id, device_type="thermostat", name="Hall thermostat"
    )
    set_state(db, thermostat, target_temperature=68, unit="F")
    page = open_page()
    ui_login(page, owner)
    c = card(page, "Hall thermostat")
    expect(c.get_by_test_id("temp-gauge")).to_be_visible()
    assert (
        c.get_by_test_id("temp-gauge").evaluate("e => e.tagName.toLowerCase()") == "svg"
    )
    expect(c.get_by_test_id("target-temp")).to_have_text(re.compile(r"68\s*°\s*F"))
    expect(c.get_by_test_id("temp-limits")).to_have_text(re.compile(r"60.*80"))

    c.get_by_test_id("temp-up").click()
    expect(card(page, "Hall thermostat").get_by_test_id("target-temp")).to_have_text(
        re.compile(r"69")
    )
    assert device_state(db, thermostat)["target_temperature"] == 69
    card(page, "Hall thermostat").get_by_test_id("temp-down").click()
    expect(card(page, "Hall thermostat").get_by_test_id("target-temp")).to_have_text(
        re.compile(r"68")
    )
    card(page, "Hall thermostat").get_by_test_id("temp-down").click()
    expect(card(page, "Hall thermostat").get_by_test_id("target-temp")).to_have_text(
        re.compile(r"67")
    )
    assert device_state(db, thermostat)["target_temperature"] == 67


def test_ui_devices_dial_stops_at_limits(open_page, db, owner, make_device):
    recommended_limits(db, owner.home_id)
    heater = make_device(owner.home_id, device_type="water_heater", name="Water heater")
    set_state(db, heater, target_temperature=120, unit="F")
    cold = make_device(owner.home_id, device_type="thermostat", name="Cold thermostat")
    set_state(db, cold, target_temperature=60, unit="F")
    page = open_page()
    ui_login(page, owner)
    expect(card(page, "Water heater").get_by_test_id("temp-up")).to_be_disabled()
    expect(card(page, "Water heater").get_by_test_id("temp-down")).to_be_enabled()
    expect(card(page, "Cold thermostat").get_by_test_id("temp-down")).to_be_disabled()
    expect(card(page, "Cold thermostat").get_by_test_id("temp-up")).to_be_enabled()


def test_ui_devices_temperature_locked_without_limits(
    open_page, db, owner, make_device
):
    make_device(owner.home_id, device_type="water_heater", name="Water heater")
    page = open_page()
    ui_login(page, owner)
    c = card(page, "Water heater")
    expect(c.get_by_test_id("limits-missing")).to_be_visible()
    expect(c.get_by_test_id("temp-up")).to_be_disabled()
    expect(c.get_by_test_id("temp-down")).to_be_disabled()


def test_ui_devices_refused_command_shows_error(open_page, db, owner, make_device):
    recommended_limits(db, owner.home_id)
    thermostat = make_device(
        owner.home_id, device_type="thermostat", name="Den thermostat"
    )
    set_state(db, thermostat, target_temperature=70, unit="F")
    page = open_page()
    ui_login(page, owner)
    expect(card(page, "Den thermostat").get_by_test_id("temp-up")).to_be_enabled()
    # The owner tightens the limits in another window; this page has not reloaded.
    limits = (
        db.query(DeviceSafetyLimits)
        .filter_by(home_id=owner.home_id, device_type="thermostat")
        .one()
    )
    limits.max_temperature = 70
    db.commit()
    card(page, "Den thermostat").get_by_test_id("temp-up").click()
    expect(page.get_by_test_id("status")).to_have_attribute("data-kind", "error")
    expect(page.get_by_test_id("status")).not_to_be_empty()
    assert device_state(db, thermostat)["target_temperature"] == 70


def test_ui_devices_offline_device_is_disabled(open_page, db, owner, make_device):
    lamp = make_device(owner.home_id, name="Porch light")
    db.get(Device, lamp).online = False
    db.commit()
    page = open_page()
    ui_login(page, owner)
    c = card(page, "Porch light")
    expect(c).to_have_attribute("data-online", "false")
    expect(c.get_by_test_id("power-toggle")).to_be_disabled()


def test_ui_devices_device_names_are_text_not_html(open_page, owner, make_device):
    make_device(owner.home_id, name='<img src=x onerror="window.pwned=1">')
    page = open_page()
    ui_login(page, owner)
    expect(page.get_by_test_id("device-card")).to_contain_text("<img src=x")
    assert page.evaluate("window.pwned === undefined")


# ------------------------------------------------------------ U8: TV remote


def open_remote(page, name):
    card(page, name).get_by_test_id("tv-remote-open").click()
    remote = page.get_by_test_id("tv-remote")
    expect(remote).to_be_visible()
    return remote


def test_ui_tv_remote_full_control(open_page, db, owner, make_device):
    tv = make_device(owner.home_id, device_type="tv", name="Living room TV")
    page = open_page()
    ui_login(page, owner)
    remote = open_remote(page, "Living room TV")
    expect(remote).to_contain_text("Living room TV")

    remote.get_by_test_id("remote-power").click()
    expect(remote.get_by_test_id("remote-volume")).to_have_text(re.compile(r"\b10\b"))
    assert device_state(db, tv)["on"] is True

    remote.get_by_test_id("remote-volume-up").click()
    expect(remote.get_by_test_id("remote-volume")).to_have_text(re.compile(r"\b11\b"))
    remote.get_by_test_id("remote-volume-up").click()
    expect(remote.get_by_test_id("remote-volume")).to_have_text(re.compile(r"\b12\b"))
    remote.get_by_test_id("remote-volume-down").click()
    expect(remote.get_by_test_id("remote-volume")).to_have_text(re.compile(r"\b11\b"))
    remote.get_by_test_id("remote-mute").click()
    expect(remote.get_by_test_id("remote-volume")).to_have_text(
        re.compile("muted", re.I)
    )
    assert device_state(db, tv)["muted"] is True
    remote.get_by_test_id("remote-mute").click()
    expect(remote.get_by_test_id("remote-volume")).to_have_text(re.compile(r"\b11\b"))

    remote.get_by_test_id("remote-channel-up").click()
    expect(remote.get_by_test_id("remote-channel")).to_have_text(re.compile(r"\b2\b"))
    remote.get_by_test_id("remote-channel-down").click()
    expect(remote.get_by_test_id("remote-channel")).to_have_text(re.compile(r"\b1\b"))
    remote.get_by_test_id("remote-channel-input").fill("505")
    remote.get_by_test_id("remote-channel-go").click()
    expect(remote.get_by_test_id("remote-channel")).to_have_text(re.compile(r"\b505\b"))
    assert device_state(db, tv)["channel"] == 505

    remote.get_by_test_id("remote-input").select_option("hdmi2")
    expect(remote.get_by_test_id("remote-screen")).to_contain_text("HDMI 2")
    assert device_state(db, tv)["input"] == "hdmi2"
    remote.get_by_test_id("remote-app-netflix").click()
    expect(remote.get_by_test_id("remote-screen")).to_contain_text("Netflix")
    assert device_state(db, tv)["app"] == "netflix"

    for key in (
        "up",
        "down",
        "left",
        "right",
        "select",
        "back",
        "menu",
        "info",
        "guide",
        "play",
        "pause",
        "stop",
        "rewind",
        "fast_forward",
        "home",
    ):
        remote.get_by_test_id(f"remote-key-{key}").click()
        expect(page.get_by_test_id("status")).not_to_have_attribute(
            "data-kind", "pending"
        )
        assert device_state(db, tv)["last_key"] == key, key
    assert device_state(db, tv)["app"] is None  # Home leaves the app

    remote.get_by_test_id("remote-close").click()
    expect(page.get_by_test_id("tv-remote")).to_be_hidden()
    expect(
        card(page, "Living room TV").get_by_test_id("power-toggle")
    ).to_have_attribute("aria-pressed", "true")


def test_ui_tv_remote_only_power_works_while_off(open_page, db, owner, make_device):
    make_device(owner.home_id, device_type="tv", name="Bedroom TV")
    page = open_page()
    ui_login(page, owner)
    remote = open_remote(page, "Bedroom TV")
    expect(remote.get_by_test_id("remote-power")).to_be_enabled()
    expect(remote.get_by_test_id("remote-close")).to_be_enabled()
    for testid in (
        "remote-volume-up",
        "remote-volume-down",
        "remote-mute",
        "remote-channel-up",
        "remote-channel-down",
        "remote-channel-go",
        "remote-input",
        "remote-key-up",
        "remote-key-select",
        "remote-app-youtube",
    ):
        expect(remote.get_by_test_id(testid)).to_be_disabled()
    page.keyboard.press("Escape")
    expect(page.get_by_test_id("tv-remote")).to_be_hidden()


def test_ui_tv_remote_member_can_use_it(open_page, db, owner, make_user, make_device):
    tv = make_device(owner.home_id, device_type="tv", name="Den TV")
    set_state(db, tv, on=True)
    member = make_user(owner.home_id, role="member")
    page = open_page()
    ui_login(page, member)
    remote = open_remote(page, "Den TV")
    remote.get_by_test_id("remote-volume-up").click()
    expect(remote.get_by_test_id("remote-volume")).to_have_text(re.compile(r"\b11\b"))
    assert device_state(db, tv)["volume"] == 11


# ------------------------------------------- U9: settings menu and home settings

SETTINGS_SECTIONS = (
    "account",
    "admin",  # Users is inside Admin, which comes right after My account
    "devices",
    "integrations",
    "safety",
    "activity",
)


def test_ui_settings_menu_shows_one_category_at_a_time(open_page, owner):
    page = open_page()
    ui_login(page, owner)
    page.get_by_test_id("nav-settings").click()
    menu = page.get_by_test_id("settings-menu")
    expect(menu).to_be_visible()
    for section in SETTINGS_SECTIONS:
        expect(menu.get_by_test_id(f"settings-nav-{section}")).to_be_visible()
    expect(
        page.get_by_test_id("settings-account")
    ).to_be_visible()  # the first category
    expect(menu.get_by_test_id("settings-nav-account")).to_have_attribute(
        "aria-current", "page"
    )

    menu.get_by_test_id("settings-nav-admin").click()
    expect(page.get_by_test_id("settings-members")).to_be_visible()  # Users
    for other in SETTINGS_SECTIONS:
        if other != "admin":
            expect(page.get_by_test_id(f"settings-{other}")).to_be_hidden()
    expect(menu.get_by_test_id("settings-nav-admin")).to_have_attribute(
        "aria-current", "page"
    )
    expect(menu.get_by_test_id("settings-nav-account")).not_to_have_attribute(
        "aria-current", "page"
    )
    assert page.url.endswith("#/settings/admin")
    labels = menu.locator("a").all_inner_texts()
    assert labels[:2] == ["My account", "Admin"]
    page.reload()
    expect(page.get_by_test_id("settings-members")).to_be_visible()

    page.goto("/#/settings/safety")
    expect(page.get_by_test_id("settings-safety")).to_be_visible()
    expect(page.get_by_test_id("settings-members")).to_be_hidden()


def test_ui_settings_menu_hides_owner_only_categories(open_page, owner, make_user):
    admin = make_user(owner.home_id, role="operator")
    page = open_page()
    ui_login(page, admin)
    page.get_by_test_id("nav-settings").click()
    menu = page.get_by_test_id("settings-menu")
    for section in ("account", "devices", "integrations", "safety"):
        expect(menu.get_by_test_id(f"settings-nav-{section}")).to_be_visible()
    for section in ("admin", "activity"):  # admins only
        expect(menu.get_by_test_id(f"settings-nav-{section}")).to_have_count(0)
    page.goto("/#/settings/activity")
    expect(page.get_by_test_id("view-settings")).to_be_visible()
    expect(page.get_by_test_id("settings-activity")).to_have_count(0)


def test_ui_settings_fit_a_phone_screen(open_page, db, owner, make_user, make_device):
    recommended_limits(db, owner.home_id)
    make_user(owner.home_id, role="member")
    make_device(owner.home_id, name="A long device name for the phone test")
    page = open_page(width=390, height=844)
    ui_login(page, owner)
    for section in SETTINGS_SECTIONS:
        go_settings(page, section)
        overflow = page.evaluate(
            "document.documentElement.scrollWidth - document.documentElement.clientWidth"
        )
        assert overflow <= 0, f"settings {section} scrolls sideways by {overflow}px"


def integration_row(section, integration_id):
    return section.locator(
        f'[data-testid="integration-row"][data-integration="{integration_id}"]'
    )


def test_ui_integrations_owner_turns_brands_on_and_off(
    open_page, db, owner, make_device
):
    from app.models import HomeIntegration

    make_device(owner.home_id, name="Reading lamp")
    page = open_page()
    ui_login(page, owner)
    section = go_settings(page, "integrations")
    expect(section.get_by_test_id("integration-row")).to_have_count(5)
    for integration_id in (
        "simulated",
        "cync",
        "samsung_tv",
        "rheem_econet",
        "frigate",
    ):
        expect(integration_row(section, integration_id)).to_be_visible()
    expect(integration_row(section, "cync")).to_contain_text("GE Cync")
    expect(integration_row(section, "cync")).to_have_attribute("data-available", "true")
    expect(
        integration_row(section, "cync").get_by_test_id("integration-toggle")
    ).not_to_be_checked()
    demo = integration_row(section, "simulated").get_by_test_id("integration-toggle")
    expect(demo).to_be_checked()

    demo.uncheck()
    expect(page.get_by_test_id("status")).to_have_attribute("data-kind", "success")
    db.expire_all()
    row = (
        db.query(HomeIntegration)
        .filter_by(home_id=owner.home_id, integration="simulated")
        .one()
    )
    assert row.enabled is False

    page.get_by_test_id("nav-devices").click()  # demo devices were deleted
    expect(page.get_by_test_id("device-card")).to_have_count(0)

    section = go_settings(page, "integrations")
    integration_row(section, "rheem_econet").get_by_test_id(
        "integration-toggle"
    ).check()
    expect(page.get_by_test_id("status")).to_have_attribute("data-kind", "success")
    integration_row(section, "simulated").get_by_test_id("integration-toggle").check()
    expect(page.get_by_test_id("status")).to_have_attribute("data-kind", "success")
    page.get_by_test_id("nav-devices").click()
    expect(
        card(page, "Living room lamp").get_by_test_id("power-toggle")
    ).to_be_enabled()
    expect(page.get_by_test_id("device-card")).to_have_count(5)  # demo devices back
    db.expire_all()
    rheem = (
        db.query(HomeIntegration)
        .filter_by(home_id=owner.home_id, integration="rheem_econet")
        .one()
    )
    assert rheem.enabled is True


def test_ui_integrations_read_only_for_admin(open_page, owner, make_user):
    admin = make_user(owner.home_id, role="operator")
    page = open_page()
    ui_login(page, admin)
    section = go_settings(page, "integrations")
    expect(section.get_by_test_id("integration-row")).to_have_count(5)
    toggles = section.get_by_test_id("integration-toggle")
    for i in range(5):
        expect(toggles.nth(i)).to_be_disabled()


def limits_row(section, device_type):
    return section.locator(
        f'[data-testid="limits-row"][data-device-type="{device_type}"]'
    )


def db_limits(db, home_id):
    db.expire_all()
    return {
        r.device_type: r
        for r in db.query(DeviceSafetyLimits).filter_by(home_id=home_id)
    }


def test_ui_safety_owner_uses_recommended_then_edits(open_page, db, owner, make_device):
    make_device(owner.home_id, device_type="thermostat", name="Hall")
    make_device(owner.home_id, device_type="water_heater", name="Tank")
    page = open_page()
    ui_login(page, owner)
    section = go_settings(page, "safety")
    section.get_by_test_id("limits-recommended").click()
    row = limits_row(section, "thermostat")
    expect(row.get_by_test_id("limits-min")).to_have_value(re.compile(r"^60(\.0)?$"))
    expect(row.get_by_test_id("limits-max")).to_have_value(re.compile(r"^80(\.0)?$"))
    expect(row.get_by_test_id("limits-default")).to_have_value(
        re.compile(r"^68(\.0)?$")
    )
    expect(
        limits_row(section, "water_heater").get_by_test_id("limits-default")
    ).to_have_value(re.compile(r"^120(\.0)?$"))
    rows = db_limits(db, owner.home_id)
    assert (
        rows["water_heater"].min_temperature,
        rows["water_heater"].max_temperature,
    ) == (110, 120)

    row.get_by_test_id("limits-max").fill("78")
    row.get_by_test_id("limits-default").fill("70")
    row.get_by_test_id("limits-save").click()
    expect(page.get_by_test_id("status")).to_have_attribute("data-kind", "success")
    rows = db_limits(db, owner.home_id)
    assert (rows["thermostat"].max_temperature, rows["thermostat"].default_target) == (
        78,
        70,
    )

    row.get_by_test_id("limits-min").fill("85")
    row.get_by_test_id("limits-save").click()
    expect(page.get_by_test_id("status")).to_have_attribute("data-kind", "error")
    assert db_limits(db, owner.home_id)["thermostat"].min_temperature == 60


def test_ui_safety_owner_turns_control_off(open_page, db, owner, make_device):
    recommended_limits(db, owner.home_id)
    make_device(owner.home_id, device_type="water_heater", name="Tank")
    page = open_page()
    ui_login(page, owner)
    row = limits_row(go_settings(page, "safety"), "water_heater")
    expect(row.get_by_test_id("limits-enabled")).to_be_checked()
    row.get_by_test_id("limits-enabled").uncheck()
    row.get_by_test_id("limits-save").click()
    expect(page.get_by_test_id("status")).to_have_attribute("data-kind", "success")
    assert db_limits(db, owner.home_id)["water_heater"].enabled is False


def test_ui_safety_read_only_for_admin(open_page, db, owner, make_user, make_device):
    recommended_limits(db, owner.home_id)
    make_device(owner.home_id, device_type="thermostat", name="Hall")
    admin = make_user(owner.home_id, role="operator")
    page = open_page()
    ui_login(page, admin)
    section = go_settings(page, "safety")
    row = limits_row(section, "thermostat")
    expect(row.get_by_test_id("limits-max")).to_be_disabled()
    expect(section.get_by_test_id("limits-save")).to_have_count(0)
    expect(section.get_by_test_id("limits-recommended")).to_have_count(0)


def test_ui_device_edit_admin_renames_and_moves(
    open_page, db, owner, make_user, make_device
):
    lamp = make_device(owner.home_id, name="Lamp 1")
    admin = make_user(owner.home_id, role="admin")
    page = open_page()
    ui_login(page, admin)
    section = go_settings(page, "devices")
    row = section.locator(f'[data-testid="device-row"][data-device-id="{lamp}"]')
    row.get_by_test_id("device-name").fill("Desk lamp")
    row.get_by_test_id("device-room").fill("Office")
    section.get_by_test_id("device-save-bottom").click()
    expect(page.get_by_test_id("status")).to_have_attribute("data-kind", "success")
    db.expire_all()
    device = db.get(Device, lamp)
    assert (device.name, device.room) == ("Desk lamp", "Office")
    page.get_by_test_id("nav-devices").click()
    expect(page.locator('[data-testid="room"][data-room="Office"]')).to_contain_text(
        "Desk lamp"
    )


def test_ui_device_edit_read_only_for_member(open_page, owner, make_user, make_device):
    make_device(owner.home_id, name="Lamp 1")
    member = make_user(owner.home_id, role="member")
    page = open_page()
    ui_login(page, member)
    go_settings(page, "account")  # members only have My account
    for hidden in ("devices", "integrations", "safety", "members", "admin"):
        expect(page.get_by_test_id(f"settings-nav-{hidden}")).to_have_count(0)
    expect(page.get_by_test_id("nav-cameras")).to_be_hidden()


def test_ui_activity_owner_sees_events(open_page, owner, make_device):
    make_device(owner.home_id, name="Reading lamp")
    page = open_page()
    ui_login(page, owner)
    card(page, "Reading lamp").get_by_test_id("power-toggle").click()
    expect(card(page, "Reading lamp").get_by_test_id("power-toggle")).to_have_attribute(
        "aria-pressed", "true"
    )
    section = go_settings(page, "activity")
    section.get_by_test_id("activity-refresh").click()
    rows = section.get_by_test_id("activity-row")
    expect(rows.first).to_contain_text("device_command")
    expect(rows.filter(has_text="login_success").first).to_contain_text(owner.email)


def test_ui_activity_hidden_from_admin(open_page, owner, make_user):
    admin = make_user(owner.home_id, role="operator")
    page = open_page()
    ui_login(page, admin)
    go_settings(page, "safety")
    expect(page.get_by_test_id("settings-activity")).to_have_count(0)
    expect(page.get_by_test_id("settings-nav-activity")).to_have_count(0)


# ------------------------------------------- U10: account, members, enrollment


def expected_qr(otpauth_uri):
    import segno

    return segno.make(otpauth_uri, error="m").svg_data_uri(
        scale=4, border=2, dark="#000000", light="#ffffff"
    )


def assert_qr_shown(image, secret):
    """The QR image is the one the backend drew for this secret, and it
    actually rendered (the Content-Security-Policy allows data: images)."""
    expect(image).to_be_visible()
    src = image.get_attribute("src") or ""
    assert src.startswith("data:image/svg+xml"), src[:40]
    assert "<script" not in urllib.parse.unquote(src)
    assert image.evaluate("e => e.complete && e.naturalWidth > 0")
    box = image.bounding_box()
    assert box and box["width"] >= 120 and box["height"] >= 120, box


def test_ui_account_change_password(open_page, db, owner):
    page = open_page()
    ui_login(page, owner)
    section = go_settings(page, "account")
    new_password = "a fresh long passphrase 4"

    section.get_by_test_id("password-current").fill(owner.password)
    section.get_by_test_id("password-new").fill(new_password)
    section.get_by_test_id("password-confirm").fill(new_password + "x")
    section.get_by_test_id("password-save").click()
    expect(page.get_by_test_id("status")).to_have_attribute("data-kind", "error")

    section.get_by_test_id("password-current").fill("not my password")
    section.get_by_test_id("password-confirm").fill(new_password)
    section.get_by_test_id("password-save").click()
    expect(page.get_by_test_id("status")).to_have_attribute("data-kind", "error")
    db.expire_all()
    assert verify_password(owner.password, db.get(User, owner.id).hashed_password)

    section.get_by_test_id("password-current").fill(owner.password)
    section.get_by_test_id("password-save").click()
    expect(page.get_by_test_id("status")).to_have_attribute("data-kind", "success")
    db.expire_all()
    assert verify_password(new_password, db.get(User, owner.id).hashed_password)
    expect(section.get_by_test_id("password-new")).to_have_value("")


def test_ui_account_new_recovery_codes(open_page, new_client, owner):
    page = open_page()
    ui_login(page, owner)
    section = go_settings(page, "account")
    section.get_by_test_id("recovery-password").fill(owner.password)
    section.get_by_test_id("recovery-generate").click()
    codes_box = section.get_by_test_id("recovery-codes")
    expect(codes_box).to_be_visible()
    codes = re.findall(r"\b\d{8}\b", codes_box.inner_text())
    assert len(codes) == 10
    body = {"email": owner.email, "password": owner.password, "recovery_code": codes[3]}
    assert new_client().post(f"{API}/auth/login", json=body).status_code == 200


def test_ui_account_replace_authenticator(open_page, db, owner):
    page = open_page()
    ui_login(page, owner)
    section = go_settings(page, "account")
    section.get_by_test_id("totp-password").fill(owner.password)
    section.get_by_test_id("totp-start").click()
    secret_box = section.get_by_test_id("totp-secret")
    expect(secret_box).to_be_visible()
    secret = re.sub(r"\s", "", secret_box.inner_text())
    assert re.fullmatch(r"[A-Z2-7]{16,}", secret), secret
    qr = section.get_by_test_id("totp-qr")
    assert_qr_shown(qr, secret)
    uri = pyotp.TOTP(secret).provisioning_uri(name=owner.email, issuer_name="SmartHome")
    assert qr.get_attribute("src") == expected_qr(uri)
    section.get_by_test_id("totp-code").fill(pyotp.TOTP(secret).now())
    section.get_by_test_id("totp-confirm").click()
    expect(page.get_by_test_id("status")).to_have_attribute("data-kind", "success")
    db.expire_all()
    assert db.get(User, owner.id).totp_secret == secret


def test_ui_account_sessions(open_page, new_client, owner):
    other = api_client(new_client, owner, code=owner.recovery_codes[0])
    page = open_page()
    ui_login(page, owner)
    section = go_settings(page, "account")
    rows = section.get_by_test_id("session-row")
    expect(rows).to_have_count(2)
    current = section.locator('[data-testid="session-row"][data-current="true"]')
    expect(current).to_have_count(1)
    expect(current.get_by_test_id("session-end")).to_have_count(0)
    section.locator('[data-testid="session-row"][data-current="false"]').get_by_test_id(
        "session-end"
    ).click()
    expect(rows).to_have_count(1)
    assert other.get(f"{API}/account").status_code == 401

    third = api_client(new_client, owner, code=owner.recovery_codes[1])
    page.reload()
    section = go_settings(page, "account")
    expect(section.get_by_test_id("session-row")).to_have_count(2)
    section.get_by_test_id("sessions-end-others").click()
    expect(section.get_by_test_id("session-row")).to_have_count(1)
    assert third.get(f"{API}/account").status_code == 401


def member_row(section, user_id):
    return section.locator(f'[data-testid="member-row"][data-user-id="{user_id}"]')


def test_ui_members_owner_manages_roles(open_page, db, owner, make_user):
    member = make_user(owner.home_id, role="member")
    page = open_page()
    ui_login(page, owner)
    section = go_settings(page, "members")
    expect(section.get_by_test_id("member-row")).to_have_count(2)
    own = member_row(section, owner.id)
    expect(own).to_contain_text(owner.email)
    expect(own.get_by_test_id("member-remove")).to_have_count(0)
    expect(own.get_by_test_id("member-role")).to_have_count(0)

    row = member_row(section, member.id)
    row.get_by_test_id("member-role").select_option("admin")
    expect(page.get_by_test_id("status")).to_have_attribute("data-kind", "success")
    db.expire_all()
    assert db.query(HomeMembership).filter_by(user_id=member.id).one().role == "admin"

    row.get_by_test_id("member-remove").click()
    assert (
        db.query(HomeMembership).filter_by(user_id=member.id).count() == 1
    )  # asks first
    row.get_by_test_id("member-remove-confirm").click()
    expect(member_row(section, member.id)).to_have_count(0)
    db.expire_all()
    assert db.query(HomeMembership).filter_by(user_id=member.id).count() == 0


def test_ui_members_owner_invites_and_cancels(open_page, owner):
    page = open_page()
    ui_login(page, owner)
    section = go_settings(page, "members")
    section.get_by_test_id("invite-email").fill("guest@example.com")
    section.get_by_test_id("invite-name").fill("Guest")
    section.get_by_test_id("invite-role").select_option("member")
    section.get_by_test_id("invite-submit").click()
    code = section.get_by_test_id("invite-code")
    expect(code).to_have_text(re.compile(r"[A-Z2-9]{4}(-[A-Z2-9]{4}){3}"))
    pending = section.get_by_test_id("enrollment-row")
    expect(pending).to_have_count(1)
    expect(pending).to_contain_text("guest@example.com")
    pending.get_by_test_id("enrollment-cancel").click()
    expect(section.get_by_test_id("enrollment-row")).to_have_count(0)


def test_ui_members_read_only_for_member(open_page, owner, make_user):
    operator = make_user(owner.home_id, role="operator")  # only admins see Users
    page = open_page()
    ui_login(page, operator)
    go_settings(page, "devices")
    expect(page.get_by_test_id("settings-nav-admin")).to_have_count(0)
    expect(page.get_by_test_id("member-row")).to_have_count(0)


def make_code(new_client, owner, email, role="member"):
    c = api_client(new_client, owner)
    r = c.post(
        f"{API}/homes/{owner.home_id}/members/enrollments",
        json={"email": email, "role": role},
        headers={"X-CSRF-Token": c.cookies.get("csrf_token")},
    )
    assert r.status_code == 201, r.text
    return r.json()["enrollment_code"]


def test_ui_enroll_new_member(open_page, new_client, owner):
    code = make_code(new_client, owner, "newbie@example.com")
    page = open_page()
    page.get_by_test_id("enroll-link").click()
    expect(page.get_by_test_id("enroll-page")).to_be_visible()
    assert page.url.endswith("#/enroll")
    page.get_by_test_id("enroll-code").fill(code)
    page.get_by_test_id("enroll-start").click()
    secret_box = page.get_by_test_id("enroll-secret")
    expect(secret_box).to_be_visible()
    expect(page.get_by_test_id("enroll-email")).to_have_text("newbie@example.com")
    secret = re.sub(r"\s", "", secret_box.inner_text())
    qr = page.get_by_test_id("enroll-qr")
    assert_qr_shown(qr, secret)
    uri = pyotp.TOTP(secret).provisioning_uri(
        name="newbie@example.com", issuer_name="SmartHome"
    )
    assert qr.get_attribute("src") == expected_qr(uri)
    password = "newbie long password 3"
    page.get_by_test_id("enroll-password").fill(password)
    page.get_by_test_id("enroll-password-confirm").fill(password)
    page.get_by_test_id("enroll-totp").fill(pyotp.TOTP(secret).now())
    page.get_by_test_id("enroll-finish").click()
    codes_box = page.get_by_test_id("enroll-recovery-codes")
    expect(codes_box).to_be_visible()
    assert len(re.findall(r"\b\d{8}\b", codes_box.inner_text())) == 10

    page.get_by_test_id("enroll-done").click()
    expect(page.get_by_test_id("login-form")).to_be_visible()
    page.get_by_test_id("login-email").fill("newbie@example.com")
    page.get_by_test_id("login-password").fill(password)
    page.get_by_test_id("login-code").fill(next_step_code(secret))
    page.get_by_test_id("login-submit").click()
    expect(page.get_by_test_id("home-name")).to_have_text("Home A")


def test_ui_enroll_bad_code(open_page):
    page = open_page()
    page.goto("/#/enroll")
    expect(page.get_by_test_id("enroll-page")).to_be_visible()
    page.get_by_test_id("enroll-code").fill("WXYZ-WXYZ-WXYZ-WXYZ")
    page.get_by_test_id("enroll-start").click()
    expect(page.get_by_test_id("enroll-error")).not_to_be_empty()
    expect(page.get_by_test_id("enroll-secret")).to_be_hidden()


def test_ui_enroll_password_mismatch_is_caught(open_page, new_client, owner):
    code = make_code(new_client, owner, "typo@example.com")
    page = open_page()
    page.goto("/#/enroll")
    page.get_by_test_id("enroll-code").fill(code)
    page.get_by_test_id("enroll-start").click()
    secret = re.sub(r"\s", "", page.get_by_test_id("enroll-secret").inner_text())
    page.get_by_test_id("enroll-password").fill("newbie long password 3")
    page.get_by_test_id("enroll-password-confirm").fill("newbie long password 4")
    page.get_by_test_id("enroll-totp").fill(pyotp.TOTP(secret).now())
    page.get_by_test_id("enroll-finish").click()
    expect(page.get_by_test_id("enroll-error")).not_to_be_empty()
    expect(page.get_by_test_id("enroll-recovery-codes")).to_be_hidden()


def test_ui_enroll_existing_account(open_page, new_client, owner, make_home, make_user):
    elsewhere = make_user(make_home("Home B"), role="owner")
    code = make_code(new_client, owner, elsewhere.email)
    page = open_page()
    page.goto("/#/enroll")
    page.get_by_test_id("enroll-code").fill(code)
    page.get_by_test_id("enroll-start").click()
    expect(page.get_by_test_id("enroll-existing")).to_be_visible()
    expect(page.get_by_test_id("enroll-secret")).to_be_hidden()
    expect(page.get_by_test_id("enroll-password-confirm")).to_be_hidden()
    expect(page.get_by_test_id("enroll-qr")).to_be_hidden()
    page.get_by_test_id("enroll-password").fill(elsewhere.password)
    page.get_by_test_id("enroll-totp").fill(elsewhere.totp.now())
    page.get_by_test_id("enroll-finish").click()
    expect(page.get_by_test_id("enroll-done")).to_be_visible()
    page.get_by_test_id("enroll-done").click()
    ui_login(page, elsewhere, code=next_step_code(elsewhere.totp_secret))
    expect(page.get_by_test_id("home-select").locator("option")).to_have_count(2)
