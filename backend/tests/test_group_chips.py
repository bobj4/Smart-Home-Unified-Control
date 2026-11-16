"""Settings > Devices: groups work like rooms (a chip each, ✕ to delete, a
box to create one), with no list of rows to edit."""

import json

from playwright.sync_api import expect

from app.models import DeviceGroup
from tests import test_ui as _ui


def test_ui_group_chips(open_page, db, owner, make_device):
    lamp = make_device(owner.home_id, name="Ceiling 1")
    db.add(
        DeviceGroup(
            home_id=owner.home_id, name="Ceiling", device_ids=json.dumps([lamp])
        )
    )
    db.commit()
    page = open_page()
    _ui.ui_login(page, owner)
    section = _ui.go_settings(page, "devices")
    chip = section.get_by_test_id("group-row").filter(has_text="Ceiling")
    expect(chip).to_have_class("chip")  # like a room: its name and ✕
    expect(chip).to_have_attribute("title", "1 device in Lab")
    expect(chip.locator("select, input")).to_have_count(0)
    expect(section.get_by_test_id("group-save")).to_have_count(0)  # no list of rows
    section.get_by_test_id("group-row").get_by_test_id("group-delete").click()
    expect(section.get_by_test_id("group-row")).to_have_count(0)
    db.expire_all()
    assert db.query(DeviceGroup).count() == 0
