"""HTTP behaviour contract for steps 7-14. Written by the reviewer (Review 2).

Do not edit, skip, mark or delete these tests. If one looks wrong, stop and
report the test name and its full failure output instead of changing it.

IDs in docstrings refer to docs/SECURITY.md (SEC-xx) and docs/REVIEW-1.md.
"""

import re
import statistics
import time
import uuid
from datetime import UTC, datetime, timedelta

from app.models import AuditEvent, Device
from app.models import Session as SessionModel

LOGIN = "/api/v1/auth/login"
LOGOUT = "/api/v1/auth/logout"
HOMES = "/api/v1/homes"


def devices_url(home_id, device_id=None, suffix=""):
    url = f"/api/v1/homes/{home_id}/devices"
    if device_id is not None:
        url += f"/{device_id}"
    return url + suffix


def as_utc(value):
    """SQLite returns naive datetimes; treat them as UTC."""
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value


def set_cookie_headers(response):
    return [v for k, v in response.headers.multi_items() if k.lower() == "set-cookie"]


def cookie_header(response, name):
    for header in set_cookie_headers(response):
        if header.split("=", 1)[0].strip() == name:
            return header
    return None


def audit_rows(db):
    db.expire_all()
    return db.query(AuditEvent).all()


def audit_text(db):
    return "\n".join(
        f"{e.event_type} {e.user_id} {e.home_id} {e.ip_address} {e.details}"
        for e in audit_rows(db)
    )


# --------------------------------------------------------------- login (B5, B7)


def test_login_without_totp_is_rejected(client, owner):
    """SEC-02 / B7: a password alone never logs in a TOTP-enabled account."""
    r = client.post(LOGIN, json={"email": owner.email, "password": owner.password})
    assert r.status_code in (401, 422)
    assert cookie_header(r, "session_token") is None


def test_login_with_wrong_totp_is_rejected(client, owner, login):
    r = login(client, owner, totp_code="000000")
    if owner.totp.verify("000000"):  # one-in-a-million real match
        return
    assert r.status_code == 401
    assert cookie_header(r, "session_token") is None


def test_login_sets_secure_session_cookie_and_no_token_in_body(client, owner, login):
    """SEC-03 / B5: the session token lives only in an HttpOnly cookie."""
    r = login(client, owner)
    assert r.status_code == 200, r.text
    session = cookie_header(r, "session_token")
    assert session is not None
    flags = session.lower()
    assert "httponly" in flags
    assert "secure" in flags
    assert "samesite=strict" in flags
    token = client.cookies.get("session_token")
    assert token and token not in r.text
    assert "session_token" not in r.json()


def test_login_sets_readable_csrf_cookie(client, owner, login):
    """SEC-04: double-submit token, readable by the web app's JavaScript."""
    r = login(client, owner)
    assert r.status_code == 200, r.text
    csrf_cookie = cookie_header(r, "csrf_token")
    assert csrf_cookie is not None
    flags = csrf_cookie.lower()
    assert "httponly" not in flags
    assert "secure" in flags
    assert "samesite=strict" in flags
    assert client.cookies.get("csrf_token") != client.cookies.get("session_token")


def test_totp_code_cannot_be_reused(client, new_client, owner, login):
    """SEC-07: the same code is accepted once, even from another client."""
    code = owner.totp.now()
    first = login(client, owner, totp_code=code)
    assert first.status_code == 200, first.text
    second = login(new_client(), owner, totp_code=code)
    assert second.status_code == 401


def test_recovery_code_logs_in_once(client, new_client, owner):
    """SEC-06: a recovery code replaces the TOTP code and works only once."""
    code = owner.recovery_codes[0]
    body = {"email": owner.email, "password": owner.password, "recovery_code": code}
    first = client.post(LOGIN, json=body)
    assert first.status_code == 200, first.text
    second = new_client().post(LOGIN, json=body)
    assert second.status_code == 401


def test_login_rejects_unknown_fields(client, owner):
    """SEC-20 / M7."""
    body = {
        "email": owner.email,
        "password": owner.password,
        "totp_code": owner.totp.now(),
        "is_admin": True,
    }
    assert client.post(LOGIN, json=body).status_code == 422


