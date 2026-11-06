"""After repeated failed logins: a lockout after N (for a time, or until the
password is reset), a lockdown after M (account off until an admin turns it
on), both, or neither. Blank turns a rule off."""

from datetime import UTC, datetime, timedelta

from playwright.sync_api import expect

from app.login_policy import settings
from app.models import AuditEvent, User
from tests import test_ui as _ui

LOGIN = "/api/v1/auth/login"
RULES = "/api/v1/admin/login-failures"


def rule(db, lockout_after=None, minutes=15, lockdown_after=None):
    row = settings(db)
    row.login_lockout_after = lockout_after
    row.login_lockout_minutes = minutes
    row.login_lockdown_after = lockdown_after
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
    rule(db, lockout_after=3, minutes=15)
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
    rule(db, lockout_after=2, minutes=0)
    fail(new_client(), owner, 2)
    r = attempt(new_client(), owner)
    assert r.status_code == 403 and "reset its password" in r.json()["detail"]
    db.expire_all()
    from app.auth import hash_password

    db.get(User, owner.id).hashed_password = hash_password(owner.password)  # a reset
    db.commit()
    assert attempt(new_client(), owner).status_code == 200


def test_correct_login_starts_the_count_again(client, db, owner, new_client):
    rule(db, lockout_after=3)
    fail(new_client(), owner, 2)
    assert attempt(new_client(), owner).status_code == 200
    fail(new_client(), owner, 2)
    db.expire_all()
    assert db.get(User, owner.id).locked_until is None


def test_lockdown_turns_the_account_off(
    client, db, owner, make_user, new_client, login, csrf
):
    member = make_user(owner.home_id, role="member")
    rule(db, lockdown_after=2)
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


def test_blank_turns_the_rules_off(client, db, owner, new_client):
    rule(db, lockout_after=None, minutes=None, lockdown_after=None)
    fail(new_client(), owner, 4)
    db.expire_all()
    assert db.get(User, owner.id).is_active is True


def test_lockout_then_lockdown(client, db, owner, make_user, new_client):
    member = make_user(owner.home_id, role="member")
    rule(db, lockout_after=2, minutes=15, lockdown_after=4)
    fail(new_client(), member, 2)
    db.expire_all()
    user = db.get(User, member.id)
    assert user.locked_until is not None and user.is_active is True
    # Tries during the lockout are not counted.
    fail(new_client(), member, 1)
    db.expire_all()
    user = db.get(User, member.id)
    assert user.failed_logins == 2
    user.locked_until = datetime.now(UTC) - timedelta(seconds=1)  # time is up
    db.commit()
    fail(new_client(), member, 2)
    db.expire_all()
    assert db.get(User, member.id).is_active is False
    events = [e.event_type for e in db.query(AuditEvent).all()]
    assert events.count("account_locked") == 1
    assert "account_locked_down" in events


def test_rules_api(client, owner, make_user, new_client, login, csrf):
    assert login(client, owner).status_code == 200
    assert client.get(RULES).json() == {
        "lockout_after": None,
        "lockout_minutes": 15,
        "lockdown_after": None,
    }
    for good in (
        {"lockout_after": 5, "lockout_minutes": 0, "lockdown_after": None},
        {"lockout_after": None, "lockout_minutes": None, "lockdown_after": 500},
        {"lockout_after": 3, "lockout_minutes": 30, "lockdown_after": 10},
        {"lockout_after": None, "lockout_minutes": None, "lockdown_after": None},
    ):
        r = client.put(RULES, json=good, headers=csrf(client))
        assert r.status_code == 200 and r.json() == good
    for bad in (
        {"lockout_after": 0, "lockout_minutes": 1, "lockdown_after": None},
        {"lockout_after": 5, "lockout_minutes": -1, "lockdown_after": None},
        {"lockout_after": None, "lockout_minutes": 1, "lockdown_after": 0},
        {"lockout_after": "5", "lockout_minutes": 1, "lockdown_after": None},
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
    expect(panel.get_by_test_id("failure-lockout_after")).to_have_value("")
    expect(panel.get_by_test_id("failure-lockout_minutes")).to_have_value("15")
    panel.get_by_test_id("failure-lockout_after").fill("2")
    panel.get_by_test_id("failure-lockout_minutes").fill("30")
    panel.get_by_test_id("failure-save").click()
    expect(page.get_by_test_id("status")).to_contain_text("Failed-login rules saved")
    db.expire_all()
    row = settings(db)
    assert (row.login_lockout_after, row.login_lockout_minutes) == (2, 30)
    assert row.login_lockdown_after is None

    other = open_page()
    for _ in range(2):
        other.get_by_test_id("login-email").fill(member.email)
        other.get_by_test_id("login-password").fill("wrong password")
        other.get_by_test_id("login-submit").click()
        expect(other.get_by_test_id("login-error")).to_contain_text("Login failed")
        other.get_by_test_id("login-error").evaluate("e => e.textContent = ''")
    other.get_by_test_id("login-password").fill(member.password)
    other.get_by_test_id("login-submit").click()
    expect(other.get_by_test_id("login-error")).to_contain_text("locked")
