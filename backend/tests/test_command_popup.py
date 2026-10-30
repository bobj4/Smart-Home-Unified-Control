"""A device that does not follow a command opens a popup with the reason and
Retry, instead of only a line at the top of the page."""

import json

from playwright.sync_api import expect

from app.models import DeviceGroup
from tests import test_ui as _ui


def failing_once(page, pattern, body):
    calls = {"n": 0}

    def handle(route):
        if route.request.method == "POST" and calls["n"] == 0:
            calls["n"] += 1
            route.fulfill(
                status=502, content_type="application/json", body=json.dumps(body)
            )
        else:
            route.continue_()

    page.route(pattern, handle)
    return calls


def test_ui_failed_command_popup_and_retry(open_page, owner, make_device):
    make_device(owner.home_id, name="Porch")
    page = open_page()
    _ui.ui_login(page, owner)
    failing_once(
        page, "**/devices/*/command", {"detail": "Cync did not answer in time"}
    )
    _ui.card(page, "Porch").get_by_test_id("power-toggle").click()
    popup = page.get_by_test_id("command-popup")
    expect(popup).to_be_visible()
    expect(popup.get_by_test_id("command-popup-title")).to_have_text(
        "Porch did not turn on"
    )
    expect(popup).to_contain_text("Cync did not answer in time")
    popup.get_by_test_id("command-popup-retry").click()
    expect(popup).to_be_hidden()
    expect(_ui.card(page, "Porch")).to_have_class("device-card on")


def test_ui_group_lists_the_devices_that_failed(open_page, db, owner, make_device):
    a = make_device(owner.home_id, name="Ceiling 1")
    b = make_device(owner.home_id, name="Ceiling 2")
    db.add(
        DeviceGroup(
            home_id=owner.home_id, name="Ceiling", device_ids=json.dumps([a, b])
        )
    )
    db.commit()
    page = open_page()
    _ui.ui_login(page, owner)

    def partly(route):
        response = route.fetch()
        data = response.json()
        data["results"][1] = {
            "device_id": b,
            "ok": False,
            "detail": "Cync did not answer in time",
        }
        route.fulfill(response=response, body=json.dumps(data))

    page.route("**/groups/*/command", partly)
    page.get_by_test_id("group-card").get_by_test_id("power-toggle").click()
    popup = page.get_by_test_id("command-popup")
    expect(popup).to_be_visible()
    expect(popup.get_by_test_id("command-popup-title")).to_have_text(
        "Ceiling did not turn on"
    )
    expect(popup.get_by_test_id("command-popup-reasons")).to_have_text(
        "Ceiling 2: Cync did not answer in time"
    )
    popup.get_by_test_id("command-popup-close").click()
    expect(popup).to_be_hidden()


def test_ui_no_popup_when_it_works(open_page, owner, make_device):
    make_device(owner.home_id, name="Porch")
    page = open_page()
    _ui.ui_login(page, owner)
    _ui.card(page, "Porch").get_by_test_id("power-toggle").click()
    expect(_ui.card(page, "Porch")).to_have_class("device-card on")
    expect(page.get_by_test_id("command-popup")).to_have_count(0)
