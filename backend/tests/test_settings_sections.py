"""Settings pages: foldable sections (remembered per person, with jump links)
and live updates (a change made elsewhere shows without reloading)."""

from playwright.sync_api import expect

from tests import test_ui as _ui


def test_collapsed_api(client, owner, login, csrf):
    assert login(client, owner).status_code == 200
    assert client.get("/api/v1/account").json()["collapsed_sections"] == []
    body = {"sections": ["admin/motd-settings", "admin/motd-settings", "x" * 101]}
    r = client.put("/api/v1/account/collapsed", json=body, headers=csrf(client))
    assert r.json() == {"sections": ["admin/motd-settings"]}
    assert client.get("/api/v1/account").json()["collapsed_sections"] == [
        "admin/motd-settings"
    ]
    bad = client.put(
        "/api/v1/account/collapsed", json={"sections": "x"}, headers=csrf(client)
    )
    assert bad.status_code == 422


def test_ui_fold_sections_and_jump(open_page, owner):
    page = open_page()
    _ui.ui_login(page, owner)
    _ui.go_settings(page, "admin")
    motd = page.get_by_test_id("motd-settings")
    heading = motd.locator("h3")
    expect(page.get_by_test_id("motd-input")).to_be_visible()
    heading.click()
    expect(heading).to_have_attribute("aria-expanded", "false")
    expect(page.get_by_test_id("motd-input")).to_be_hidden()
    page.wait_for_timeout(300)  # the save
    page.reload()
    expect(page.get_by_test_id("app-shell")).to_be_visible()
    expect(page.get_by_test_id("motd-input")).to_be_hidden()  # remembered
    page.get_by_test_id("section-jump").get_by_role(
        "button", name="Message of the day"
    ).click()
    expect(page.get_by_test_id("motd-input")).to_be_visible()
    page.get_by_test_id("section-fold-all").click()
    expect(page.get_by_test_id("motd-input")).to_be_hidden()
    expect(page.get_by_test_id("login-rules")).to_have_class("subpanel collapsed")
    expect(page.get_by_test_id("login-failures")).to_be_hidden()


def test_ui_grouped_sections(open_page, owner):
    """Login rules holds the account rules, failed logins and login times;
    2 Factor Login holds approved devices (Admin) and the status,
    authenticator app and recovery codes (My account); the background
    picture is part of Appearance."""
    page = open_page()
    _ui.ui_login(page, owner)
    _ui.go_settings(page, "admin")
    jump = page.get_by_test_id("section-jump")
    expect(jump.get_by_role("button", name="Login rules", exact=True)).to_be_visible()
    expect(jump.get_by_role("button", name="2 Factor Login")).to_be_visible()
    for gone in ("Failed logins", "Login times", "Approved devices"):
        expect(jump.get_by_role("button", name=gone)).to_have_count(0)
    rules = page.get_by_test_id("login-rules")
    for part in ("login-failures", "login-times"):
        expect(rules.get_by_test_id(part)).to_have_class("subsection")
    expect(rules.get_by_test_id("login-policy-save")).to_be_visible()
    expect(
        page.get_by_test_id("admin-two-factor").get_by_test_id("admin-devices")
    ).to_be_visible()
    page.get_by_test_id("admin-two-factor").locator(":scope > h3").click()
    expect(page.get_by_test_id("admin-devices")).to_be_hidden()

    _ui.go_settings(page, "account")
    jump = page.get_by_test_id("section-jump")
    expect(jump.get_by_role("button", name="2 Factor Login")).to_be_visible()
    for gone in ("Recovery codes", "Authenticator app", "Background picture"):
        expect(jump.get_by_role("button", name=gone)).to_have_count(0)
    group = page.get_by_test_id("two-factor-login")
    for part in ("two-factor-status", "totp-start", "recovery-generate"):
        expect(group.get_by_test_id(part)).to_be_visible()
    appearance = page.get_by_test_id("theme-select").locator(
        "xpath=ancestor::div[contains(@class, 'subpanel')][1]"
    )
    expect(appearance.get_by_test_id("background")).to_have_class("subsection")
    expect(appearance).not_to_contain_text("null")


def test_ui_settings_update_live(open_page, client, owner, login, csrf):
    assert login(client, owner).status_code == 200  # first: a code works once
    page = open_page()
    _ui.ui_login(page, owner, code=owner.recovery_codes[0])
    _ui.go_settings(page, "admin")
    page.evaluate("window.smartHomeApp.refreshMs = 300")
    page.get_by_test_id("home-name").click()  # nothing focused
    expect(page.get_by_test_id("motd-input")).to_have_value("")
    r = client.put(
        "/api/v1/admin/motd", json={"text": "Changed elsewhere"}, headers=csrf(client)
    )
    assert r.status_code == 200
    expect(page.get_by_test_id("motd-input")).to_have_value(
        "Changed elsewhere", timeout=15000
    )
    # Not while someone is typing.
    page.get_by_test_id("motd-input").fill("my draft")
    page.locator("body").click()
    client.put(
        "/api/v1/admin/motd", json={"text": "Second change"}, headers=csrf(client)
    )
    page.wait_for_timeout(3000)
    expect(page.get_by_test_id("motd-input")).to_have_value("my draft")


def test_ui_live_after_choices_and_saves(open_page, client, owner, login, csrf):
    """Using a list, a switch or Save does not stop the page updating; only
    typing that is not saved yet does."""
    assert login(client, owner).status_code == 200
    page = open_page()
    _ui.ui_login(page, owner, code=owner.recovery_codes[0])
    _ui.go_settings(page, "devices")
    page.evaluate("window.smartHomeApp.refreshMs = 300")
    page.get_by_test_id("room-new-name").fill("Kitchen")
    page.get_by_test_id("room-create").click()  # typed, then saved
    expect(page.get_by_test_id("status")).to_contain_text("Room created")
    page.get_by_test_id("home-name").click()  # nothing focused
    url = f"/api/v1/homes/{owner.home_id}/devices"
    r = client.post(
        url,
        json={"name": "New lamp", "type": "light", "integration": "simulated"},
        headers=csrf(client),
    )
    assert r.status_code == 201, r.text
    rows = page.get_by_test_id("device-row")
    expect(rows.filter(has_text="New lamp")).to_have_count(0)  # its value, not text
    expect(page.locator('[data-testid="device-name"][value="New lamp"]')).to_have_count(
        0
    )
    names = page.get_by_test_id("device-name")
    expect(names).to_have_count(1, timeout=15000)
    expect(names.first).to_have_value("New lamp")
    # Typing a new name, not saved: the page waits.
    names.first.fill("Typed lamp")
    page.get_by_test_id("home-name").click()
    client.post(
        url,
        json={"name": "Second lamp", "type": "light", "integration": "simulated"},
        headers=csrf(client),
    )
    page.wait_for_timeout(3000)
    expect(names).to_have_count(1)
    expect(names.first).to_have_value("Typed lamp")
