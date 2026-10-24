"""Settings API contract: safety defaults, account security, household
members and enrollment, device editing, activity log.

Written by the reviewer (UI and settings phase). Do not edit, skip, mark or
delete these tests. If one looks wrong, stop and report the test name and its
full failure output instead of changing it.
"""

import json
import re
import time
from datetime import UTC, datetime, timedelta
from unittest.mock import patch

import pyotp

from app.models import AuditEvent

LOGIN = "/api/v1/auth/login"
ACCOUNT = "/api/v1/account"


def home_url(home_id, suffix=""):
    return f"/api/v1/homes/{home_id}{suffix}"


def next_step_code(secret):
    """A valid code from the next 30-second step (the current one may already
    have been used by the login fixture)."""
    return pyotp.TOTP(secret).at(int(time.time()) + 30)


def recovery_login(client, user, code_index=0):
    body = {
        "email": user.email,
        "password": user.password,
        "recovery_code": user.recovery_codes[code_index],
    }
    return client.post(LOGIN, json=body)


def audit_rows(db, event_type=None):
    db.expire_all()
    query = db.query(AuditEvent)
    if event_type:
        query = query.filter(AuditEvent.event_type == event_type)
    return query.all()


def all_audit_text(db):
    return "\n".join(
        f"{e.event_type} {e.user_id} {e.home_id} {e.details}" for e in audit_rows(db)
    )


# ------------------------------------------------- safety limits and defaults

RECOMMENDED = {
    "thermostat": {
        "unit": "F",
        "min_temperature": 60,
        "max_temperature": 80,
        "default_target": 68,
    },
    "water_heater": {
        "unit": "F",
        "min_temperature": 110,
        "max_temperature": 120,
        "default_target": 120,
    },
}


def limits_by_type(client, home_id):
    r = client.get(home_url(home_id, "/safety-limits"))
    assert r.status_code == 200, r.text
    return {row["device_type"]: row for row in r.json()}


def test_cli_applies_recommended_limits_and_defaults(client, owner, login):
    from scripts.set_safety_limits import main as limits_cli

    assert limits_cli(["--recommended"]) == 0
    assert login(client, owner).status_code == 200
    rows = limits_by_type(client, owner.home_id)
    for device_type, expected in RECOMMENDED.items():
        row = rows[device_type]
        assert row["enabled"] is True
        for key, value in expected.items():
            assert row[key] == value, (device_type, key)


def test_create_owner_applies_recommended_limits(client, db):
    from scripts.create_owner import main as create_owner

    answers = iter(["first-owner@example.com", "a long enough password 1"])
    with patch("builtins.input", lambda prompt="": next(answers)):
        assert create_owner() == 0
    from app.models import DeviceSafetyLimits

    db.expire_all()
    rows = {r.device_type: r for r in db.query(DeviceSafetyLimits).all()}
    assert rows["thermostat"].default_target == 68
    assert rows["water_heater"].max_temperature == 120
    assert rows["water_heater"].default_target == 120


def test_new_thermostat_and_water_heater_start_at_default_target(
    client, owner, login, csrf
):
    assert login(client, owner).status_code == 200
    for device_type, body in RECOMMENDED.items():
        r = client.put(
            home_url(owner.home_id, f"/safety-limits/{device_type}"),
            json=body,
            headers=csrf(client),
        )
        assert r.status_code == 200, r.text
        assert r.json()["default_target"] == body["default_target"]
    for device_type, target in (("thermostat", 68), ("water_heater", 120)):
        r = client.post(
            home_url(owner.home_id, "/devices"),
            json={
                "name": f"New {device_type}",
                "type": device_type,
                "integration": "simulated",
            },
            headers=csrf(client),
        )
        assert r.status_code in (200, 201), r.text
        assert r.json()["state"] == {"target_temperature": target, "unit": "F"}