def test_unknown_account_and_wrong_password_look_the_same(client, owner):
    """H4: same response, and an unknown account still pays for a hash."""
    wrong = {"email": owner.email, "password": "wrong-password", "totp_code": "000000"}
    unknown = {
        "email": "nobody@example.com",
        "password": "wrong-password",
        "totp_code": "000000",
    }

    def timed(body):
        start = time.perf_counter()
        response = client.post(LOGIN, json=body)
        return response, time.perf_counter() - start

    wrong_runs = [timed(wrong) for _ in range(3)]
    unknown_runs = [timed(unknown) for _ in range(3)]
    for response, _ in wrong_runs + unknown_runs:
        assert response.status_code == 401
    assert wrong_runs[0][0].json() == unknown_runs[0][0].json()
    wrong_time = statistics.median(t for _, t in wrong_runs)
    unknown_time = statistics.median(t for _, t in unknown_runs)
    assert unknown_time > 0.5 * wrong_time


# ------------------------------------------------------- rate limiting (H1, M5)


def test_account_locked_after_five_failures(client, owner, login):
    """SEC-05: limit is per account; a client-chosen cookie must not reset it."""
    for attempt in range(5):
        client.cookies.set("user_id", f"rotating-{attempt}")
        r = client.post(
            LOGIN,
            json={"email": owner.email, "password": "wrong", "totp_code": "000000"},
        )
        assert r.status_code == 401
    client.cookies.set("user_id", "rotating-final")
    r = login(client, owner)
    assert r.status_code == 429
    assert "retry-after" in {k.lower() for k in r.headers}


def test_lockout_of_one_account_does_not_block_another(
    client, new_client, owner, make_user, login
):
    other = make_user(owner.home_id, role="member")
    for _ in range(5):
        client.post(
            LOGIN,
            json={"email": owner.email, "password": "wrong", "totp_code": "000000"},
        )
    assert login(new_client(), other).status_code == 200


# --------------------------------------------------------------- sessions (B1)


def test_protected_route_without_session_is_401(client):
    """SEC-10: missing session is 401, never 500."""
    assert client.get(HOMES).status_code == 401


def test_homes_lists_only_member_homes(client, owner, make_home, make_user, login):
    make_user(make_home("Home B"), role="owner")
    assert login(client, owner).status_code == 200
    r = client.get(HOMES)
    assert r.status_code == 200, r.text
    assert [h["id"] for h in r.json()] == [owner.home_id]


def test_logout_revokes_session(client, owner, login, csrf):
    """SEC-03: logout deletes the session; the old cookie stops working."""
    assert login(client, owner).status_code == 200
    old_token = client.cookies.get("session_token")
    r = client.post(LOGOUT, headers=csrf(client))
    assert r.status_code == 200, r.text
    client.cookies.set("session_token", old_token)
    assert client.get(HOMES).status_code == 401


def test_idle_session_expires_after_30_minutes(client, db, owner, login):
    assert login(client, owner).status_code == 200
    db.query(SessionModel).update(
        {SessionModel.last_activity: datetime.now(UTC) - timedelta(minutes=31)}
    )
    db.commit()
    assert client.get(HOMES).status_code == 401


def test_activity_refreshes_idle_timer(client, db, owner, login):
    assert login(client, owner).status_code == 200
    db.query(SessionModel).update(
        {SessionModel.last_activity: datetime.now(UTC) - timedelta(minutes=20)}
    )
    db.commit()
    assert client.get(HOMES).status_code == 200
    db.expire_all()
    session = db.query(SessionModel).one()
    assert datetime.now(UTC) - as_utc(session.last_activity) < timedelta(minutes=1)


def test_session_has_12_hour_absolute_limit(client, db, owner, login):
    assert login(client, owner).status_code == 200
    session = db.query(SessionModel).one()
    remaining = as_utc(session.expires_at) - datetime.now(UTC)
    assert timedelta(hours=11, minutes=55) < remaining <= timedelta(hours=12)
    session.expires_at = datetime.now(UTC) - timedelta(seconds=1)
    db.commit()
    assert client.get(HOMES).status_code == 401


def test_session_token_is_stored_hashed(client, db, owner, login):
    assert login(client, owner).status_code == 200
    token = client.cookies.get("session_token")
    session = db.query(SessionModel).one()
    assert token not in str(session.hash_token)


def test_user_id_parameter_cannot_end_other_users_sessions(
    client, new_client, owner, login
):
    """B1: no route takes the acting user from a query parameter."""
    assert login(client, owner).status_code == 200
    attacker = new_client()
    r = attacker.post(f"/api/v1/sessions/logout-all?user_id={owner.id}")
    assert r.status_code in (401, 403, 404, 405)
    assert client.get(HOMES).status_code == 200


# ------------------------------------------------------------------- CSRF


def test_state_change_without_csrf_header_is_403(client, owner, login):
    """SEC-04."""
    assert login(client, owner).status_code == 200
    assert client.post(LOGOUT).status_code == 403
    assert client.get(HOMES).status_code == 200


