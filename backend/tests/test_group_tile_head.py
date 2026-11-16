"""A group tile without the ⋯ button keeps its name next to the icon."""

import json

from playwright.sync_api import expect

from app.models import DeviceGroup
from tests import test_ui as _ui


def test_ui_name_next_to_icon(open_page, db, owner, make_device):
    one = make_device(owner.home_id, name="Strip")
    a = make_device(owner.home_id, name="Down 1")
    b = make_device(owner.home_id, name="Down 2")
    db.add_all(
        [
            DeviceGroup(
                home_id=owner.home_id, name="Desk", device_ids=json.dumps([one])
            ),
            DeviceGroup(
                home_id=owner.home_id, name="Down", device_ids=json.dumps([a, b])
            ),
        ]
    )
    db.commit()
    page = open_page()
    _ui.ui_login(page, owner)
    for name in ("Desk", "Down"):
        tile = page.get_by_test_id("group-card").filter(has_text=name)
        expect(tile).to_be_visible()
        gap = tile.evaluate(
            """t => { const head = t.querySelector('.card-head');
            const icon = head.firstElementChild.getBoundingClientRect();
            const text = head.children[1].getBoundingClientRect();
            return text.left - icon.right; }"""
        )
        assert 0 <= gap <= 16, (name, gap)
    menu = (
        page.get_by_test_id("group-card")
        .filter(has_text="Down")
        .get_by_test_id("group-menu")
    )
    box, tile_box = (
        menu.bounding_box(),
        page.get_by_test_id("group-card").filter(has_text="Down").bounding_box(),
    )
    assert (
        tile_box["x"] + tile_box["width"] - (box["x"] + box["width"]) < 40
    )  # at the right