def test_owner_restores_recommended_limits(
    client, new_client, owner, make_user, login, csrf
):
    url = home_url(owner.home_id, "/safety-limits/recommended")
    admin = make_user(owner.home_id, role="operator")
    admin_client = new_client()
    assert login(admin_client, admin).status_code == 200
    assert admin_client.post(url, headers=csrf(admin_client)).status_code == 403
    assert login(client, owner).status_code == 200
    assert client.post(url).status_code == 403  # no CSRF
    r = client.post(url, headers=csrf(client))
    assert r.status_code == 200, r.text
    rows = {row["device_type"]: row for row in r.json()}
    for device_type, expected in RECOMMENDED.items():
        for key, value in expected.items():
            assert rows[device_type][key] == value, (device_type, key)


def test_default_target_must_be_within_limits(client, owner, login, csrf):
    assert login(client, owner).status_code == 200
    body = {**RECOMMENDED["thermostat"], "default_target": 85}
    r = client.put(
        home_url(owner.home_id, "/safety-limits/thermostat"),
        json=body,
        headers=csrf(client),
    )
    assert r.status_code == 422


# ----------------------------------------------------------------- account


def test_account_overview(client, owner, login):
    assert client.get(ACCOUNT).status_code == 401
    assert login(client, owner).status_code == 200
    r = client.get(ACCOUNT)
    assert r.status_code == 200
    body = r.json()
    assert body["email"] == owner.email
    assert body["homes"] == [{"id": owner.home_id, "name": "Home A", "role": "admin"}]
    assert "hashed_password" not in r.text and owner.totp_secret not in r.text


def test_change_password(client, new_client, db, owner, login, csrf):
    other = new_client()
    assert login(client, owner).status_code == 200
    assert recovery_login(other, owner).status_code == 200
    url = f"{ACCOUNT}/password"
    new_password = "a brand new passphrase 9"

    assert (
        client.post(
            url, json={"current_password": owner.password, "new_password": new_password}
        ).status_code
        == 403
    )  # no CSRF
    wrong = {"current_password": "not it", "new_password": new_password}
    assert client.post(url, json=wrong, headers=csrf(client)).status_code == 403
    short = {"current_password": owner.password, "new_password": "short"}
    assert client.post(url, json=short, headers=csrf(client)).status_code == 422
    good = {"current_password": owner.password, "new_password": new_password}
    assert client.post(url, json=good, headers=csrf(client)).status_code == 200

    assert client.get(ACCOUNT).status_code == 200  # this session stays
    assert other.get(ACCOUNT).status_code == 401  # other sessions end
    fresh = new_client()
    old = {
        "email": owner.email,
        "password": owner.password,
        "recovery_code": owner.recovery_codes[1],
    }
    assert fresh.post(LOGIN, json=old).status_code == 401
    new = {**old, "password": new_password}
    assert fresh.post(LOGIN, json=new).status_code == 200
    assert audit_rows(db, "password_changed")
    assert new_password not in all_audit_text(db)


def test_regenerate_recovery_codes(client, new_client, db, owner, login, csrf):
    assert login(client, owner).status_code == 200
    url = f"{ACCOUNT}/recovery-codes"
    assert (
        client.post(url, json={"password": "not it"}, headers=csrf(client)).status_code
        == 403
    )
    r = client.post(url, json={"password": owner.password}, headers=csrf(client))
    assert r.status_code == 200, r.text
    codes = r.json()["recovery_codes"]
    assert len(codes) == 10 and all(re.fullmatch(r"\d{8}", c) for c in codes)

    old = {
        "email": owner.email,
        "password": owner.password,
        "recovery_code": owner.recovery_codes[0],
    }
    assert new_client().post(LOGIN, json=old).status_code == 401
    new = {**old, "recovery_code": codes[0]}
    assert new_client().post(LOGIN, json=new).status_code == 200
    assert new_client().post(LOGIN, json=new).status_code == 401  # single use
    text = all_audit_text(db)
    assert "recovery_codes_regenerated" in text
    assert not any(code in text for code in codes)


