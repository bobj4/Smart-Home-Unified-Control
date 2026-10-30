"""Remember this device (skip the two-factor code), the admin's Login times,
and the approved-devices lists."""

import time
from datetime import UTC, datetime, timedelta

from app.login_times import device_name
from app.models import AuditEvent, SystemSettings, TrustedDevice
from app.models import Session as SessionModel

LOGIN = "/api/v1/auth/login"
TIMES = "/api/v1/admin/login-times"
MINE = "/api/v1/account/trusted-devices"
ALL = "/api/v1/admin/trusted-devices"
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0) Chrome/130.0 Safari/537.36"}


def later(user, steps=1):
    """An unused code (each login spends the current one)."""
    return user.totp.at(time.time() + 30 * steps)


def remember_login(client, user, code=None):
    body = {
        "email": user.email,
        "password": user.password,
        "totp_code": code or user.totp.now(),
        "remember_device": True,
    }
    return client.post(LOGIN, json=body, headers=UA)


def password_only(client, user):
    return client.post(LOGIN, json={"email": user.email, "password": user.password})


def logout(client, csrf):
    assert client.post("/api/v1/auth/logout", headers=csrf(client)).status_code == 200


def test_remembered_device_skips_the_code(client, db, owner, csrf):
    assert password_only(client, owner).status_code == 401  # code needed
    r = remember_login(client, owner)
    assert r.status_code == 200
    header = next(
        h for h in r.headers.get_list("set-cookie") if h.startswith("trusted_device=")
    ).lower()
    assert "httponly" in header and "secure" in header and "samesite=strict" in header
    assert "path=/api/v1;" in header
    device = db.query(TrustedDevice).one()
    assert device.name == "Chrome on Windows"
    assert len(device.token_hash) == 64 and device.token_hash not in header
    logout(client, csrf)

    r = password_only(client, owner)  # same browser: no code needed
    assert r.status_code == 200
    events = [
        e.details for e in db.query(AuditEvent).filter_by(event_type="login_success")
    ]
    assert '"method": "trusted_device"' in events[-1]
    db.expire_all()
    assert db.query(TrustedDevice).one().last_used_at is not None


def test_still_needs_the_password(client, owner, csrf):
    assert remember_login(client, owner).status_code == 200
    logout(client, csrf)
    bad = {"email": owner.email, "password": "wrong password!"}
    assert client.post(LOGIN, json=bad).status_code == 401


def test_device_belongs_to_one_user(client, owner, make_user, csrf):
    other = make_user(owner.home_id, role="member")
    assert remember_login(client, owner).status_code == 200
    logout(client, csrf)
    # Someone else on the same browser still needs their own code.
    assert password_only(client, other).status_code == 401


def test_other_browsers_need_the_code(client, new_client, owner):
    assert remember_login(client, owner).status_code == 200
    assert password_only(new_client(), owner).status_code == 401


def test_without_ticking_nothing_is_remembered(client, db, owner):
    body = {
        "email": owner.email,
        "password": owner.password,
        "totp_code": owner.totp.now(),
    }
    r = client.post(LOGIN, json=body)
    assert r.status_code == 200
    assert not any(
        h.startswith("trusted_device=") for h in r.headers.get_list("set-cookie")
    )
    assert db.query(TrustedDevice).count() == 0


def test_remember_device_must_be_a_boolean(client, owner):
    body = {
        "email": owner.email,
        "password": owner.password,
        "totp_code": owner.totp.now(),
        "remember_device": "yes",
    }
    assert client.post(LOGIN, json=body).status_code == 422


def test_expires_after_the_admins_days(client, db, owner, csrf):
    assert remember_login(client, owner).status_code == 200
    logout(client, csrf)
    row = db.get(SystemSettings, 1)
    row.remember_device_days = 7
    device = db.query(TrustedDevice).one()
    device.created_at = datetime.now(UTC) - timedelta(days=8)
    db.commit()
    assert password_only(client, owner).status_code == 401
    db.expire_all()
    assert db.query(TrustedDevice).count() == 0  # the expired one is removed


def test_forever_by_default(client, db, owner, csrf):
    assert remember_login(client, owner).status_code == 200
    logout(client, csrf)
    device = db.query(TrustedDevice).one()
    device.created_at = datetime.now(UTC) - timedelta(days=3000)
    db.commit()
    assert password_only(client, owner).status_code == 200


def test_password_change_forgets_devices(client, db, owner, csrf):
    assert remember_login(client, owner).status_code == 200
    r = client.post(
        "/api/v1/account/password",
        json={
            "current_password": owner.password,
            "new_password": "another long password 1",
        },
        headers=csrf(client),
    )
    assert r.status_code == 200, r.text
    assert db.query(TrustedDevice).count() == 0


