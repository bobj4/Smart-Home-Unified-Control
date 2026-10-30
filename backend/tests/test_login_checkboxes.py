"""The login page's checkboxes are all the same size, whatever their label."""

from playwright.sync_api import expect


def test_ui_login_checkboxes_same_size(open_page):
    for width in (1100, 360):
        page = open_page(width=width, height=800)
        expect(page.get_by_test_id("login-page")).to_be_visible()
        sizes = page.evaluate(
            """() => [...document.querySelectorAll('#login-form .check input')]
            .filter((i) => i.offsetParent !== null)
            .map((i) => { const r = i.getBoundingClientRect(); return [r.width, r.height]; })"""
        )
        assert len(sizes) == 3
        assert all(s == sizes[0] for s in sizes), sizes
        assert sizes[0][0] >= 16
