"""The open TV remote is not rebuilt when the device list is re-read and
nothing changed. It used to be, so a re-read finishing just after the remote
opened (right after login) swapped its buttons out from under a click."""

from playwright.sync_api import expect

from tests import test_ui as _ui


def test_open_remote_survives_refresh(open_page, db, owner, make_device):
    make_device(owner.home_id, device_type="tv", name="Den TV")
    page = open_page()
    _ui.ui_login(page, owner)
    _ui.card(page, "Den TV").get_by_test_id("tv-remote-open").click()
    remote = page.get_by_test_id("tv-remote")
    expect(remote).to_be_visible()
    handle = remote.element_handle()
    # Re-read the devices, as the page does after login or a home change.
    page.evaluate("() => window.smartHomeApp.devices.load()")
    assert handle.evaluate("node => node.isConnected") is True
    expect(remote).to_be_visible()
