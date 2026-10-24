"""Admin settings: login rules, home name, users without a code, recovery.

Written by the reviewer. Do not edit, skip, mark or delete these tests. If
one looks wrong, stop and report the test name and its full failure output
instead of changing it.
"""

import time

import pyotp
from playwright.sync_api import expect

from app.auth import verify_password
from app.models import AuditEvent, Home, HomeMembership, PasswordReset, User
from tests import test_ui as _ui

go_settings, ui_login = _ui.go_settings, _ui.ui_login
POLICY = "/api/v1/admin/login-policy"
DEFAULT = {
    "require_email": True,
    "allow_recovery": False,
    "password": {
        "min_length": 12,
        "upper": False,
        "lower": False,
        "digit": False,
        "special": False,
    },
}


def set_policy(client, csrf, **changes):
    body = {**DEFAULT, **changes}
    if "password" in changes:
        body["password"] = {**DEFAULT["password"], **changes["password"]}
    return client.put(POLICY, json=body, headers=csrf(client))


def create(
    client, csrf, home_id, login_name, password="a good password 12", role="member"
):
    return client.post(
        f"/api/v1/homes/{home_id}/members",
        json={"login": login_name, "role": role, "password": password},
        headers=csrf(client),
    )


def password_login(client, login_name, password):
    return client.post(
        "/api/v1/auth/login", json={"email": login_name, "password": password}
    )


# ------------------------------------------------------------ login rules


def test_login_options_are_public(client):
    r = client.get("/api/v1/login-options")
    assert r.status_code == 200 and r.json() == {**DEFAULT, "email_recovery": False}


def test_only_owners_change_login_rules(
    client, new_client, db, owner, make_user, login, csrf
):
    admin = make_user(owner.home_id, role="operator")
    a = new_client()
    assert login(a, admin).status_code == 200
    assert a.get(POLICY).status_code == 403
    assert set_policy(a, csrf, require_email=False).status_code == 403

    assert login(client, owner).status_code == 200
    assert client.put(POLICY, json=DEFAULT).status_code == 403  # no CSRF
    for bad in (
        {"password": {"min_length": -1}},
        {"password": {"min_length": 17}},
        {"password": {"min_length": 128}},
        {"require_email": "no"},
    ):
        assert set_policy(client, csrf, **bad).status_code == 422, bad
    r = set_policy(
        client,
        csrf,
        require_email=False,
        allow_recovery=True,
        password={"min_length": 8, "digit": True},
    )
    assert r.status_code == 200
    assert r.json()["password"] == {
        "min_length": 8,
        "upper": False,
        "lower": False,
        "digit": True,
        "special": False,
    }
    assert client.get("/api/v1/login-options").json()["require_email"] is False
    assert (
        db.query(AuditEvent).filter_by(event_type="login_policy_changed").count() == 1
    )


def test_password_rules_apply_everywhere(client, new_client, owner, login, csrf):
    assert login(client, owner).status_code == 200
    rules = {
        "min_length": 10,
        "upper": True,
        "lower": True,
        "digit": True,
        "special": True,
    }
    assert set_policy(client, csrf, password=rules).status_code == 200
    r = create(client, csrf, owner.home_id, "weak@example.com", password="alllowercase")
    assert r.status_code == 422
    for needed in ("an uppercase letter", "a number", "a special character"):
        assert needed in r.json()["detail"]
    assert (
        create(
            client, csrf, owner.home_id, "ok@example.com", password="Str0ng!pass"
        ).status_code
        == 201
    )
    change = {"current_password": owner.password, "new_password": "Short1!"}
    assert (
        client.post(
            "/api/v1/account/password", json=change, headers=csrf(client)
        ).status_code
        == 422
    )
    change["new_password"] = "Longer1!pass"
    assert (
        client.post(
            "/api/v1/account/password", json=change, headers=csrf(client)
        ).status_code
        == 200
    )

    assert set_policy(client, csrf, password={"min_length": 8}).status_code == 200
    assert set_policy(client, csrf, password={"min_length": 0}).status_code == 200
    assert set_policy(client, csrf, password={"min_length": 16}).status_code == 200
    assert set_policy(client, csrf, password={"min_length": 8}).status_code == 200
    change = {"current_password": "Longer1!pass", "new_password": "eightchr"}
    assert (
        client.post(
            "/api/v1/account/password", json=change, headers=csrf(client)
        ).status_code
        == 200
    )


def test_usernames_only_when_email_not_required(
    client, new_client, db, owner, login, csrf
):
    assert login(client, owner).status_code == 200
    r = create(client, csrf, owner.home_id, "kid_room")
    assert r.status_code == 422 and "email" in r.json()["detail"].lower()
    assert set_policy(client, csrf, require_email=False).status_code == 200
    assert (
        create(client, csrf, owner.home_id, "a b").status_code == 422
    )  # not a valid username
    r = create(client, csrf, owner.home_id, "Kid_Room")
    assert r.status_code == 201 and r.json()["login"] == "kid_room"
    assert (
        password_login(new_client(), "KID_ROOM", "a good password 12").status_code
        == 200
    )
    invite = client.post(
        f"/api/v1/homes/{owner.home_id}/members/enrollments",
        json={"email": "grandma", "role": "member"},
        headers=csrf(client),
    )
    assert invite.status_code == 201  # enrollment codes for usernames too


