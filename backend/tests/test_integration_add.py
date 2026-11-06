"""Settings > Integrations: "Add integration…" lists the brands not turned on;
picking one turns it on and goes to its setup."""

from playwright.sync_api import expect

from tests import test_ui as _ui


def test_ui_add_integration(open_page, owner, make_user):
    page = open_page()
    _ui.ui_login(page, owner)
    _ui.go_settings(page, "integrations")
    add = page.get_by_test_id("integration-add")
    options = add.locator("option")
    expect(options.first).to_have_text("Add integration…")
    names = options.all_inner_texts()
    assert "Philips Hue" in names and "Roku TV" in names
    assert "Simulated" not in " ".join(names)  # already on
    add.select_option("hue")
    expect(page.get_by_test_id("status")).to_contain_text("Philips Hue turned on")
    expect(page.get_by_test_id("hue")).to_be_in_viewport()
    toggle = page.locator(
        '[data-testid="integration-row"][data-integration="hue"]'
    ).get_by_test_id("integration-toggle")
    expect(toggle).to_be_checked()
    expect(
        page.get_by_test_id("integration-add").locator('option[value="hue"]')
    ).to_have_count(0)


def test_ui_no_add_for_operators(open_page, owner, make_user):
    operator = make_user(owner.home_id, role="operator")
    page = open_page()
    _ui.ui_login(page, operator)
    _ui.go_settings(page, "integrations")
    expect(page.get_by_test_id("integration-row").first).to_be_visible()
    expect(page.get_by_test_id("integration-add")).to_have_count(0)
