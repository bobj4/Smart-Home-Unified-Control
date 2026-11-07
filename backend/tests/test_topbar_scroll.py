"""On a phone the top bar's links scroll sideways when they do not fit,
instead of making the whole page wider."""

from playwright.sync_api import expect

from tests import test_ui as _ui


def test_phone_page_is_not_wider_than_the_screen(open_page, owner, make_device):
    make_device(owner.home_id, device_type="thermostat", name="Hallway")
    page = open_page()
    page.set_viewport_size({"width": 360, "height": 740})
    _ui.ui_login(page, owner)
    expect(page.get_by_test_id("nav-thermostats")).to_be_visible()
    # Make the bar wider than the screen, as a long home name and many tabs do.
    page.evaluate(
        "document.querySelectorAll('.nav-link').forEach(a => { a.textContent += ' tab' })"
    )
    widths = page.evaluate(
        "() => [document.documentElement.scrollWidth, window.innerWidth,"
        " document.querySelector('.nav').scrollWidth,"
        " document.querySelector('.nav').clientWidth]"
    )
    page_width, screen, nav_content, nav_box = widths
    assert page_width <= screen
    assert nav_content > nav_box  # the links scroll inside the bar
    logout = page.get_by_test_id("logout")
    logout.scroll_into_view_if_needed()
    expect(logout).to_be_in_viewport()
    assert page.evaluate("window.scrollX") == 0
