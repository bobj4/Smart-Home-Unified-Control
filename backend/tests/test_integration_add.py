"""Settings > Integrations: only the brands in use are listed, each with
"Remove integration"; "Add integration…" lists the rest, and picking one
turns it on and goes to its setup."""

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
    section = page.get_by_test_id("settings-integrations")
    expect(_ui.integration_row(section, "hue")).to_be_visible()
    expect(
        page.get_by_test_id("integration-add").locator('option[value="hue"]')
    ).to_have_count(0)
    # Remove integration: asks first, then it goes back to the list.
    row = _ui.integration_row(section, "hue")
    row.get_by_test_id("integration-remove").click()
    row.get_by_test_id("integration-remove-cancel").click()
    expect(row).to_be_visible()
    _ui.remove_integration(section, "hue")
    expect(page.get_by_test_id("status")).to_contain_text("Philips Hue removed")
    expect(
        page.get_by_test_id("integration-add").locator('option[value="hue"]')
    ).to_have_count(1)


def test_ui_no_add_for_operators(open_page, owner, make_user):
    operator = make_user(owner.home_id, role="operator")
    page = open_page()
    _ui.ui_login(page, operator)
    _ui.go_settings(page, "integrations")
    expect(page.get_by_test_id("integration-row").first).to_be_visible()
    expect(page.get_by_test_id("integration-add")).to_have_count(0)
