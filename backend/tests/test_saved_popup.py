"""Every Save button shows a "Changes Saved" popup once the server has the
change; a failed save shows the reason in a popup that stays until closed."""

from playwright.sync_api import expect

from tests import test_ui as _ui


def test_ui_changes_saved_popup(open_page, owner):
    page = open_page()
    _ui.ui_login(page, owner)
    _ui.go_settings(page, "admin")
    times = page.get_by_test_id("login-times")
    times.get_by_test_id("login-time-keep_logged_in_days").fill("14")
    times.get_by_test_id("login-times-save").click()
    toast = page.get_by_test_id("toast")
    expect(toast).to_be_visible()
    expect(toast).to_have_text("Changes Saved")
    expect(toast).to_have_attribute("data-kind", "success")
    expect(toast).to_be_hidden(timeout=4000)  # closes by itself


def test_ui_failed_save_popup_stays(open_page, owner):
    page = open_page()
    _ui.ui_login(page, owner)
    _ui.go_settings(page, "admin")
    page.route(
        "**/api/v1/admin/login-times",
        lambda route: (
            route.fulfill(
                status=409,
                content_type="application/json",
                body='{"detail": "Not saved: try again"}',
            )
            if route.request.method == "PUT"
            else route.continue_()
        ),
    )
    page.get_by_test_id("login-times").get_by_test_id("login-times-save").click()
    toast = page.get_by_test_id("toast")
    expect(toast).to_contain_text("Not saved: try again")
    expect(toast).to_have_attribute("data-kind", "error")
    page.wait_for_timeout(2500)
    expect(toast).to_be_visible()  # an error stays
    toast.get_by_test_id("toast-close").click()
    expect(toast).to_be_hidden()


def test_ui_no_popup_for_other_buttons(open_page, owner, make_device):
    make_device(owner.home_id, name="Lamp")
    page = open_page()
    _ui.ui_login(page, owner)
    _ui.card(page, "Lamp").get_by_test_id("power-toggle").click()
    expect(_ui.card(page, "Lamp")).to_have_class("device-card on")
    expect(page.get_by_test_id("toast")).to_be_hidden()