# ------------------------------------------------------------ home and users


def test_owner_renames_home(client, new_client, db, owner, make_user, login, csrf):
    admin = make_user(owner.home_id, role="operator")
    a = new_client()
    assert login(a, admin).status_code == 200
    url = f"/api/v1/homes/{owner.home_id}"
    assert a.patch(url, json={"name": "X"}, headers=csrf(a)).status_code == 403
    assert login(client, owner).status_code == 200
    assert client.patch(url, json={"name": ""}, headers=csrf(client)).status_code == 422
    assert (
        client.patch(url, json={"name": "   "}, headers=csrf(client)).status_code == 422
    )
    r = client.patch(url, json={"name": "Lake House"}, headers=csrf(client))
    assert r.status_code == 200 and r.json()["name"] == "Lake House"
    db.expire_all()
    assert db.get(Home, owner.home_id).name == "Lake House"
    assert client.get("/api/v1/homes").json()[0]["name"] == "Lake House"
    assert db.query(AuditEvent).filter_by(event_type="home_renamed").count() == 1


def test_owner_creates_user_without_code(
    client, new_client, db, owner, make_user, login, csrf
):
    admin = make_user(owner.home_id, role="operator")
    a = new_client()
    assert login(a, admin).status_code == 200
    assert create(a, csrf, owner.home_id, "new@example.com").status_code == 403
    assert login(client, owner).status_code == 200
    assert (
        create(client, csrf, owner.home_id, "new@example.com", role="owner").status_code
        == 422
    )
    r = create(client, csrf, owner.home_id, "New@Example.com", role="admin")
    assert r.status_code == 201, r.text
    assert create(client, csrf, owner.home_id, "new@example.com").status_code == 409
    assert create(client, csrf, owner.home_id, owner.email).status_code == 409

    db.expire_all()
    user = db.query(User).filter_by(email="new@example.com").one()
    assert user.is_totp_enabled is False
    membership = db.query(HomeMembership).filter_by(user_id=user.id).one()
    assert (membership.home_id, membership.role) == (owner.home_id, "admin")
    events = db.query(AuditEvent).filter_by(event_type="member_created").all()
    assert events and "a good password" not in (events[-1].details or "")
    assert (
        password_login(
            new_client(), "new@example.com", "a good password 12"
        ).status_code
        == 200
    )


# ------------------------------------------------------------ recovery


def reset_code(client, csrf, home_id, user_id):
    return client.post(
        f"/api/v1/homes/{home_id}/members/{user_id}/reset-code", headers=csrf(client)
    )


def recover(client, login_name, code, new_password="a fresh password 34"):
    return client.post(
        "/api/v1/recover",
        json={"login": login_name, "code": code, "new_password": new_password},
    )


def test_recovery_is_off_by_default(client, new_client, owner, make_user, login, csrf):
    member = make_user(owner.home_id, role="member")
    assert login(client, owner).status_code == 200
    assert reset_code(client, csrf, owner.home_id, member.id).status_code == 409
    assert recover(new_client(), member.email, "AAAA-BBBB-CCCC-DDDD").status_code == 404


def test_recovery_with_a_reset_code(
    client, new_client, db, owner, make_user, login, csrf
):
    member = make_user(owner.home_id, role="member")
    other_owner = make_user(owner.home_id, role="owner")
    member_client = new_client()
    assert login(member_client, member).status_code == 200
    assert login(client, owner).status_code == 200
    assert set_policy(client, csrf, allow_recovery=True).status_code == 200

    assert (
        reset_code(client, csrf, owner.home_id, owner.id).status_code == 409
    )  # yourself
    assert (
        reset_code(client, csrf, owner.home_id, other_owner.id).status_code == 409
    )  # another owner
    r = reset_code(client, csrf, owner.home_id, member.id)
    assert r.status_code == 200, r.text
    code = r.json()["reset_code"]
    assert code not in (db.query(PasswordReset).one().code_hash)

    guest = new_client()
    assert recover(guest, member.email, "AAAA-BBBB-CCCC-DDDD").status_code == 404
    assert recover(guest, owner.email, code).status_code == 404  # someone else's code
    assert recover(guest, member.email, code, new_password="short").status_code == 422
    r = recover(guest, member.email.upper(), code.lower())
    assert r.status_code == 200, r.text
    assert recover(guest, member.email, code).status_code == 404  # works once

    db.expire_all()
    user = db.get(User, member.id)
    assert verify_password("a fresh password 34", user.hashed_password)
    assert user.is_totp_enabled is False
    assert member_client.get("/api/v1/account").status_code == 401  # sessions ended
    assert (
        password_login(new_client(), member.email, "a fresh password 34").status_code
        == 200
    )
    assert db.query(AuditEvent).filter_by(event_type="password_recovered").count() == 1


