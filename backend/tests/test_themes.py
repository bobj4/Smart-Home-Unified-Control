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
        ["Device Theme", "Light", "Dark", "Red", "Purple"]
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
