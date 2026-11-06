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
    expect(page.get_by_test_id("login-failures")).to_have_class("subpanel collapsed")


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
