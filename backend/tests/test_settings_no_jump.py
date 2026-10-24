"""Redrawing a settings page (the 5-second live refresh of Integrations, or
turning an integration on or off) keeps the page where it was scrolled to,
instead of emptying it while it reloads and snapping back to the top."""

from playwright.sync_api import expect

from tests import test_ui as _ui

REDRAW = """async (live) => {
  const settings = window.smartHomeApp.settings;
  let lowest = window.scrollY;
  const watch = () => { lowest = Math.min(lowest, window.scrollY); };
  window.addEventListener('scroll', watch);
  settings.shown = null;
  await settings.load('integrations', { live });
  await new Promise((done) => requestAnimationFrame(() => requestAnimationFrame(done)));
  window.removeEventListener('scroll', watch);
  return { lowest, after: window.scrollY };
}"""


def test_integrations_redraw_keeps_the_scroll_position(open_page, owner, make_device):
    for n in range(40):
        make_device(owner.home_id, name=f"Lamp {n:02d}")
    page = open_page(width=390, height=700)
    _ui.ui_login(page, owner)
    page.goto("/#/settings/integrations")
    expect(page.get_by_test_id("integration-devices").first).to_be_visible()
    page.evaluate("() => window.scrollTo(0, document.body.scrollHeight)")
    before = page.evaluate("() => window.scrollY")
    assert before > 500  # the page really is scrolled down

    for live in (True, False):  # the 5-second refresh, and after a change
        result = page.evaluate(REDRAW, live)
        assert result["lowest"] == before, (live, result)  # never jumped up
        assert result["after"] == before, (live, result)
    expect(page.get_by_test_id("integration-row").first).to_be_visible()


def test_opening_another_section_still_starts_fresh(open_page, owner, make_device):
    page = open_page()
    _ui.ui_login(page, owner)
    page.goto("/#/settings/integrations")
    expect(page.get_by_test_id("integration-row").first).to_be_visible()
    page.goto("/#/settings/account")
    expect(page.get_by_test_id("settings-account")).to_be_visible()
    expect(page.get_by_test_id("integration-row")).to_have_count(0)
    page.get_by_test_id("nav-devices").click()
    page.get_by_test_id("nav-settings").click()
    page.goto("/#/settings/integrations")
    expect(page.get_by_test_id("integration-row").first).to_be_visible()


def test_live_refresh_never_replaces_typing(open_page, owner, make_device):
    make_device(owner.home_id, name="Lamp")
    page = open_page()
    _ui.ui_login(page, owner)
    page.goto("/#/settings/integrations")
    row = page.get_by_test_id("integration-row").first
    expect(row).to_be_visible()
    handle = row.element_handle()
    # Someone types while a live refresh is loading: the page is kept.
    page.evaluate(
        """async () => {
          const settings = window.smartHomeApp.settings;
          settings.shown = null;
          const loading = settings.load('integrations', { live: true });
          settings.dirty = true;
          await loading;
        }"""
    )
    assert handle.evaluate("node => node.isConnected") is True
