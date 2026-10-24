"""Operator role, members limited to devices, the Cameras tab, the busy
spinner. Written by the reviewer (roles phase). Do not edit, skip, mark or
delete these tests. If one looks wrong, stop and report the test name and its
full failure output instead of changing it.
"""

import time

from playwright.sync_api import expect

from tests import test_ui as _ui

card, go_settings, ui_login = _ui.card, _ui.go_settings, _ui.ui_login


def url(home_id, suffix=""):
    return f"/api/v1/homes/{home_id}{suffix}"


NEW = {"name": "Desk lamp", "type": "light", "integration": "simulated"}


def test_operator_manages_devices_not_people(
    client, new_client, owner, make_user, login, csrf
):
    home = owner.home_id
    operator = make_user(home, role="operator")
    member = make_user(home, role="member")
    o, m = new_client(), new_client()
    assert login(o, operator).status_code == 200
    assert login(m, member).status_code == 200

    r = o.post(url(home, "/devices"), json=NEW, headers=csrf(o))
    assert r.status_code == 201, r.text
    device = r.json()["id"]
    assert (
        o.patch(
            url(home, f"/devices/{device}"), json={"room": "Office"}, headers=csrf(o)
        ).status_code
        == 200
    )
    on = {"command": "turn_on", "payload": {}}
    assert (
        m.post(url(home, f"/devices/{device}/command"), json=on, headers=csrf(m))
    ).status_code == 200  # members use devices
    assert m.post(url(home, "/devices"), json=NEW, headers=csrf(m)).status_code == 403
    for c in (o, m):
        assert c.get(url(home, "/members")).status_code == 403
        assert (
            c.post(
                url(home, "/members/enrollments"),
                json={"email": "x@example.com", "name": "X", "role": "member"},
                headers=csrf(c),
            ).status_code
            == 403
        )
    assert o.delete(url(home, f"/devices/{device}"), headers=csrf(o)).status_code == 200


def test_owner_gives_the_operator_role(client, owner, make_user, login, csrf):
    member = make_user(owner.home_id, role="member")
    assert login(client, owner).status_code == 200
    r = client.patch(
        url(owner.home_id, f"/members/{member.id}"),
        json={"role": "operator"},
        headers=csrf(client),
    )
    assert r.status_code == 200, r.text
    rows = {
        row["email"]: row for row in client.get(url(owner.home_id, "/members")).json()
    }
    assert rows[member.email]["role"] == "operator"


def test_ui_operator_sees_devices_settings_not_users(open_page, owner, make_user):
    operator = make_user(owner.home_id, role="operator")
    page = open_page()
    ui_login(page, operator)
    go_settings(page, "devices")
    for shown in ("account", "devices", "integrations", "safety"):
        expect(page.get_by_test_id(f"settings-nav-{shown}")).to_have_count(1)
    for hidden in ("members", "admin", "activity"):
        expect(page.get_by_test_id(f"settings-nav-{hidden}")).to_have_count(0)


def test_ui_cameras_tab_follows_frigate(open_page, owner):
    page = open_page()
    ui_login(page, owner)
    expect(page.get_by_test_id("nav-cameras")).to_be_hidden()
    section = go_settings(page, "integrations")
    section.locator(
        '[data-testid="integration-row"][data-integration="frigate"]'
    ).get_by_test_id("integration-toggle").check()
    expect(page.get_by_test_id("nav-cameras")).to_be_visible()


def test_ui_card_shows_spinner_while_applying(open_page, owner, make_device):
    make_device(owner.home_id, name="Slow lamp")
    page = open_page()
    ui_login(page, owner)

    def slow(route):
        time.sleep(1.0)
        route.continue_()

    page.route("**/command", slow)
    card(page, "Slow lamp").get_by_test_id("power-toggle").click()
    expect(card(page, "Slow lamp")).to_have_attribute("data-busy", "true")
    expect(card(page, "Slow lamp").get_by_test_id("power-toggle")).to_have_attribute(
        "aria-pressed", "true"
    )
    expect(card(page, "Slow lamp")).not_to_have_attribute("data-busy", "true")