def test_replace_authenticator(client, new_client, owner, login, csrf):
    assert login(client, owner).status_code == 200
    confirm = f"{ACCOUNT}/totp/confirm"
    assert (
        client.post(
            confirm, json={"totp_code": "123456"}, headers=csrf(client)
        ).status_code
        == 409
    )
    setup = f"{ACCOUNT}/totp/setup"
    assert (
        client.post(
            setup, json={"password": "not it"}, headers=csrf(client)
        ).status_code
        == 403
    )
    r = client.post(setup, json={"password": owner.password}, headers=csrf(client))
    assert r.status_code == 200, r.text
    new_secret = r.json()["secret"]
    assert r.json()["otpauth_uri"].startswith("otpauth://totp/")
    assert new_secret != owner.totp_secret

    wrong = "000000" if pyotp.TOTP(new_secret).now() != "000000" else "111111"
    assert (
        client.post(
            confirm, json={"totp_code": wrong}, headers=csrf(client)
        ).status_code
        == 400
    )
    code = pyotp.TOTP(new_secret).now()
    assert (
        client.post(confirm, json={"totp_code": code}, headers=csrf(client)).status_code
        == 200
    )

    body = {"email": owner.email, "password": owner.password}
    assert (
        new_client()
        .post(LOGIN, json={**body, "totp_code": next_step_code(owner.totp_secret)})
        .status_code
        == 401
    )
    assert (
        new_client()
        .post(LOGIN, json={**body, "totp_code": next_step_code(new_secret)})
        .status_code
        == 200
    )


def test_list_and_end_sessions(client, new_client, owner, make_user, login, csrf):
    other = new_client()
    assert login(client, owner).status_code == 200
    assert recovery_login(other, owner).status_code == 200
    r = client.get(f"{ACCOUNT}/sessions")
    assert r.status_code == 200
    sessions = r.json()
    assert len(sessions) == 2
    assert [s["current"] for s in sessions].count(True) == 1
    for s in sessions:
        assert set(s) == {"id", "created_at", "last_activity", "ip_address", "current"}
    other_id = next(s["id"] for s in sessions if not s["current"])

    stranger = make_user(owner.home_id, role="member")
    stranger_client = new_client()
    assert login(stranger_client, stranger).status_code == 200
    stranger_id = next(
        s["id"] for s in stranger_client.get(f"{ACCOUNT}/sessions").json()
    )
    assert (
        client.delete(
            f"{ACCOUNT}/sessions/{stranger_id}", headers=csrf(client)
        ).status_code
        == 404
    )
    assert stranger_client.get(ACCOUNT).status_code == 200

    assert client.delete(f"{ACCOUNT}/sessions/{other_id}").status_code == 403  # no CSRF
    assert (
        client.delete(
            f"{ACCOUNT}/sessions/{other_id}", headers=csrf(client)
        ).status_code
        == 200
    )
    assert other.get(ACCOUNT).status_code == 401

    third = new_client()
    assert recovery_login(third, owner, code_index=1).status_code == 200
    r = client.post(f"{ACCOUNT}/sessions/revoke-others", headers=csrf(client))
    assert r.status_code == 200
    assert third.get(ACCOUNT).status_code == 401
    assert client.get(ACCOUNT).status_code == 200


# ------------------------------------------------------ members and enrollment

ENROLL_START = "/api/v1/enroll/start"
ENROLL_FINISH = "/api/v1/enroll/finish"


def invite(client, csrf, home_id, email, role="member"):
    return client.post(
        home_url(home_id, "/members/enrollments"),
        json={"email": email, "name": "New Person", "role": role},
        headers=csrf(client),
    )


def test_members_list_is_home_scoped(client, owner, make_user, make_home, login):
    member = make_user(owner.home_id, role="member")
    outsider = make_user(make_home("Home B"), role="owner")
    assert login(client, member).status_code == 200
    # Members only use devices; admins and owners see the list.
    assert client.get(home_url(owner.home_id, "/members")).status_code == 403
    admin = make_user(owner.home_id, role="admin")
    assert login(client, admin).status_code == 200
    r = client.get(home_url(owner.home_id, "/members"))
    assert r.status_code == 200
    rows = {row["email"]: row for row in r.json()}
    assert rows[owner.email]["role"] == "admin"
    assert rows[member.email]["role"] == "member"
    assert rows[admin.email]["role"] == "admin"
    assert outsider.email not in rows
    assert set(rows[owner.email]) == {"user_id", "email", "name", "role"}


