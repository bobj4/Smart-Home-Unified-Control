"""After repeated failed logins: none, lockout (for a time, or until the
password is reset) or lockdown (account off until an admin turns it on)."""

from datetime import UTC, datetime, timedelta

from playwright.sync_api import expect

from app.login_policy import settings
from app.models import AuditEvent, User
from tests import test_ui as _ui

LOGIN = "/api/v1/auth/login"
RULES = "/api/v1/admin/login-failures"


def rule(db, action, limit=3, minutes=15):
    row = settings(db)
    row.login_failure_action, row.login_failure_limit, row.login_lockout_minutes = (
        action,
        limit,
        minutes,
    )
    db.commit()


def attempt(client, person, password=None, code=None):
    return client.post(
        LOGIN,
        json={
            "email": person.email,
            "password": person.password if password is None else password,
            "totp_code": code or person.totp.now(),
        },
    )


def fail(client, person, times):
    for _ in range(times):
        assert attempt(client, person, password="wrong password").status_code == 401


def test_default_is_none(client, db, owner, new_client):
    fail(new_client(), owner, 4)
    db.expire_all()
    assert db.get(User, owner.id).locked_until is None
    assert attempt(new_client(), owner).status_code == 200


def test_lockout_for_a_time(client, db, owner, new_client):
    rule(db, "lockout", limit=3, minutes=15)
    fail(new_client(), owner, 3)
    r = attempt(new_client(), owner)  # the right password, but locked
    assert r.status_code == 403 and "Try again in 15 minutes" in r.json()["detail"]
    assert (
        attempt(new_client(), owner, password="nope").status_code == 401
    )  # says nothing
    db.expire_all()
    user = db.get(User, owner.id)
    user.locked_until = datetime.now(UTC) - timedelta(seconds=1)  # time is up
    db.commit()
    assert (
        attempt(
            new_client(),
            owner,
            code=owner.totp.at(datetime.now() + timedelta(seconds=30)),
        ).status_code
        == 200
    )
    assert db.query(AuditEvent).filter_by(event_type="account_locked").count() == 1


def test_lockout_until_password_reset(client, db, owner, new_client):
    rule(db, "lockout", limit=2, minutes=0)
    fail(new_client(), owner, 2)
    r = attempt(new_client(), owner)
    assert r.status_code == 403 and "reset its password" in r.json()["detail"]
    db.expire_all()
    from app.auth import hash_password

    db.get(User, owner.id).hashed_password = hash_password(owner.password)  # a reset
    db.commit()
    assert attempt(new_client(), owner).status_code == 200


def test_correct_login_starts_the_count_again(client, db, owner, new_client):
    rule(db, "lockout", limit=3)
    fail(new_client(), owner, 2)
    assert attempt(new_client(), owner).status_code == 200
    fail(new_client(), owner, 2)
    db.expire_all()
    assert db.get(User, owner.id).locked_until is None


def test_lockdown_turns_the_account_off(
    client, db, owner, make_user, new_client, login, csrf
):
    member = make_user(owner.home_id, role="member")
    rule(db, "lockdown", limit=2)
    fail(new_client(), member, 2)
    db.expire_all()
    assert db.get(User, member.id).is_active is False
    assert attempt(new_client(), member).status_code == 401
    assert login(client, owner).status_code == 200
    r = client.put(
        f"/api/v1/homes/{owner.home_id}/members/{member.id}/active",
        json={"active": True},
        headers=csrf(client),
    )
    assert r.status_code == 200, r.text
    assert attempt(new_client(), member).status_code == 200


def test_blank_limit_turns_the_rule_off(client, db, owner, new_client):
    rule(db, "lockdown", limit=None)
    fail(new_client(), owner, 4)
    db.expire_all()
    assert db.get(User, owner.id).is_active is True


def test_rules_api(client, owner, make_user, new_client, login, csrf):
    assert login(client, owner).status_code == 200
    assert client.get(RULES).json() == {
        "action": "none",
        "limit": 10,
        "lockout_minutes": 15,
    }
    for good in (
        {"action": "lockout", "limit": 5, "lockout_minutes": 0},
        {"action": "lockdown", "limit": 500, "lockout_minutes": None},
        {"action": "none", "limit": None, "lockout_minutes": None},
    ):
        r = client.put(RULES, json=good, headers=csrf(client))
        assert r.status_code == 200 and r.json() == good
    for bad in (
        {"action": "ban", "limit": 5, "lockout_minutes": 1},
        {"action": "lockout", "limit": 0, "lockout_minutes": 1},
        {"action": "lockout", "limit": 5, "lockout_minutes": -1},
        {"action": "lockout", "limit": "5", "lockout_minutes": 1},
    ):
        assert client.put(RULES, json=bad, headers=csrf(client)).status_code == 422
    member = make_user(owner.home_id, role="member")
    m = new_client()
    assert login(m, member).status_code == 200
    assert m.get(RULES).status_code == 403


def test_ui_rule_and_locked_message(open_page, db, owner, make_user):
    member = make_user(owner.home_id, role="member")
    page = open_page()
    _ui.ui_login(page, owner)
    _ui.go_settings(page, "admin")
    panel = page.get_by_test_id("login-failures")
    expect(panel.get_by_test_id("failure-minutes")).to_be_hidden()  # action none
    panel.get_by_test_id("failure-action").select_option("lockout")
    expect(panel.get_by_test_id("failure-minutes")).to_be_visible()
    panel.get_by_test_id("failure-limit").fill("2")
    panel.get_by_test_id("failure-minutes").fill("30")
    panel.get_by_test_id("failure-save").click()
    expect(page.get_by_test_id("status")).to_contain_text("Failed-login rule saved")
    db.expire_all()
    assert settings(db).login_failure_action == "lockout"

    other = open_page()
    for _ in range(2):
        other.get_by_test_id("login-email").fill(member.email)
        other.get_by_test_id("login-password").fill("wrong password")
        other.get_by_test_id("login-code").fill(member.totp.now())
        other.get_by_test_id("login-submit").click()
        expect(other.get_by_test_id("login-error")).to_contain_text("Login failed")
        other.get_by_test_id("login-error").evaluate("e => e.textContent = ''")
    other.get_by_test_id("login-password").fill(member.password)
    other.get_by_test_id("login-submit").click()
    expect(other.get_by_test_id("login-error")).to_contain_text("locked")
