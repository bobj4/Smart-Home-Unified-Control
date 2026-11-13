"""More than one home: Admin > Home adds homes and sets each one's name,
address and icon (built in, or a picture); each person orders their homes;
the top one opens on a first login, then the last one viewed."""

import base64
import struct
import zlib

from playwright.sync_api import expect

from app.models import DeviceSafetyLimits, HomeMembership
from tests import test_ui as _ui

HOMES = "/api/v1/homes"


def png(width=4, height=4):
    raw = b"".join(b"\x00" + b"\x4c\x8d\xff" * width for _ in range(height))

    def chunk(kind, data):
        return (
            struct.pack(">I", len(data))
            + kind
            + data
            + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)
        )

    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(raw))
        + chunk(b"IEND", b"")
    )


def data_url(raw, kind="png"):
    return f"data:image/{kind};base64,{base64.b64encode(raw).decode()}"


def add(client, csrf, **body):
    return client.post(HOMES, json={"name": "Lake House", **body}, headers=csrf(client))


def test_add_a_home(client, db, owner, login, csrf, make_user, new_client):
    assert login(client, owner).status_code == 200
    r = add(client, csrf, address="1 Shore Rd", icon="cabin")
    assert r.status_code == 201, r.text
    lake = r.json()
    assert lake["role"] == "admin" and lake["icon"] == "cabin"
    assert lake["address"] == "1 Shore Rd"
    homes = client.get(HOMES).json()
    assert [h["id"] for h in homes] == [owner.home_id, lake["id"]]  # at the bottom
    # A new home starts with the recommended safety limits, like the first.
    assert db.query(DeviceSafetyLimits).filter_by(home_id=lake["id"]).count() > 0
    assert add(client, csrf, icon="castle").status_code == 422
    member = make_user(owner.home_id, role="member")
    other = new_client()
    assert login(other, member).status_code == 200
    assert add(other, csrf).status_code == 403
    assert len(other.get(HOMES).json()) == 1  # not someone else's new home


def test_name_address_icon_and_picture(
    client, owner, login, csrf, make_user, new_client
):
    assert login(client, owner).status_code == 200
    url = f"{HOMES}/{owner.home_id}"
    r = client.patch(
        url, json={"address": "2 Main St", "icon": "farm"}, headers=csrf(client)
    )
    assert r.status_code == 200, r.text
    assert (r.json()["name"], r.json()["address"], r.json()["icon"]) == (
        "Home A",
        "2 Main St",
        "farm",
    )
    assert (
        client.patch(url, json={"icon": "castle"}, headers=csrf(client)).status_code
        == 422
    )
    assert client.patch(url, json={}, headers=csrf(client)).status_code == 422
    picture = f"{url}/icon-image"
    good = data_url(png())
    r = client.put(picture, json={"data_url": good}, headers=csrf(client))
    assert r.status_code == 200 and r.json()["icon_image"] == good
    for bad in (
        data_url(b"GIF89a....", "png"),  # not what it says
        "data:image/gif;base64,R0lGODlh",  # not a kind it takes
        data_url(b"\x89PNG\r\n\x1a\n" + b"0" * 100_000),  # too big
    ):
        assert (
            client.put(
                picture, json={"data_url": bad}, headers=csrf(client)
            ).status_code
            == 422
        )
    assert client.delete(picture, headers=csrf(client)).json()["icon_image"] is None
    member = make_user(owner.home_id, role="member")
    other = new_client()
    assert login(other, member).status_code == 200
    assert (
        other.patch(url, json={"icon": "boat"}, headers=csrf(other)).status_code == 403
    )
    assert (
        other.put(picture, json={"data_url": good}, headers=csrf(other)).status_code
        == 403
    )