def test_state_change_with_wrong_csrf_header_is_403(client, owner, login):
    assert login(client, owner).status_code == 200
    r = client.post(LOGOUT, headers={"X-CSRF-Token": "not-the-token"})
    assert r.status_code == 403


def test_csrf_token_from_another_session_is_rejected(
    client, new_client, owner, make_user, login, csrf
):
    other = make_user(owner.home_id, role="member")
    second = new_client()
    assert login(client, owner).status_code == 200
    assert login(second, other).status_code == 200
    r = client.post(LOGOUT, headers=csrf(second))
    assert r.status_code == 403


# ---------------------------------------------------------- authorization


def test_cross_home_device_access_is_denied(
    client, owner, make_home, make_user, make_device, login, csrf
):
    """SEC-11: a member of home A cannot see or control home B's devices."""
    home_b = make_home("Home B")
    make_user(home_b, role="owner")
    device_b = make_device(home_b)
    assert login(client, owner).status_code == 200
    assert client.get(devices_url(home_b)).status_code in (403, 404)
    assert client.get(devices_url(home_b, device_b)).status_code in (403, 404)
    # Home A in the path does not unlock a device that belongs to home B.
    assert client.get(devices_url(owner.home_id, device_b)).status_code == 404
    r = client.post(
        devices_url(home_b, device_b, "/command"),
        json={"command": "turn_on", "payload": {}},
        headers=csrf(client),
    )
    assert r.status_code in (403, 404)


def test_owner_can_list_and_read_devices(client, owner, make_device, login):
    """Owner passes a member-level check (roles are a hierarchy)."""
    device_id = make_device(owner.home_id)
    assert login(client, owner).status_code == 200
    r = client.get(devices_url(owner.home_id))
    assert r.status_code == 200, r.text
    assert [d["id"] for d in r.json()] == [device_id]
    r = client.get(devices_url(owner.home_id, device_id))
    assert r.status_code == 200, r.text
    assert r.json()["id"] == device_id


def test_member_cannot_create_or_delete_devices(
    client, owner, make_user, make_device, login, csrf
):
    member = make_user(owner.home_id, role="member")
    device_id = make_device(owner.home_id)
    assert login(client, member).status_code == 200
    body = {"name": "Lamp 2", "type": "light", "integration": "simulated"}
    assert (
        client.post(
            devices_url(owner.home_id), json=body, headers=csrf(client)
        ).status_code
        == 403
    )
    r = client.delete(devices_url(owner.home_id, device_id), headers=csrf(client))
    assert r.status_code == 403


def test_owner_creates_device_with_validated_input(client, owner, login, csrf):
    """SEC-20: typed body, unknown fields and unknown device types rejected."""
    assert login(client, owner).status_code == 200
    url = devices_url(owner.home_id)
    good = {
        "name": "Lamp 2",
        "type": "light",
        "integration": "simulated",
        "room": "Hall",
    }
    r = client.post(url, json=good, headers=csrf(client))
    assert r.status_code in (200, 201), r.text
    assert r.json()["name"] == "Lamp 2"
    assert (
        client.post(
            url, json={**good, "home_id": str(uuid.uuid4())}, headers=csrf(client)
        ).status_code
        == 422
    )
    assert (
        client.post(
            url, json={**good, "type": "toaster"}, headers=csrf(client)
        ).status_code
        == 422
    )


# ------------------------------------------------- device commands (SEC-40-42)


def test_light_command_is_executed_and_audited(
    client, db, owner, make_device, login, csrf
):
    device_id = make_device(owner.home_id, device_type="light")
    assert login(client, owner).status_code == 200
    r = client.post(
        devices_url(owner.home_id, device_id, "/command"),
        json={"command": "turn_on", "payload": {}},
        headers=csrf(client),
    )
    assert r.status_code == 200, r.text
    events = [e for e in audit_rows(db) if e.event_type == "device_command"]
    assert len(events) == 1
    assert str(events[0].user_id) == owner.id
    assert str(events[0].home_id) == owner.home_id


def test_thermostat_command_refused_until_limits_configured(
    client, db, owner, make_device, login, csrf
):
    """SEC-42 and SEC-41: refused, nothing changes, and the refusal is audited."""
    device_id = make_device(owner.home_id, device_type="thermostat", name="Hall")
    assert login(client, owner).status_code == 200
    r = client.post(
        devices_url(owner.home_id, device_id, "/command"),
        json={"command": "set_temperature", "payload": {"temperature": 21}},
        headers=csrf(client),
    )
    assert r.status_code == 409
    db.expire_all()
    assert db.get(Device, device_id).state == "{}"
    assert "device_command_rejected" in [e.event_type for e in audit_rows(db)]


