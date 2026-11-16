"""Names and logins: admins edit members' details (a login only when they run
every home the person is in); people edit their own when an admin allows it
(their password for a new login)."""

from playwright.sync_api import expect

from app.models import AuditEvent, User
from tests import test_ui as _ui

LOGIN = "/api/v1/auth/login"


def info_url(home_id, user_id):
    return f"/api/v1/homes/{home_id}/members/{user_id}/info"


def test_admin_edits_member(
    client, db, owner, make_user, make_home, new_client, login, csrf
):
    member = make_user(owner.home_id, role="member")
    assert login(client, owner).status_code == 200
    r = client.put(
        info_url(owner.home_id, member.id),
        json={"name": " Sam ", "email": "Sam.New@Example.com"},
        headers=csrf(client),
    )
    assert r.status_code == 200, r.text
    assert r.json() == {
        "user_id": member.id,
        "email": "sam.new@example.com",
        "name": "Sam",
    }
    # They log in with the new login.
    m = new_client()
    r = m.post(
        LOGIN,
        json={
            "email": "sam.new@example.com",
            "password": member.password,
            "totp_code": member.totp.now(),
        },
    )
    assert r.status_code == 200, r.text
    # Taken logins are refused; members cannot edit others.
    r = client.put(
        info_url(owner.home_id, member.id),
        json={"email": owner.email},
        headers=csrf(client),
    )
    assert r.status_code == 409
    assert (
        m.put(
            info_url(owner.home_id, owner.id),
            json={"email": "x@example.com"},
            headers=csrf(m),
        ).status_code
        == 403
    )
    # Someone also in another home this admin does not run: name yes, login no.
    other_home = make_home("Cabin")
    shared = make_user(owner.home_id, role="member")
    from app.models import HomeMembership

    db.add(HomeMembership(home_id=other_home, user_id=shared.id, role="member"))
    db.commit()
    r = client.put(
        info_url(owner.home_id, shared.id),
        json={"name": "Pat", "email": shared.email},
        headers=csrf(client),
    )
    assert r.status_code == 200
    r = client.put(
        info_url(owner.home_id, shared.id),
        json={"email": "pat@example.com"},
        headers=csrf(client),
    )
    assert r.status_code == 403
    assert db.query(AuditEvent).filter_by(event_type="member_info_changed").count() == 2


def test_own_details_need_permission_and_password(
    client, db, owner, make_user, new_client, login, csrf
):
    member = make_user(owner.home_id, role="member")
    m = new_client()
    assert login(m, member).status_code == 200
    body = {"name": "Me", "email": member.email}
    assert m.put("/api/v1/account/info", json=body, headers=csrf(m)).status_code == 403
    assert m.get("/api/v1/account").json()["can_edit_info"] is False
    assert login(client, owner).status_code == 200
    assert (
        m.put(
            "/api/v1/admin/self-edit", json={"allowed": True}, headers=csrf(m)
        ).status_code
        == 403
    )
    r = client.put(
        "/api/v1/admin/self-edit", json={"allowed": True}, headers=csrf(client)
    )
    assert r.json() == {"allowed": True}
    assert m.get("/api/v1/account").json()["can_edit_info"] is True
    r = m.put("/api/v1/account/info", json=body, headers=csrf(m))
    assert r.status_code == 200 and r.json()["name"] == "Me"  # no password for a name
    new = {"name": "Me", "email": "me2@example.com"}
    assert m.put("/api/v1/account/info", json=new, headers=csrf(m)).status_code == 403
    r = m.put(
        "/api/v1/account/info", json={**new, "password": "wrong"}, headers=csrf(m)
    )
    assert r.status_code == 403
    r = m.put(
        "/api/v1/account/info",
        json={**new, "password": member.password},
        headers=csrf(m),
    )
    assert r.status_code == 200 and r.json()["email"] == "me2@example.com"
    db.expire_all()
    assert db.get(User, member.id).email == "me2@example.com"


def test_ui_edit_member_and_own_details(open_page, db, owner, make_user):
    member = make_user(owner.home_id, role="member")
    page = open_page()
    _ui.ui_login(page, owner)
    _ui.go_settings(page, "members")
    row = page.locator(f'[data-testid="member-row"][data-user-id="{member.id}"]')
    row.get_by_test_id("member-edit").click()
    form = page.get_by_test_id("member-edit-form")
    form.get_by_test_id("member-edit-name").fill("Sam Lee")
    form.get_by_test_id("member-edit-save").click()
    expect(
        page.locator(f'[data-testid="member-row"][data-user-id="{member.id}"]')
    ).to_contain_text("Sam Lee")

    _ui.go_settings(page, "admin")
    users = page.get_by_test_id("settings-members")  # under Users, a toggle
    expect(users.get_by_test_id("self-edit")).to_have_attribute("role", "switch")
    users.get_by_test_id("self-edit").check()
    expect(page.get_by_test_id("status")).to_contain_text("can now change")
    other = open_page()
    _ui.ui_login(other, member)
    box = _ui.go_settings(other, "account").get_by_test_id("own-info")
    expect(box.get_by_test_id("own-password")).to_be_hidden()
    box.get_by_test_id("own-email").fill("sam@example.com")
    expect(box.get_by_test_id("own-password")).to_be_visible()
    box.get_by_test_id("own-password").fill(member.password)
    box.get_by_test_id("own-info-save").click()
    expect(other.get_by_test_id("status")).to_contain_text("Your details are saved")
    db.expire_all()
    assert db.get(User, member.id).email == "sam@example.com"