def test_order_and_last_viewed(client, db, owner, login, csrf, make_home):
    assert login(client, owner).status_code == 200
    second = add(client, csrf, name="Cabin").json()["id"]
    third = add(client, csrf, name="Apartment").json()["id"]
    order = f"{'/api/v1/account'}/home-order"
    r = client.put(
        order, json={"home_ids": [third, owner.home_id]}, headers=csrf(client)
    )
    assert [h["id"] for h in r.json()] == [third, owner.home_id, second]
    elsewhere = make_home("Elsewhere")
    assert (
        client.put(
            order, json={"home_ids": [elsewhere]}, headers=csrf(client)
        ).status_code
        == 404
    )
    account = "/api/v1/account"
    assert client.get(account).json()["last_home_id"] is None
    last = f"{account}/last-home"
    assert (
        client.put(last, json={"home_id": second}, headers=csrf(client)).status_code
        == 200
    )
    assert client.get(account).json()["last_home_id"] == second
    assert (
        client.put(last, json={"home_id": elsewhere}, headers=csrf(client)).status_code
        == 404
    )
    # No longer a member there: it is not offered.
    db.query(HomeMembership).filter_by(user_id=owner.id, home_id=second).delete()
    db.commit()
    assert client.get(account).json()["last_home_id"] is None


def test_ui_add_switch_and_come_back(open_page, new_client, owner, login, csrf):
    page = open_page()
    _ui.ui_login(page, owner)
    expect(page.get_by_test_id("home-badge")).to_be_visible()
    # Hold every save of the home last viewed, as a slow link would.
    held = []
    page.route("**/api/v1/account/last-home", lambda route: held.append(route))
    panel = _ui.go_settings(page, "admin").get_by_test_id("homes-panel")
    expect(panel.get_by_test_id("home-row")).to_have_count(1)
    panel.get_by_test_id("home-add").click()
    panel.get_by_test_id("home-add-name").fill("Lake House")
    panel.get_by_test_id("home-add-address").fill("1 Shore Rd")
    panel.locator("[data-testid=home-add-form] [data-icon=boat]").click()
    panel.get_by_test_id("home-add-save").click()
    expect(page.get_by_test_id("status")).to_contain_text("Lake House added")
    expect(page.get_by_test_id("home-name")).to_have_text("Lake House")
    # The icon at the top right lists both homes and switches.
    page.get_by_test_id("home-badge").click()
    menu = page.get_by_test_id("home-menu")
    expect(menu.get_by_test_id("home-menu-item")).to_have_count(2)
    menu.get_by_test_id("home-menu-item").filter(has_text="Home A").click()
    expect(page.get_by_test_id("home-name")).to_have_text("Home A")
    page.get_by_test_id("home-badge").click()
    page.get_by_test_id("home-menu").get_by_test_id("home-menu-item").filter(
        has_text="Lake House"
    ).click()
    expect(page.get_by_test_id("home-name")).to_have_text("Lake House")
    # Let them through out of order (newest, then oldest first): what was
    # chosen last must still be what is saved.
    for _ in range(6):
        page.wait_for_timeout(250)
        order = held[-1:] + held[:-1]
        held.clear()
        for route in order:
            route.continue_()
            page.wait_for_timeout(150)
    # Next login opens the home last viewed (logging out waits for its save).
    page.get_by_test_id("logout").click()
    expect(page.get_by_test_id("login-form")).to_be_visible()
    again = open_page()
    _ui.ui_login(again, owner, owner.totp.at(__import__("time").time() + 30))
    expect(again.get_by_test_id("home-name")).to_have_text("Lake House")


def test_ui_first_login_opens_the_top_home_and_a_picture_shows(
    open_page, db, owner, make_home, tmp_path
):
    lake = make_home("Lake House")
    db.add(HomeMembership(user_id=owner.id, home_id=lake, role="admin", position=-1))
    db.commit()
    page = open_page()
    _ui.ui_login(page, owner)
    expect(page.get_by_test_id("home-name")).to_have_text("Lake House")  # on top
    panel = _ui.go_settings(page, "admin").get_by_test_id("homes-panel")
    expect(panel.get_by_test_id("home-row").first).to_contain_text("Lake House")
    picture = tmp_path / "home.png"
    picture.write_bytes(png(40, 30))
    panel.get_by_test_id("home-picture-input").set_input_files(str(picture))
    expect(page.get_by_test_id("status")).to_contain_text("Picture saved")
    expect(page.get_by_test_id("home-badge").locator("img")).to_be_visible()
    panel.get_by_test_id("home-picture-remove").click()
    expect(page.get_by_test_id("home-badge").locator("svg")).to_be_visible()