def test_turning_recovery_off_cancels_codes(
    client, new_client, owner, make_user, login, csrf
):
    member = make_user(owner.home_id, role="member")
    assert login(client, owner).status_code == 200
    assert set_policy(client, csrf, allow_recovery=True).status_code == 200
    code = reset_code(client, csrf, owner.home_id, member.id).json()["reset_code"]
    assert set_policy(client, csrf, allow_recovery=False).status_code == 200
    assert set_policy(client, csrf, allow_recovery=True).status_code == 200
    assert recover(new_client(), member.email, code).status_code == 404


# ------------------------------------------------------------ browser


def test_ui_admin_tab(open_page, db, owner, make_user):
    page = open_page()
    ui_login(page, owner)
    section = go_settings(page, "admin")
    section.get_by_test_id("home-name-input").fill("Lake House")
    section.get_by_test_id("home-name-save").click()
    expect(page.get_by_test_id("status")).to_have_attribute("data-kind", "success")
    expect(page.get_by_test_id("home-name")).to_have_text("Lake House")

    section.get_by_test_id("require-2fa-toggle").check()
    expect(page.get_by_test_id("status")).to_have_attribute("data-kind", "success")
    db.expire_all()
    assert db.get(Home, owner.home_id).require_two_factor is True

    section.get_by_test_id("require-email-toggle").uncheck()
    section.get_by_test_id("allow-recovery-toggle").check()
    section.get_by_test_id("pw-min-length").fill("10")
    section.get_by_test_id("pw-digit").check()
    section.get_by_test_id("login-policy-save").click()
    expect(page.get_by_test_id("status")).to_have_attribute("data-kind", "success")
    from app.login_policy import settings

    db.expire_all()
    row = settings(db)
    assert (
        row.require_email,
        row.allow_recovery,
        row.password_min_length,
        row.password_digit,
    ) == (False, True, 10, True)

    admin = make_user(owner.home_id, role="operator")
    admin_page = open_page()
    ui_login(
        admin_page, admin, code=pyotp.TOTP(admin.totp_secret).at(int(time.time()) + 30)
    )
    admin_page.get_by_test_id("nav-settings").click()
    expect(admin_page.get_by_test_id("settings-nav-admin")).to_have_count(0)


def test_ui_create_user_and_log_in_with_username(
    open_page, new_client, owner, login, csrf
):
    c = new_client()
    assert login(c, owner).status_code == 200
    assert set_policy(c, csrf, require_email=False).status_code == 200
    page = open_page()
    ui_login(page, owner, code=pyotp.TOTP(owner.totp_secret).at(int(time.time()) + 30))
    section = go_settings(page, "members")
    section.get_by_test_id("create-login").fill("guest_room")
    section.get_by_test_id("create-role").select_option("member")
    section.get_by_test_id("create-password").fill("a good password 12")
    section.get_by_test_id("create-submit").click()
    expect(page.get_by_test_id("status")).to_have_attribute("data-kind", "success")
    expect(
        section.get_by_test_id("member-row").filter(has_text="guest_room")
    ).to_have_count(1)

    guest = open_page()
    expect(guest.locator("#login-name-label")).to_have_text("Email or username")
    guest.get_by_test_id("login-email").fill("guest_room")
    guest.get_by_test_id("login-password").fill("a good password 12")
    guest.get_by_test_id("login-submit").click()
    expect(guest.get_by_test_id("app-shell")).to_be_visible()


def test_ui_password_recovery(open_page, new_client, owner, make_user, login, csrf):
    member = make_user(owner.home_id, role="member")
    c = new_client()
    assert login(c, owner).status_code == 200
    assert set_policy(c, csrf, allow_recovery=True).status_code == 200
    page = open_page()
    ui_login(page, owner, code=pyotp.TOTP(owner.totp_secret).at(int(time.time()) + 30))
    row = go_settings(page, "members").locator(
        f'[data-testid="member-row"][data-user-id="{member.id}"]'
    )
    row.get_by_test_id("member-reset").click()
    code_box = row.get_by_test_id("member-reset-code")
    expect(code_box).to_be_visible()
    code = code_box.inner_text()

    guest = open_page()
    guest.get_by_test_id("recover-link").click()
    expect(guest.get_by_test_id("recover-page")).to_be_visible()
    expect(guest.get_by_test_id("recover-rules")).to_contain_text(
        "at least 12 characters"
    )
    guest.get_by_test_id("recover-login").fill(member.email)
    guest.get_by_test_id("recover-code").fill(code)
    guest.get_by_test_id("recover-password").fill("a fresh password 34")
    guest.get_by_test_id("recover-password-confirm").fill("a fresh password 34")
    guest.get_by_test_id("recover-submit").click()
    expect(guest.get_by_test_id("recover-done")).to_be_visible()
    assert (
        password_login(new_client(), member.email, "a fresh password 34").status_code
        == 200
    )


def test_ui_recovery_link_hidden_when_off(open_page):
    page = open_page()
    expect(page.get_by_test_id("login-form")).to_be_visible()
    expect(page.get_by_test_id("recover-link")).to_be_hidden()
    expect(page.locator("#login-name-label")).to_have_text("Email")