def test_only_owner_creates_enrollment_codes(
    client, new_client, owner, make_user, login, csrf
):
    for role in ("operator", "member"):
        user = make_user(owner.home_id, role=role)
        c = new_client()
        assert login(c, user).status_code == 200
        assert invite(c, csrf, owner.home_id, "x@example.com").status_code == 403
    assert login(client, owner).status_code == 200
    assert (
        client.post(
            home_url(owner.home_id, "/members/enrollments"),
            json={"email": "x@example.com", "role": "member"},
        ).status_code
        == 403
    )  # no CSRF
    assert (
        invite(client, csrf, owner.home_id, "x@example.com", role="owner").status_code
        == 422
    )
    r = invite(client, csrf, owner.home_id, "x@example.com")
    assert r.status_code == 201, r.text
    assert len(r.json()["enrollment_code"]) >= 12
    listed = client.get(home_url(owner.home_id, "/members/enrollments"))
    assert listed.status_code == 200
    assert r.json()["enrollment_code"] not in listed.text
    assert [e["email"] for e in listed.json()] == ["x@example.com"]


def test_new_member_enrolls_with_code(client, new_client, db, owner, login, csrf):
    assert login(client, owner).status_code == 200
    code = invite(client, csrf, owner.home_id, "newbie@example.com").json()[
        "enrollment_code"
    ]

    guest = new_client()
    typed = code.lower().replace("-", " ")  # case, spaces and dashes do not matter
    r = guest.post(ENROLL_START, json={"code": typed})
    assert r.status_code == 200, r.text
    start = r.json()
    assert start["email"] == "newbie@example.com" and start["existing_account"] is False
    secret = start["totp_secret"]
    assert start["otpauth_uri"].startswith("otpauth://totp/")
    password = "newbie long password 3"

    wrong = "000000" if pyotp.TOTP(secret).now() != "000000" else "111111"
    bad = {"code": code, "password": password, "totp_code": wrong}
    assert guest.post(ENROLL_FINISH, json=bad).status_code == 400
    short = {"code": code, "password": "short", "totp_code": pyotp.TOTP(secret).now()}
    assert guest.post(ENROLL_FINISH, json=short).status_code == 422
    good = {"code": code, "password": password, "totp_code": pyotp.TOTP(secret).now()}
    r = guest.post(ENROLL_FINISH, json=good)
    assert r.status_code == 200, r.text
    recovery = r.json()["recovery_codes"]
    assert len(recovery) == 10

    assert (
        new_client().post(ENROLL_START, json={"code": code}).status_code == 404
    )  # used
    member = new_client()
    login_body = {
        "email": "newbie@example.com",
        "password": password,
        "totp_code": next_step_code(secret),
    }
    assert member.post(LOGIN, json=login_body).status_code == 200
    homes = member.get(f"{ACCOUNT}").json()["homes"]
    assert homes == [{"id": owner.home_id, "name": "Home A", "role": "member"}]

    text = all_audit_text(db)
    assert "member_added" in text
    for secret_value in (code, secret, password, *recovery):
        assert secret_value not in text


def test_existing_account_joins_another_home(
    client, new_client, owner, make_home, make_user, login, csrf
):
    elsewhere = make_user(make_home("Home B"), role="owner")
    assert login(client, owner).status_code == 200
    code = invite(client, csrf, owner.home_id, elsewhere.email, role="admin").json()[
        "enrollment_code"
    ]
    guest = new_client()
    start = guest.post(ENROLL_START, json={"code": code}).json()
    assert start["existing_account"] is True and "totp_secret" not in start
    wrong = {
        "code": code,
        "password": "not the password 12",
        "totp_code": elsewhere.totp.now(),
    }
    assert guest.post(ENROLL_FINISH, json=wrong).status_code == 403
    good = {
        "code": code,
        "password": elsewhere.password,
        "totp_code": elsewhere.totp.now(),
    }
    r = guest.post(ENROLL_FINISH, json=good)
    assert r.status_code == 200, r.text
    assert r.json()["recovery_codes"] == []
    c = new_client()
    assert recovery_login(c, elsewhere).status_code == 200
    roles = {h["id"]: h["role"] for h in c.get(ACCOUNT).json()["homes"]}
    assert roles[owner.home_id] == "admin"


