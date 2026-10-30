"""Device types always start with a capital letter, and TV is all capitals."""

from playwright.sync_api import expect

from tests import test_ui as _ui


def test_ui_type_labels(open_page, owner, make_device):
    for kind, name in (("light", "Lamp"), ("tv", "Telly"), ("plug", "Fan plug")):
        make_device(owner.home_id, device_type=kind, name=name)
    page = open_page()
    _ui.ui_login(page, owner)
    expect(_ui.card(page, "Lamp")).to_contain_text("Light")
    expect(_ui.card(page, "Telly")).to_contain_text("TV")
    panel = _ui.go_settings(page, "devices")
    rows = panel.get_by_test_id("device-row")
    expect(rows).to_have_count(3)
    kinds = sorted(rows.locator("span.muted").all_inner_texts())
    assert kinds == ["Light", "Plug", "TV"], kinds


def test_type_label_helper(open_page, owner):
    page = open_page()
    labels = page.evaluate(
        "() => ['light', 'tv', 'water_heater', 'smart_switch', ''].map(typeLabel)"
    )
    assert labels == ["Light", "TV", "Water heater", "Smart switch", ""]
