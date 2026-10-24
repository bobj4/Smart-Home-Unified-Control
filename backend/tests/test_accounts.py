"""First-start admin account, optional passwords, admins setting members'
passwords. Written by the reviewer (accounts phase). Do not edit, skip, mark
or delete these tests. If one looks wrong, stop and report the test name and
its full failure output instead of changing it.
"""

from playwright.sync_api import expect

from app.bootstrap import ensure_default_admin
from app.login_policy import settings
from app.models import AuditEvent, HomeMembership, User
from app.models import Session as SessionModel
from tests import test_admin as _admin
from tests import test_ui as _ui

create, password_login, set_policy = (
    _admin.create,
    _admin.password_login,
    _admin.set_policy,
)
go_settings, ui_login = _ui.go_settings, _ui.ui_login


def test_first_start_creates_admin(client, db):
    assert db.query(User).count() == 0
    assert ensure_default_admin(db) is True
    assert ensure_default_admin(db) is False  # only once
    user = db.query(User).one()
    assert user.email == "admin" and user.is_totp_enabled is False
    assert db.query(HomeMembership).one().role in ("owner", "admin")
    assert settings(db).require_email is False
    r = password_login(client, "admin", "admin")
    assert r.status_code == 200, r.text
    assert client.get("/api/v1/account").status_code == 200


def test_no_password_when_rules_allow(client, new_client, owner, login, csrf):
    assert login(client, owner).status_code == 200
    assert (
        create(
            client, csrf, owner.home_id, "nopass@example.com", password=""
        ).status_code
        == 422
    )
    assert set_policy(client, csrf, password={"min_length": 0}).status_code == 200
    r = create(client, csrf, owner.home_id, "nopass@example.com", password="")
    assert r.status_code == 201, r.text
    guest = new_client()
    assert password_login(guest, "nopass@example.com", "").status_code == 200
    assert password_login(new_client(), "nopass@example.com", "x").status_code == 401


def test_admin_sets_member_passwords(
    client, new_client, db, owner, make_user, login, csrf
):
    home = owner.home_id
    admin = make_user(home, role="admin")
    other_admin = make_user(home, role="admin")
    member = make_user(home, role="member")
    operator = make_user(home, role="operator")
    a = new_client()
    assert login(a, admin).status_code == 200
    m = new_client()
    assert login(m, member).status_code == 200

    def set_pw(c, target, password="a new password 12"):
        return c.post(
            f"/api/v1/homes/{home}/members/{target.id}/password",
            json={"password": password},
            headers=csrf(c),
        )

    assert set_pw(a, member).status_code == 200
    assert db.query(SessionModel).filter_by(user_id=member.id).count() == 0
    assert m.get("/api/v1/account").status_code == 401  # logged out
    assert password_login(
        new_client(), member.email, "a new password 12"
    ).status_code in (
        200,
        401,  # 401 only if the member still has two-factor on (needs a code)
    )
    assert set_pw(a, operator).status_code == 200
    assert set_pw(a, other_admin).status_code == 403
    assert set_pw(a, owner).status_code == 403
    assert set_pw(a, admin).status_code == 409  # own: My account
    assert set_pw(a, member, password="short").status_code == 422  # rules apply
    m2 = new_client()
    member2 = make_user(home, role="member")
    assert login(m2, member2).status_code == 200
    assert set_pw(m2, operator).status_code == 403  # members cannot
    events = db.query(AuditEvent).filter_by(event_type="member_password_set").all()
    assert len(events) == 2
    assert all("a new password" not in (e.details or "") for e in events)


def test_ui_admin_sets_password(open_page, owner, make_user, new_client):
    admin = make_user(owner.home_id, role="admin")
    member = make_user(owner.home_id, role="member")
    page = open_page()
    ui_login(page, admin)
    section = go_settings(page, "members")
    row = section.locator(f'[data-testid="member-row"][data-user-id="{member.id}"]')
    row.get_by_test_id("member-set-password").click()
    row.get_by_test_id("member-new-password").fill("another password 12")
    row.get_by_test_id("member-password-save").click()
    expect(page.get_by_test_id("status")).to_have_attribute("data-kind", "success")
    owner_row = section.locator(
        f'[data-testid="member-row"][data-user-id="{owner.id}"]'
    )
    expect(owner_row.get_by_test_id("member-set-password")).to_have_count(0)


def test_removed_user_login_can_be_used_again(
    client, new_client, db, owner, login, csrf
):
    assert login(client, owner).status_code == 200
    r = create(client, csrf, owner.home_id, "again@example.com")
    assert r.status_code == 201, r.text
    user_id = r.json()["user_id"]
    guest = new_client()
    assert (
        password_login(guest, "again@example.com", "a good password 12").status_code
        == 200
    )
    r = client.delete(
        f"/api/v1/homes/{owner.home_id}/members/{user_id}", headers=csrf(client)
    )
    assert r.status_code == 200
    assert guest.get("/api/v1/account").status_code == 401  # logged out
    assert (
        password_login(
            new_client(), "again@example.com", "a good password 12"
        ).status_code
        == 401
    )
    r = create(client, csrf, owner.home_id, "again@example.com")
    assert r.status_code == 201, r.text  # the same login works again
    assert r.json()["user_id"] != user_id
