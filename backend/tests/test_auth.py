"""Tests for auth.py password hashing functions."""

import pytest

from app.auth import hash_password, verify_password


@pytest.fixture
def password():
    """Provide a test password."""
    return "SecurePass123"


def test_hash_password():
    """Test that hash_password produces a valid hash."""
    password = "SecurePass123"
    hashed = hash_password(password)

    # Should be a non-empty string
    assert isinstance(hashed, str)
    assert len(hashed) > 0
    assert hashed.startswith("$argon2")


def test_verify_password_correct(password):
    """Test that verify_password returns True for correct password."""
    hashed = hash_password(password)

    # verify_password takes (plain_password, hashed_password)
    assert verify_password(password, hashed) is True


def test_verify_password_incorrect(password):
    """Test that verify_password returns False for incorrect password."""
    wrong_password = "WrongPassword123"
    hashed = hash_password(password)

    assert verify_password(wrong_password, hashed) is False


def test_verify_password_empty():
    """Test that verify_password returns False for empty password."""
    password = "SecurePass123"
    hashed = hash_password(password)

    assert verify_password("", hashed) is False


def test_verify_password_different():
    """Test that verify_password returns False for completely different hash."""
    password1 = "Password1"
    password2 = "Password2"
    hashed1 = hash_password(password1)

    assert verify_password(password2, hashed1) is False


def test_hash_same_password_different():
    """Test that hashing the same password produces different hashes."""
    password = "SecurePass123"
    hash1 = hash_password(password)
    hash2 = hash_password(password)

    assert hash1 != hash2


def test_verify_password_hashed_again(password):
    """Test that hashing a hash returns False."""
    hashed = hash_password(password)
    hash_password(hashed)

    # Should not match
    assert verify_password(password, hashed) is True
    assert verify_password(hashed, hashed) is False
