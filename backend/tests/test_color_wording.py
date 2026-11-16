"""US spelling ("color") in what the app shows, and the Appearance wording:
"Themes" for the theme choice and "Custom" for one's own background."""

import re
from pathlib import Path

from playwright.sync_api import expect

from tests import test_ui as _ui

WEB = Path(__file__).resolve().parents[2] / "web"


def test_no_colour_in_the_web_app():
    # Test ids (theme-colour) are names, not wording.
    for path in [*WEB.rglob("*.js"), *WEB.rglob("*.css"), *WEB.rglob("*.html")]:
        text = re.sub(r"theme-colour", "", path.read_text(encoding="utf-8"))
        assert "colour" not in text.lower(), path


def test_ui_appearance_wording(open_page, owner):
    page = open_page()
    _ui.ui_login(page, owner)
    account = _ui.go_settings(page, "account")
    select = account.get_by_test_id("theme-select")
    expect(
        account.locator("label.field", has=page.get_by_test_id("theme-select"))
    ).to_contain_text("Themes")
    select.select_option("custom")
    base = account.get_by_test_id("theme-base")
    expect(base.locator("option[value=own]")).to_have_text("Custom")
    base.select_option("own")
    expect(account.get_by_test_id("theme-custom")).to_contain_text("Background color")
    expect(account.get_by_test_id("theme-custom-save")).to_have_text("Save colors")
