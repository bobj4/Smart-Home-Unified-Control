"""Two-factor login: each person may turn it off; an owner may require it.

Written by the reviewer (TV and two-factor phase). Do not edit, skip, mark or
delete these tests. If one looks wrong, stop and report the test name and its
full failure output instead of changing it.
"""

import time

import pyotp

from app.models import AuditEvent, Home, User

LOGIN = "/api/v1/auth/login"
ACCOUNT = "/api/v1/account"


def next_code(secret, steps=1):
    return pyotp.TOTP(secret).at(int(time.time()) + 30 * steps)


def turn_off(client, csrf, user, code=None):
    return client.post(
        f"{ACCOUNT}/totp/disable",
        json={
            "password": user.password,
            "totp_code": code or next_code(user.totp_secret),
        },
        headers=csrf(client),
    )


def policy(client, csrf, home_id, required):
    return client.put(
        f"/api/v1/homes/{home_id}/security",
        json={"require_two_factor": required},
        headers=csrf(client),
    )


def test_account_reports_two_factor(client, owner, login):
    assert login(client, owner).status_code == 200
    body = client.get(ACCOUNT).json()
    assert body["two_factor"] is True
    assert body["two_factor_required"] is False


def test_turning_two_factor_off(client, new_client, db, owner, login, csrf):
    assert login(client, owner).status_code == 200
    url = f"{ACCOUNT}/totp/disable"
    good = {"password": owner.password, "totp_code": next_code(owner.totp_secret)}
    assert client.post(url, json=good).status_code == 403  # no CSRF
    wrong_password = {**good, "password": "not the password"}
    assert (
        client.post(url, json=wrong_password, headers=csrf(client)).status_code == 403
    )
    wrong_code = {
        **good,
        "totp_code": "000000" if good["totp_code"] != "000000" else "111111",
    }
    assert client.post(url, json=wrong_code, headers=csrf(client)).status_code == 400
    assert (
        client.post(
            url, json={"password": owner.password}, headers=csrf(client)
        ).status_code
        == 422
    )

    assert client.post(url, json=good, headers=csrf(client)).status_code == 200
    assert client.get(ACCOUNT).json()["two_factor"] is False
    assert turn_off(client, csrf, owner).status_code == 409  # already off
    db.expire_all()
    user = db.get(User, owner.id)
    assert user.is_totp_enabled is False and user.totp_secret is None
    assert db.query(AuditEvent).filter_by(event_type="totp_disabled").count() == 1

    password_only = {"email": owner.email, "password": owner.password}
    assert new_client().post(LOGIN, json=password_only).status_code == 200
    assert (
        new_client()
        .post(LOGIN, json={**password_only, "password": "wrong one"})
        .status_code
        == 401
    )


def test_turning_two_factor_back_on(client, new_client, owner, login, csrf):
    assert login(client, owner).status_code == 200
    assert turn_off(client, csrf, owner).status_code == 200
    setup = client.post(
        f"{ACCOUNT}/totp/setup", json={"password": owner.password}, headers=csrf(client)
    )
    secret = setup.json()["secret"]
    confirm = client.post(
        f"{ACCOUNT}/totp/confirm",
        json={"totp_code": pyotp.TOTP(secret).now()},
        headers=csrf(client),
    )
    assert confirm.status_code == 200
    assert client.get(ACCOUNT).json()["two_factor"] is True

    password_only = {"email": owner.email, "password": owner.password}
    assert new_client().post(LOGIN, json=password_only).status_code == 401
    with_code = {**password_only, "totp_code": next_code(secret)}
    assert new_client().post(LOGIN, json=with_code).status_code == 200


def test_only_owner_sets_the_home_policy(
    client, new_client, db, owner, make_user, login, csrf
):
    url = f"/api/v1/homes/{owner.home_id}/security"
    admin = make_user(owner.home_id, role="operator")
    admin_client = new_client()
    assert login(admin_client, admin).status_code == 200
    assert admin_client.get(url).status_code == 403
    assert policy(admin_client, csrf, owner.home_id, True).status_code == 403

    assert login(client, owner).status_code == 200
    assert client.get(url).json() == {"require_two_factor": False}
    assert (
        client.put(url, json={"require_two_factor": True}).status_code == 403
    )  # no CSRF
    assert (
        client.put(
            url, json={"require_two_factor": "yes"}, headers=csrf(client)
        ).status_code
        == 422
    )
    r = policy(client, csrf, owner.home_id, True)
    assert r.status_code == 200 and r.json() == {"require_two_factor": True}
    assert client.get(url).json() == {"require_two_factor": True}
    db.expire_all()
    assert db.get(Home, owner.home_id).require_two_factor is True
    assert (
        db.query(AuditEvent).filter_by(event_type="home_security_changed").count() == 1
    )


def test_owner_needs_two_factor_to_require_it(client, owner, login, csrf):
    assert login(client, owner).status_code == 200
    assert turn_off(client, csrf, owner).status_code == 200
    assert policy(client, csrf, owner.home_id, True).status_code == 409


def test_required_two_factor_blocks_members_without_it(
    client, new_client, owner, make_user, make_device, login, csrf
):
    make_device(owner.home_id)
    member = make_user(owner.home_id, role="member")
    member_client = new_client()
    assert login(member_client, member).status_code == 200
    assert turn_off(member_client, csrf, member).status_code == 200

    assert login(client, owner).status_code == 200
    assert policy(client, csrf, owner.home_id, True).status_code == 200

    devices = f"/api/v1/homes/{owner.home_id}/devices"
    r = member_client.get(devices)
    assert r.status_code == 403 and "two-factor" in r.json()["detail"]
    account = member_client.get(ACCOUNT)
    assert account.status_code == 200  # can still reach My account to set it up
    assert account.json()["two_factor_required"] is True
    assert client.get(devices).status_code == 200  # the owner has it on

    assert policy(client, csrf, owner.home_id, False).status_code == 200
    assert member_client.get(devices).status_code == 200


def test_cannot_turn_off_while_a_home_requires_it(
    client, new_client, owner, make_user, login, csrf
):
    member = make_user(owner.home_id, role="member")
    assert login(client, owner).status_code == 200
    assert policy(client, csrf, owner.home_id, True).status_code == 200
    member_client = new_client()
    assert login(member_client, member).status_code == 200
    r = turn_off(member_client, csrf, member)
    assert r.status_code == 409 and "Home A" in r.json()["detail"]


def test_account_without_two_factor_joins_another_home(
    client, new_client, owner, make_home, make_user, login, csrf
):
    elsewhere = make_user(make_home("Home B"), role="owner")
    other = new_client()
    assert login(other, elsewhere).status_code == 200
    assert turn_off(other, csrf, elsewhere).status_code == 200

    assert login(client, owner).status_code == 200
    code = client.post(
        f"/api/v1/homes/{owner.home_id}/members/enrollments",
        json={"email": elsewhere.email, "role": "member"},
        headers=csrf(client),
    ).json()["enrollment_code"]
    guest = new_client()
    start = guest.post("/api/v1/enroll/start", json={"code": code}).json()
    assert start["existing_account"] is True and start["two_factor"] is False
    wrong = guest.post(
        "/api/v1/enroll/finish", json={"code": code, "password": "not the password 1"}
    )
    assert wrong.status_code == 403
    r = guest.post(
        "/api/v1/enroll/finish", json={"code": code, "password": elsewhere.password}
    )
    assert r.status_code == 200, r.text
