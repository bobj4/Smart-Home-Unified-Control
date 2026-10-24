"""TOTP tests using real pyotp codes. Replaced by the reviewer (Review 2).

The previous version mocked pyotp and hmac, so it passed while every real
authenticator code was rejected. Do not edit, skip, mark or delete these tests.
"""

import time
from datetime import UTC, datetime

import pyotp

from app.auth import (
    generate_totp_provisioning_uri,
    generate_totp_secret,
    verify_totp_code,
)


def code_at(secret, seconds_from_now):
    return pyotp.TOTP(secret).at(int(time.time()) + seconds_from_now)


def current_step(secret):
    return pyotp.TOTP(secret).timecode(datetime.now(UTC))


def test_generate_totp_secret():
    secret = generate_totp_secret()
    assert isinstance(secret, str)
    assert all(c in "ABCDEFGHIJKLMNOPQRSTUVWXYZ234567" for c in secret)
    assert len(secret) >= 16


def test_current_code_is_accepted_and_returns_its_step():
    secret = generate_totp_secret()
    step = current_step(secret)
    result = verify_totp_code(pyotp.TOTP(secret).now(), secret)
    assert result in (step, step + 1)  # step + 1 only if a boundary passed


def test_code_from_previous_step_is_accepted():
    secret = generate_totp_secret()
    assert verify_totp_code(code_at(secret, -30), secret) is not None


def test_code_two_steps_old_is_rejected():
    secret = generate_totp_secret()
    old = code_at(secret, -60)
    if old in (code_at(secret, 0), code_at(secret, -30), code_at(secret, 30)):
        return  # the same digits happen to be valid now; nothing to test
    assert verify_totp_code(old, secret) is None


def test_wrong_code_is_rejected():
    secret = generate_totp_secret()
    valid = {code_at(secret, offset) for offset in (-30, 0, 30)}
    wrong = next(c for c in ("000000", "111111", "222222") if c not in valid)
    assert verify_totp_code(wrong, secret) is None


def test_malformed_codes_are_rejected():
    secret = generate_totp_secret()
    for code in ("", "12345", "1234567", "abcdef", " 12345"):
        assert verify_totp_code(code, secret) is None


def test_accepted_code_cannot_be_reused():
    secret = generate_totp_secret()
    code = pyotp.TOTP(secret).now()
    step = verify_totp_code(code, secret)
    assert step is not None
    assert verify_totp_code(code, secret, last_step=step) is None


def test_older_code_rejected_after_newer_one_was_accepted():
    secret = generate_totp_secret()
    step = verify_totp_code(pyotp.TOTP(secret).now(), secret)
    assert step is not None
    previous = code_at(secret, -30)
    if previous == pyotp.TOTP(secret).now():
        return
    assert verify_totp_code(previous, secret, last_step=step) is None


def test_generate_totp_provisioning_uri():
    uri = generate_totp_provisioning_uri(
        "test@example.com", "JBSWY3DPEHPK3PXP", "TestApp"
    )
    assert uri.startswith("otpauth://totp/")
    assert "%40example.com" in uri
    assert "TestApp" in uri
    assert "JBSWY3DPEHPK3PXP" in uri
