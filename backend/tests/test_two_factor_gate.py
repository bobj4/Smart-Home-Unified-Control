"""Required two-factor login: the first login needs only the password, but
until an authenticator is set up the person sees only the setup page and the
server refuses every home request. Turning it on for the first time also
makes recovery codes."""

import pyotp
from playwright.sync_api import expect

from app.models import AuditEvent, Home, User
from tests import test_ui as _ui

ACCOUNT = "/api/v1/account"
LOGIN = "/api/v1/auth/login"


def without_two_factor(db, person):
    user = db.get(User, person.id)
    user.is_totp_enabled = False
    user.totp_secret = None
    user.recovery_codes = None
    db.commit()


def require(db, home_id, on=True):
    db.get(Home, home_id).require_two_factor = on
    db.commit()


def password_login(client, person):
    return client.post(LOGIN, json={"email": person.email, "password": person.password})


def turn_on(client, csrf, person):
    r = client.post(
        f"{ACCOUNT}/totp/setup",
        json={"password": person.password},
        headers=csrf(client),
    )
    assert r.status_code == 200, r.text
    secret = r.json()["secret"]
    r = client.post(
        f"{ACCOUNT}/totp/confirm",
        json={"totp_code": pyotp.TOTP(secret).now()},
        headers=csrf(client),
    )
    assert r.status_code == 200, r.text
    return secret, r.json()


def test_setup_required_flag(client, db, owner, make_user, new_client, login):
    member = make_user(owner.home_id, role="member")
    without_two_factor(db, member)
    member_client = new_client()
    assert password_login(member_client, member).status_code == 200
    assert member_client.get(ACCOUNT).json()["two_factor_setup_required"] is False
    require(db, owner.home_id)
    body = member_client.get(ACCOUNT).json()
    assert body["two_factor_required"] is True
    assert body["two_factor_setup_required"] is True
    devices = f"/api/v1/homes/{owner.home_id}/devices"
    assert member_client.get(devices).status_code == 403
    # Someone who has it on is not asked.
    assert login(client, owner).status_code == 200
    assert client.get(ACCOUNT).json()["two_factor_setup_required"] is False


def test_first_setup_makes_recovery_codes(db, owner, make_user, new_client, csrf):
    member = make_user(owner.home_id, role="member")
    without_two_factor(db, member)
    require(db, owner.home_id)
    member_client = new_client()
    assert password_login(member_client, member).status_code == 200
    _, done = turn_on(member_client, csrf, member)
    codes = done["recovery_codes"]
    assert len(codes) >= 8 and len(set(codes)) == len(codes)
    assert member_client.get(ACCOUNT).json()["two_factor_setup_required"] is False
    assert (
        member_client.get(f"/api/v1/homes/{owner.home_id}/devices").status_code == 200
    )
    events = [e.event_type for e in db.query(AuditEvent).all()]
    assert "totp_enabled" in events
    # A recovery code now logs in, once; the password alone no longer does.
    fresh = new_client()
    assert password_login(fresh, member).status_code == 401
    r = fresh.post(
        LOGIN,
        json={
            "email": member.email,
            "password": member.password,
            "recovery_code": codes[0],
        },
    )
    assert r.status_code == 200, r.text


def test_replacing_an_authenticator_keeps_the_codes(client, owner, login, csrf):
    assert login(client, owner).status_code == 200
    _, done = turn_on(client, csrf, owner)
    assert "recovery_codes" not in done
    assert done["detail"] == "Authenticator replaced"
    fresh_login = client.post(
        LOGIN,
        json={
            "email": owner.email,
            "password": owner.password,
            "recovery_code": owner.recovery_codes[0],
        },
    )
    assert fresh_login.status_code == 200


def test_ui_required_two_factor_gate(open_page, db, owner, make_user, make_device):
    make_device(owner.home_id, name="Lamp")
    member = make_user(owner.home_id, role="member")
    without_two_factor(db, member)
    require(db, owner.home_id)
    page = open_page()
    page.get_by_test_id("login-email").fill(member.email)
    page.get_by_test_id("login-password").fill(member.password)
    page.get_by_test_id("login-submit").click()  # no code needed
    gate = page.get_by_test_id("twofactor-page")
    expect(gate).to_be_visible()
    expect(page.get_by_test_id("app-shell")).to_be_hidden()

    page.get_by_test_id("gate-password").fill("not the password")
    page.get_by_test_id("gate-start").click()
    expect(page.get_by_test_id("gate-error")).to_contain_text("Password is incorrect")
    page.get_by_test_id("gate-password").fill(member.password)
    page.get_by_test_id("gate-start").click()
    expect(page.get_by_test_id("gate-qr")).to_be_visible()
    secret = page.get_by_test_id("gate-secret").inner_text().replace(" ", "")
    page.get_by_test_id("gate-code").fill(
        "000000" if pyotp.TOTP(secret).now() != "000000" else "111111"
    )
    page.get_by_test_id("gate-confirm").click()
    expect(page.get_by_test_id("gate-error")).to_contain_text("Code does not match")
    page.get_by_test_id("gate-code").fill(pyotp.TOTP(secret).now())
    page.get_by_test_id("gate-confirm").click()
    expect(page.get_by_test_id("gate-recovery-codes").locator("li")).not_to_have_count(
        0
    )

    page.get_by_test_id("gate-continue").click()
    expect(page.get_by_test_id("app-shell")).to_be_visible()
    expect(_ui.card(page, "Lamp")).to_be_visible()
    expect(gate).to_be_hidden()

    # Next time, the code is needed.
    page.get_by_test_id("logout").click()
    page.get_by_test_id("login-email").fill(member.email)
    page.get_by_test_id("login-password").fill(member.password)
    page.get_by_test_id("login-submit").click()
    expect(page.get_by_test_id("login-error")).to_contain_text("Login failed")


def test_ui_no_gate_when_not_required(open_page, db, owner, make_user, make_device):
    make_device(owner.home_id, name="Lamp")
    member = make_user(owner.home_id, role="member")
    without_two_factor(db, member)
    page = open_page()
    page.get_by_test_id("login-email").fill(member.email)
    page.get_by_test_id("login-password").fill(member.password)
    page.get_by_test_id("login-submit").click()
    expect(page.get_by_test_id("app-shell")).to_be_visible()
    expect(_ui.card(page, "Lamp")).to_be_visible()
    expect(page.get_by_test_id("twofactor-page")).to_be_hidden()


def test_ui_gate_log_out(open_page, db, owner, make_user):
    member = make_user(owner.home_id, role="member")
    without_two_factor(db, member)
    require(db, owner.home_id)
    page = open_page()
    page.get_by_test_id("login-email").fill(member.email)
    page.get_by_test_id("login-password").fill(member.password)
    page.get_by_test_id("login-submit").click()
    page.get_by_test_id("gate-logout").click()
    expect(page.get_by_test_id("login-page")).to_be_visible()
    expect(page.get_by_test_id("twofactor-page")).to_be_hidden()
