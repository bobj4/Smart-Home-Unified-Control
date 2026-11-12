"""Admin > 2 Factor Login shows everyone's devices: where each person in my
homes is logged in (beside their approved devices), and Log out."""

from playwright.sync_api import expect

from tests import test_login_times as _times
from tests import test_ui as _ui

ALL = "/api/v1/admin/sessions"


def test_admin_sees_everyones_logged_in_devices(
    client, new_client, owner, make_user, make_home, login, csrf
):
    member = make_user(owner.home_id, role="member")
    guest = make_user(owner.home_id, role="guest")
    stranger = make_user(make_home("Elsewhere"), role="admin")
    clients = {}
    for person in (member, guest, stranger):
        clients[person.email] = new_client()
        assert login(clients[person.email], person).status_code == 200
    assert login(client, owner).status_code == 200
    rows = client.get(ALL).json()
    # Not other homes' people (SEC-11).
    assert {r["user"] for r in rows} == {owner.email, member.email, guest.email}
    mine = [r for r in rows if r["current"]]
    assert [r["user"] for r in mine] == [owner.email]
    theirs = next(r for r in rows if r["user"] == member.email)
    assert (
        client.delete(f"{ALL}/{theirs['id']}", headers=csrf(client)).status_code == 200
    )
    assert member.email not in {r["user"] for r in client.get(ALL).json()}
    # Another home's admin's session cannot be ended from here.
    elsewhere = clients[stranger.email]
    theirs = next(r for r in elsewhere.get(ALL).json() if r["user"] == stranger.email)
    assert (
        client.delete(f"{ALL}/{theirs['id']}", headers=csrf(client)).status_code == 404
    )


def test_only_admins(new_client, owner, make_user, login):
    member = make_user(owner.home_id, role="member")
    c = new_client()
    assert login(c, member).status_code == 200
    assert c.get(ALL).status_code == 403


def test_ui_admin_devices_tabs(open_page, new_client, owner, make_user, login):
    member = make_user(owner.home_id, role="member")
    assert _times.remember_login(new_client(), member).status_code == 200
    page = open_page()
    _ui.ui_login(page, owner)
    _ui.go_settings(page, "admin")
    box = page.get_by_test_id("admin-devices")
    # Approved devices first: the member's.
    expect(box.get_by_test_id("trusted-device")).to_contain_text(member.email)
    box.get_by_test_id("admin-devices-tab-sessions").click()
    rows = box.get_by_test_id("admin-session")
    expect(rows.filter(has_text=member.email)).to_have_count(1)
    expect(rows.filter(has_text="This device")).to_have_count(1)
    rows.filter(has_text=member.email).get_by_test_id("admin-session-end").click()
    expect(page.get_by_test_id("status")).to_contain_text("was logged out there")
    expect(rows.filter(has_text=member.email)).to_have_count(0)