def test_command_body_rejects_unknown_fields(client, owner, make_device, login, csrf):
    device_id = make_device(owner.home_id)
    assert login(client, owner).status_code == 200
    r = client.post(
        devices_url(owner.home_id, device_id, "/command"),
        json={"command": "turn_on", "payload": {}, "bypass_limits": True},
        headers=csrf(client),
    )
    assert r.status_code == 422


# ------------------------------------------------------- audit log (SEC-32/80)


def test_login_success_and_failure_are_audited(client, db, owner, login):
    client.post(
        LOGIN, json={"email": owner.email, "password": "wrong", "totp_code": "000000"}
    )
    assert login(client, owner).status_code == 200
    rows = audit_rows(db)
    success = [e for e in rows if e.event_type == "login_success"]
    failure = [e for e in rows if e.event_type == "login_failure"]
    assert len(success) == 1 and len(failure) == 1
    assert str(success[0].user_id) == owner.id
    assert success[0].ip_address


def test_logout_is_audited(client, db, owner, login, csrf):
    assert login(client, owner).status_code == 200
    assert client.post(LOGOUT, headers=csrf(client)).status_code == 200
    assert "logout" in [e.event_type for e in audit_rows(db)]


def test_audit_log_never_contains_secrets(client, db, owner, make_device, login, csrf):
    """SEC-32: checks every column of every audit row, nested payloads included."""
    device_id = make_device(owner.home_id)
    wrong_password = "SENTINEL-wrong-password-8841"
    client.post(
        LOGIN,
        json={"email": owner.email, "password": wrong_password, "totp_code": "000000"},
    )
    code = owner.totp.now()
    assert login(client, owner, totp_code=code).status_code == 200
    client.post(
        devices_url(owner.home_id, device_id, "/command"),
        json={
            "command": "turn_on",
            "payload": {
                "token": "SENTINEL-token-5512",
                "nested": {"password": "SENTINEL-pw-3307"},
            },
        },
        headers=csrf(client),
    )
    text = audit_text(db)
    assert text, "no audit rows were written"
    secrets_used = [
        owner.password,
        wrong_password,
        code,
        owner.totp_secret,
        client.cookies.get("session_token"),
        client.cookies.get("csrf_token"),
        "SENTINEL-token-5512",
        "SENTINEL-pw-3307",
    ]
    for secret in secrets_used:
        assert secret and secret not in text


# --------------------------------------------------- headers and CORS (SEC-14/24)


def check_security_headers(response):
    h = {k.lower(): v for k, v in response.headers.items()}
    assert h.get("x-content-type-options") == "nosniff"
    assert h.get("x-frame-options") == "DENY"
    assert h.get("referrer-policy")
    csp = h.get("content-security-policy", "")
    assert "default-src 'self'" in csp
    assert "frame-ancestors 'none'" in csp
    script_src = re.search(r"script-src ([^;]*)", csp)
    assert script_src and "'unsafe-inline'" not in script_src.group(1)
    for item in h.get("permissions-policy", "").split(","):
        assert re.fullmatch(r"\s*[a-z-]+=\([^()]*\)\s*", item), item


def test_security_headers_on_public_and_error_responses(client):
    check_security_headers(client.get("/health"))
    check_security_headers(client.get(HOMES))  # 401


def test_no_cors_for_unlisted_origin(client):
    """SEC-14: no origins allowed by default, and never a wildcard."""
    evil = "https://evil.example"
    r = client.options(
        LOGIN, headers={"Origin": evil, "Access-Control-Request-Method": "POST"}
    )
    assert "access-control-allow-origin" not in {k.lower() for k in r.headers}
    for path in ("/", "/js/api.js", "/health"):
        r = client.get(path, headers={"Origin": evil})
        assert "access-control-allow-origin" not in {k.lower() for k in r.headers}


def test_api_docs_not_public(client):
    """M8."""
    for path in ("/docs", "/redoc", "/openapi.json"):
        assert client.get(path).status_code in (401, 404)


# -------------------------------------------------------------- web app (B6)


def test_web_app_loads_without_a_session(client):
    r = client.get("/")
    assert r.status_code == 200
    assert "text/html" in r.headers["content-type"]
    assert 'id="login-form"' in r.text
    for path in ("/js/api.js", "/js/app.js"):
        r = client.get(path)
        assert r.status_code == 200, path
        assert "javascript" in r.headers["content-type"], path
    r = client.get("/manifest.json")
    assert r.status_code == 200
    assert r.json()["name"]
