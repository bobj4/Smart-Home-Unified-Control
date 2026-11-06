"""The Edit layout button stays at the bottom right of the Devices page."""

import time

from playwright.sync_api import expect

from tests import test_ui as _ui


def test_ui_layout_button_bottom_right(open_page, owner, make_device):
    for n in range(12):
        make_device(owner.home_id, name=f"Lamp {n}")
    for step, (width, height) in enumerate(((1280, 800), (390, 760))):
        page = open_page(width=width, height=height)
        _ui.ui_login(page, owner, owner.totp.at(time.time() + 30 * step))
        button = page.get_by_test_id("layout-open")
        expect(button).to_be_visible()
        box = button.bounding_box()
        assert width - (box["x"] + box["width"]) <= 24, box
        assert height - (box["y"] + box["height"]) <= 24, box
        page.mouse.wheel(0, 2000)  # still there after scrolling
        box = button.bounding_box()
        assert height - (box["y"] + box["height"]) <= 24, box
        page.close()


def test_ui_layout_button_never_over_popups(open_page, owner, make_device):
    make_device(owner.home_id, name="Lamp")
    page = open_page()
    _ui.ui_login(page, owner)
    button = page.get_by_test_id("layout-open")
    expect(button).to_be_visible()
    button.click()  # the room order popup
    expect(page.get_by_test_id("layout-panel")).to_be_visible()
    expect(button).to_be_hidden()
    page.keyboard.press("Escape")
    expect(page.get_by_test_id("layout-panel")).to_be_hidden()
    expect(button).to_be_visible()
    _ui.card(page, "Lamp").get_by_test_id(
        "light-settings-open"
    ).click()  # another popup
    expect(page.get_by_test_id("light-panel")).to_be_visible()
    expect(button).to_be_hidden()
    z = button.evaluate("b => Number(getComputedStyle(b).zIndex)")
    overlay_z = page.evaluate(
        "() => { const o = document.createElement('div'); o.className = 'overlay'; o.hidden = true;"
        " document.body.append(o); const z = Number(getComputedStyle(o).zIndex); o.remove(); return z; }"
    )
    assert z < overlay_z
