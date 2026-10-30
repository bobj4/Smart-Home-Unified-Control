"""Edit a TV's name, address, MAC and model year; a new address or model
year means pairing again."""

from playwright.sync_api import expect

from app.models import AuditEvent, Device
from tests import test_ui as _ui
from tests.test_samsung import ready_tv, url
from tests.test_samsung import secrets_key as secrets_key  # noqa: F401
from tests.test_samsung import tv as tv  # noqa: F401


def edit(client, csrf, home_id, device_id, **body):
    return client.put(
        url(home_id, f"/integrations/samsung_tv/tvs/{device_id}"),
        json=body,
        headers=csrf(client),
    )


def test_edit_keeps_pairing_for_name_and_mac(
    client, db, owner, login, csrf, tv, secrets_key
):
    device_id = ready_tv(client, csrf, login, owner, tv)
    db.get(Device, device_id).room = "Den"
    db.commit()
    r = edit(
        client,
        csrf,
        owner.home_id,
        device_id,
        name="Den TV",
        host="192.168.1.50",
        protocol="tizen",
        mac="aa-bb-cc-dd-ee-ff",
    )
    assert r.status_code == 200, r.text
    assert r.json()["pair_again"] is False and r.json()["paired"] is True
    assert r.json()["mac"] == "AA:BB:CC:DD:EE:FF"
    db.expire_all()
    device = db.get(Device, device_id)
    assert (device.name, device.room) == ("Den TV", "Den")  # room kept
    assert db.query(AuditEvent).filter_by(event_type="tv_changed").count() == 1


def test_new_address_means_pairing_again(
    client, db, owner, login, csrf, tv, secrets_key
):
    device_id = ready_tv(client, csrf, login, owner, tv)
    r = edit(
        client,
        csrf,
        owner.home_id,
        device_id,
        name="TV",
        host="192.168.1.77",
        protocol="tizen",
    )
    assert (
        r.status_code == 200
        and r.json()["pair_again"] is True
        and r.json()["paired"] is False
    )
    for bad in (
        {"host": "8.8.8.8"},
        {"host": "x"},
        {"protocol": "webos"},
        {"mac": "nope"},
    ):
        body = {"name": "TV", "host": "192.168.1.77", "protocol": "tizen", **bad}
        assert edit(client, csrf, owner.home_id, device_id, **body).status_code == 422


def test_ui_edit_tv(open_page, db, owner, login, client, csrf, tv, secrets_key):
    device_id = ready_tv(client, csrf, login, owner, tv)
    page = open_page()
    _ui.ui_login(page, owner, owner.totp.at(__import__("time").time() + 30))
    section = _ui.go_settings(page, "integrations")
    row = section.locator(
        f'[data-testid="samsung-tv-row"][data-device-id="{device_id}"]'
    )
    row.get_by_test_id("samsung-edit").click()
    form = section.get_by_test_id("samsung-edit-form")
    expect(form.get_by_test_id("samsung-edit-repair")).to_be_hidden()
    form.get_by_test_id("samsung-edit-name").fill("Bedroom TV")
    form.get_by_test_id("samsung-edit-host").fill("192.168.1.60")
    expect(form.get_by_test_id("samsung-edit-repair")).to_be_visible()
    form.get_by_test_id("samsung-edit-save").click()
    expect(page.get_by_test_id("status")).to_contain_text("Press Pair to pair it again")
    expect(section.get_by_test_id("samsung-tv-row")).to_contain_text("192.168.1.60")
    expect(page.get_by_test_id("toast")).to_have_text("Changes Saved")