def test_enrollment_codes_expire_and_can_be_cancelled(
    client, new_client, db, owner, login, csrf
):
    from app.models import Enrollment  # added in step U3

    assert login(client, owner).status_code == 200
    first = invite(client, csrf, owner.home_id, "a@example.com").json()
    second = invite(client, csrf, owner.home_id, "b@example.com").json()
    db.query(Enrollment).filter(Enrollment.id == first["id"]).update(
        {Enrollment.expires_at: datetime.now(UTC) - timedelta(seconds=1)}
    )
    db.commit()
    guest = new_client()
    assert (
        guest.post(ENROLL_START, json={"code": first["enrollment_code"]}).status_code
        == 404
    )
    assert (
        guest.post(ENROLL_START, json={"code": "WXYZ-WXYZ-WXYZ-WXYZ"}).status_code
        == 404
    )
    url = home_url(owner.home_id, f"/members/enrollments/{second['id']}")
    assert client.delete(url, headers=csrf(client)).status_code == 200
    assert (
        guest.post(ENROLL_START, json={"code": second["enrollment_code"]}).status_code
        == 404
    )


def test_cannot_invite_an_existing_member(client, owner, make_user, login, csrf):
    member = make_user(owner.home_id, role="member")
    assert login(client, owner).status_code == 200
    assert invite(client, csrf, owner.home_id, member.email).status_code == 409


def test_enrollment_guessing_is_rate_limited(client, new_client, owner, login, csrf):
    assert login(client, owner).status_code == 200
    code = invite(client, csrf, owner.home_id, "late@example.com").json()[
        "enrollment_code"
    ]
    guest = new_client()
    for i in range(20):
        r = guest.post(ENROLL_START, json={"code": f"AAAA-BBBB-CCCC-{i:04d}"})
        if r.status_code == 429:
            break
        assert r.status_code == 404
    assert guest.post(ENROLL_START, json={"code": code}).status_code == 429


def test_owner_changes_roles_and_removes_members(
    client, new_client, owner, make_user, make_device, login, csrf
):
    member = make_user(owner.home_id, role="member")
    member_client = new_client()
    assert login(member_client, member).status_code == 200
    device_body = {"name": "Lamp 9", "type": "light", "integration": "simulated"}
    assert (
        member_client.post(
            home_url(owner.home_id, "/devices"),
            json=device_body,
            headers=csrf(member_client),
        ).status_code
        == 403
    )

    assert login(client, owner).status_code == 200
    member_url = home_url(owner.home_id, f"/members/{member.id}")
    assert (
        member_client.patch(
            member_url, json={"role": "admin"}, headers=csrf(member_client)
        ).status_code
        == 403
    )
    assert (
        client.patch(
            member_url, json={"role": "boss"}, headers=csrf(client)
        ).status_code
        == 422
    )
    assert (
        client.patch(
            member_url, json={"role": "admin"}, headers=csrf(client)
        ).status_code
        == 200
    )
    assert member_client.post(
        home_url(owner.home_id, "/devices"),
        json=device_body,
        headers=csrf(member_client),
    ).status_code in (200, 201)

    self_url = home_url(owner.home_id, f"/members/{owner.id}")
    assert (
        client.patch(
            self_url, json={"role": "member"}, headers=csrf(client)
        ).status_code
        == 409
    )
    assert client.delete(self_url, headers=csrf(client)).status_code == 409

    assert client.delete(member_url, headers=csrf(client)).status_code == 200
    assert member_client.get(home_url(owner.home_id, "/devices")).status_code in (
        401,
        404,
    )
    assert member_client.get(ACCOUNT).status_code == 401  # no homes left: sessions end
    assert client.delete(member_url, headers=csrf(client)).status_code == 404


