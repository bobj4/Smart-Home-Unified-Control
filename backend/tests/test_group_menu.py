"""The ⋯ (each device) menu shows only on groups with two or more devices."""

import json

from playwright.sync_api import expect

from app.models import DeviceGroup
from tests import test_ui as _ui


def test_ui_menu_only_for_real_groups(open_page, db, owner, make_device):
    a = make_device(owner.home_id, name="Ceiling 1")
    b = make_device(owner.home_id, name="Ceiling 2")
    c = make_device(owner.home_id, name="Porch")
    db.add_all(
        [
            DeviceGroup(
                home_id=owner.home_id, name="Ceiling", device_ids=json.dumps([a, b])
            ),
            DeviceGroup(
                home_id=owner.home_id, name="Outside", device_ids=json.dumps([c])
            ),
        ]
    )
    db.commit()
    page = open_page()
    _ui.ui_login(page, owner)
    groups = page.get_by_test_id("group-card")
    expect(groups).to_have_count(2)
    expect(
        groups.filter(has_text="Ceiling").get_by_test_id("group-menu")
    ).to_have_count(1)
    expect(
        groups.filter(has_text="Outside").get_by_test_id("group-menu")
    ).to_have_count(0)
    expect(groups.filter(has_text="Outside")).to_contain_text("1 device")