def test_my_devices_list_and_forget(client, db, owner, csrf):
    assert remember_login(client, owner).status_code == 200
    rows = client.get(MINE).json()
    assert len(rows) == 1 and rows[0]["current"] is True
    assert rows[0]["name"] == "Chrome on Windows" and rows[0]["expires_at"] is None
    r = client.delete(f"{MINE}/{rows[0]['id']}", headers=csrf(client))
    assert r.status_code == 200
    assert client.get(MINE).json() == []
    logout(client, csrf)
    assert password_only(client, owner).status_code == 401


def test_cannot_forget_someone_elses_as_a_member(
    client, new_client, owner, make_user, login, csrf
):
    assert remember_login(client, owner).status_code == 200
    device_id = client.get(MINE).json()[0]["id"]
    member = make_user(owner.home_id, role="member")
    theirs = new_client()
    assert login(theirs, member).status_code == 200
    assert theirs.delete(f"{MINE}/{device_id}", headers=csrf(theirs)).status_code == 404
    assert theirs.get(ALL).status_code == 403
    assert theirs.delete(f"{ALL}/{device_id}", headers=csrf(theirs)).status_code == 403


def test_admin_sees_who_has_which_device(
    client, new_client, owner, make_user, make_home, csrf
):
    member = make_user(owner.home_id, role="member")
    stranger = make_user(make_home("Elsewhere"), role="admin")
    for person in (member, stranger):
        c = new_client()
        assert remember_login(c, person).status_code == 200
    assert remember_login(client, owner).status_code == 200
    rows = client.get(ALL).json()
    assert {r["user"] for r in rows} == {owner.email, member.email}  # not other homes
    theirs = next(r for r in rows if r["user"] == member.email)
    r = client.delete(f"{ALL}/{theirs['id']}", headers=csrf(client))
    assert r.status_code == 200
    assert {r["user"] for r in client.get(ALL).json()} == {owner.email}


def test_login_times_defaults_and_changes(client, db, owner, login, csrf):
    assert login(client, owner).status_code == 200
    assert client.get(TIMES).json() == {
        "keep_logged_in_days": 30,
        "remember_me_days": 365,
        "remember_device_days": 0,
    }
    new = {"keep_logged_in_days": 7, "remember_me_days": 90, "remember_device_days": 60}
    r = client.put(TIMES, json=new, headers=csrf(client))
    assert r.status_code == 200 and r.json() == new
    for bad in (
        {**new, "keep_logged_in_days": -1},
        {**new, "remember_device_days": -1},
        {**new, "remember_me_days": "90"},
        {**new, "remember_me_days": 1.5},
        {"keep_logged_in_days": 7, "remember_me_days": 90},  # all three needed
    ):
        assert client.put(TIMES, json=bad, headers=csrf(client)).status_code == 422
    assert db.query(AuditEvent).filter_by(event_type="login_times_changed").count() == 1


def test_login_times_are_used(client, db, owner, csrf):
    row = db.get(SystemSettings, 1) or SystemSettings(id=1)
    row.keep_logged_in_days = 7
    row.remember_me_days = 90
    row.remember_device_days = 60
    db.merge(row)
    db.commit()
    body = {
        "email": owner.email,
        "password": owner.password,
        "totp_code": owner.totp.now(),
        "keep_logged_in": True,
        "remember_me": True,
        "remember_device": True,
    }
    r = client.post(LOGIN, json=body)
    assert r.status_code == 200
    cookies = {h.split("=", 1)[0]: h.lower() for h in r.headers.get_list("set-cookie")}
    assert f"max-age={7 * 86400}" in cookies["session_token"]
    assert f"max-age={90 * 86400}" in cookies["remembered_login"]
    assert f"max-age={60 * 86400}" in cookies["trusted_device"]
    session = db.query(SessionModel).one()
    left = session.expires_at.replace(tzinfo=UTC) - datetime.now(UTC)
    assert timedelta(days=6, hours=23) < left <= timedelta(days=7)


def test_only_admins_change_login_times(client, owner, make_user, login, csrf):
    member = make_user(owner.home_id, role="member")
    assert login(client, member).status_code == 200
    assert client.get(TIMES).status_code == 403
    body = {"keep_logged_in_days": 7, "remember_me_days": 90, "remember_device_days": 0}
    assert client.put(TIMES, json=body, headers=csrf(client)).status_code == 403


def test_device_names():
    assert (
        device_name("Mozilla/5.0 (iPhone; CPU iPhone OS 18_0) Safari/604.1")
        == "Safari on iPhone"
    )
    assert (
        device_name("Mozilla/5.0 (Linux; Android 15) Chrome/130.0 Mobile")
        == "Chrome on Android"
    )
    assert (
        device_name("Mozilla/5.0 (Windows NT 10.0) Chrome/130 Edg/130")
        == "Edge on Windows"
    )
    assert device_name(None) == "Browser on unknown system"
