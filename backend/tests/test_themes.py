"""More colour themes: Red ("red") and Purple ("violet"), both on black."""

import pytest
from playwright.sync_api import expect

from app.models import User
from tests import test_ui as _ui

URL = "/api/v1/account/preferences"


@pytest.mark.parametrize("theme", ["red", "violet"])
def test_new_themes_saved(client, db, owner, login, csrf, theme):
    assert login(client, owner).status_code == 200
    r = client.put(URL, json={"theme": theme}, headers=csrf(client))
    assert r.status_code == 200 and r.json() == {"theme": theme}
    assert client.get("/api/v1/account").json()["theme"] == theme
    db.expire_all()
    assert db.get(User, owner.id).theme == theme


def test_other_names_still_refused(client, owner, login, csrf):
    assert login(client, owner).status_code == 200
    for bad in ("purple", "black-red", "RED", ""):
        assert (
            client.put(URL, json={"theme": bad}, headers=csrf(client)).status_code
            == 422
        )


def test_ui_red_and_violet(open_page, owner):
    page = open_page()
    _ui.ui_login(page, owner)
    select = _ui.go_settings(page, "account").get_by_test_id("theme-select")
    expect(select.locator("option")).to_have_text(
        ["Device Theme", "Light", "Dark", "Red", "Purple", "Custom"]
    )
    html = page.locator("html")

    def colours():
        return page.evaluate(
            """() => { const s = getComputedStyle(document.documentElement);
            return [s.getPropertyValue('--bg').trim(), s.getPropertyValue('--accent').trim(),
                    document.querySelector('meta[name="theme-color"]').content]; }"""
        )

    select.select_option("red")
    expect(html).to_have_attribute("data-theme", "red")
    expect(page.get_by_test_id("status")).to_contain_text("Appearance saved")
    assert colours() == ["#0b0b0c", "#d91a1a", "#0b0b0c"]

    select.select_option("violet")
    expect(html).to_have_attribute("data-theme", "violet")
    assert colours() == ["#0c0910", "#8a2be2", "#0c0910"]

    # Kept after a reload.
    page.reload()
    expect(page.get_by_test_id("app-shell")).to_be_visible()
    expect(html).to_have_attribute("data-theme", "violet")

    select = _ui.go_settings(page, "account").get_by_test_id("theme-select")
    select.select_option("system")
    expect(html).not_to_have_attribute("data-theme", "violet")


def test_custom_theme_api(client, db, owner, login, csrf):
    assert login(client, owner).status_code == 200
    # Custom needs a colour the first time.
    assert (
        client.put(URL, json={"theme": "custom"}, headers=csrf(client)).status_code
        == 422
    )
    body = {"theme": "custom", "custom": {"accent": "#2E8B57", "base": "light"}}
    r = client.put(URL, json=body, headers=csrf(client))
    assert r.status_code == 200, r.text
    assert r.json() == {
        "theme": "custom",
        "custom": {"accent": "#2e8b57", "base": "light"},
    }
    account = client.get("/api/v1/account").json()
    assert account["theme"] == "custom"
    assert account["theme_custom"] == {"accent": "#2e8b57", "base": "light"}
    # Another theme keeps the colours for next time; custom alone reuses them.
    assert client.put(URL, json={"theme": "dark"}, headers=csrf(client)).json() == {
        "theme": "dark"
    }
    assert client.get("/api/v1/account").json()["theme_custom"]["accent"] == "#2e8b57"
    r = client.put(URL, json={"theme": "custom"}, headers=csrf(client))
    assert r.status_code == 200 and r.json()["custom"]["base"] == "light"
    for bad in (
        {"accent": "red", "base": "dark"},
        {"accent": "#12345", "base": "dark"},
        {"accent": "#123456", "base": "grey"},
        {"accent": "#123456"},
    ):
        r = client.put(
            URL, json={"theme": "custom", "custom": bad}, headers=csrf(client)
        )
        assert r.status_code == 422, bad


def test_ui_custom_theme(open_page, db, owner):
    page = open_page()
    _ui.ui_login(page, owner)
    account = _ui.go_settings(page, "account")
    expect(account.get_by_test_id("theme-custom")).to_be_hidden()
    account.get_by_test_id("theme-select").select_option("custom")
    expect(account.get_by_test_id("theme-custom")).to_be_visible()
    html = page.locator("html")
    account.get_by_test_id("theme-colour").fill("#2e8b57")
    expect(html).to_have_attribute("data-theme", "custom-dark")  # a preview

    def var(name):
        return page.evaluate(
            f"getComputedStyle(document.documentElement).getPropertyValue('{name}').trim()"
        )

    assert var("--accent") == "#2e8b57"
    account.get_by_test_id("theme-base").select_option("light")
    expect(html).to_have_attribute("data-theme", "custom-light")
    assert var("--surface") == "#ffffff"
    account.get_by_test_id("theme-custom-save").click()
    expect(page.get_by_test_id("status")).to_contain_text("Appearance saved")
    db.expire_all()
    assert db.get(User, owner.id).theme_custom == "#2e8b57 light"

    page.reload()
    expect(page.get_by_test_id("app-shell")).to_be_visible()
    expect(html).to_have_attribute("data-theme", "custom-light")
    assert var("--accent") == "#2e8b57"
    # Back to a named theme: the custom colours are gone from the page.
    _ui.go_settings(page, "account").get_by_test_id("theme-select").select_option("red")
    expect(html).to_have_attribute("data-theme", "red")
    assert var("--accent") == "#d91a1a"


def test_custom_background_colour(client, owner, login, csrf):
    assert login(client, owner).status_code == 200
    body = {"theme": "custom", "custom": {"accent": "#FFCC00", "base": "#1A2B3C"}}
    r = client.put(URL, json=body, headers=csrf(client))
    assert r.json()["custom"] == {"accent": "#ffcc00", "base": "#1a2b3c"}
    bad = {"theme": "custom", "custom": {"accent": "#ffcc00", "base": "#12"}}
    assert client.put(URL, json=bad, headers=csrf(client)).status_code == 422


def test_ui_own_background_and_swatches(open_page, db, owner):
    page = open_page()
    _ui.ui_login(page, owner)
    account = _ui.go_settings(page, "account")
    account.get_by_test_id("theme-select").select_option("custom")
    expect(account.get_by_test_id("theme-background")).to_be_hidden()
    account.get_by_test_id("theme-base").select_option("own")
    expect(account.get_by_test_id("theme-background")).to_be_visible()
    account.get_by_test_id("theme-background").fill("#f0e6d2")  # light: dark text
    html = page.locator("html")
    expect(html).to_have_attribute("data-theme", "custom-light")

    def var(name):
        return page.evaluate(
            f"getComputedStyle(document.documentElement).getPropertyValue('{name}').trim()"
        )

    assert var("--bg") == "#f0e6d2"
    account.get_by_test_id("theme-background").fill("#102030")  # dark
    expect(html).to_have_attribute("data-theme", "custom-dark")
    # The colour buttons show their colour, and the chip shows both.
    assert "50%" in page.evaluate(
        "getComputedStyle(document.querySelector('[data-testid=theme-colour]')).borderRadius"
    )
    expect(account.get_by_test_id("theme-chip")).to_be_visible()
    account.get_by_test_id("theme-custom-save").click()
    expect(page.get_by_test_id("status")).to_contain_text("Appearance saved")
    db.expire_all()
    assert db.get(User, owner.id).theme_custom.endswith(" #102030")