# ------------------------------------------------------ devices and activity


def test_admin_renames_and_moves_devices(
    client, new_client, db, owner, make_user, make_home, make_device, login, csrf
):
    device_id = make_device(owner.home_id)
    other_home_device = make_device(make_home("Home B"))
    admin = make_user(owner.home_id, role="admin")
    member = make_user(owner.home_id, role="member")
    url = home_url(owner.home_id, f"/devices/{device_id}")

    member_client = new_client()
    assert login(member_client, member).status_code == 200
    assert (
        member_client.patch(
            url, json={"name": "X"}, headers=csrf(member_client)
        ).status_code
        == 403
    )

    assert login(client, admin).status_code == 200
    r = client.patch(
        url, json={"name": "Desk lamp", "room": "Office"}, headers=csrf(client)
    )
    assert r.status_code == 200, r.text
    assert r.json()["name"] == "Desk lamp" and r.json()["room"] == "Office"
    assert client.patch(url, json={"name": "Y"}).status_code == 403  # no CSRF
    assert client.patch(url, json={}, headers=csrf(client)).status_code == 422
    assert (
        client.patch(url, json={"type": "tv"}, headers=csrf(client)).status_code == 422
    )
    assert client.patch(url, json={"name": ""}, headers=csrf(client)).status_code == 422
    foreign = home_url(owner.home_id, f"/devices/{other_home_device}")
    assert (
        client.patch(foreign, json={"name": "Z"}, headers=csrf(client)).status_code
        == 404
    )
    assert audit_rows(db, "device_updated")


def test_activity_log_is_owner_only_and_home_scoped(
    client, new_client, owner, make_user, make_home, make_device, login, csrf
):
    device_id = make_device(owner.home_id)
    other_owner = make_user(make_home("Home B"), role="owner")
    other_client = new_client()
    assert login(other_client, other_owner).status_code == 200

    assert login(client, owner).status_code == 200
    client.post(
        home_url(owner.home_id, f"/devices/{device_id}/command"),
        json={"command": "turn_on", "payload": {}},
        headers=csrf(client),
    )
    url = home_url(owner.home_id, "/audit")
    r = client.get(url)
    assert r.status_code == 200, r.text
    events = r.json()
    types = [e["event_type"] for e in events]
    assert "device_command" in types and "login_success" in types
    assert types.index("device_command") < types.index("login_success")  # newest first
    command = next(e for e in events if e["event_type"] == "device_command")
    assert command["user_email"] == owner.email
    assert {"created_at", "event_type", "user_email", "ip_address", "details"} <= set(
        command
    )
    assert other_owner.email not in r.text  # other home's logins are not shown

    assert len(client.get(url, params={"limit": 1}).json()) == 1
    assert client.get(url, params={"limit": 500}).status_code == 422
    assert other_client.get(url).status_code == 404
    for role in ("operator", "member"):
        c = new_client()
        assert login(c, make_user(owner.home_id, role=role)).status_code == 200
        assert c.get(url).status_code == 403


def test_activity_log_contains_no_secrets(client, new_client, owner, login, csrf):
    assert login(client, owner).status_code == 200
    codes = client.post(
        f"{ACCOUNT}/recovery-codes",
        json={"password": owner.password},
        headers=csrf(client),
    ).json()["recovery_codes"]
    code = invite(client, csrf, owner.home_id, "s@example.com").json()[
        "enrollment_code"
    ]
    new_password = "another strong passphrase 5"
    client.post(
        f"{ACCOUNT}/password",
        json={"current_password": owner.password, "new_password": new_password},
        headers=csrf(client),
    )
    text = client.get(home_url(owner.home_id, "/audit"), params={"limit": 200}).text
    for value in (
        owner.password,
        new_password,
        owner.totp_secret,
        code,
        *codes,
        client.cookies.get("session_token"),
        client.cookies.get("csrf_token"),
    ):
        assert value and value not in text
    assert json.loads(text)
