"""Tests for recovery codes in auth.py."""

import json
import uuid

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.auth import (
    generate_recovery_codes,
    verify_recovery_code,
)
from app.models import Base, User


@pytest.fixture
def engine():
    """Create an in-memory SQLite database for testing."""
    SQLALCHEMY_DATABASE_URL = "sqlite:///:memory:"
    engine = create_engine(
        SQLALCHEMY_DATABASE_URL, echo=False, connect_args={"check_same_thread": False}
    )
    return engine


@pytest.fixture
def SessionLocal(engine):
    """Create a sessionmaker for the test engine."""
    return sessionmaker(bind=engine)


@pytest.fixture(autouse=True)
def setup_database(engine):
    """Set up the database before each test."""
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)


@pytest.fixture
def test_db(tmp_path):
    """Create a test database file."""
    db_path = tmp_path / "test.db"
    engine = create_engine(f"sqlite:///{db_path}")
    Base.metadata.create_all(bind=engine)
    SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    db = SessionLocal()
    yield db, engine, SessionLocal
    db.close()


def test_generate_recovery_codes():
    """Test that 10 recovery codes are generated."""
    codes = generate_recovery_codes()

    # Should generate exactly 10 codes
    assert len(codes) == 10

    # Each code should be a tuple of (plain_code, hashed_code)
    for plain_code, hashed_code in codes:
        assert isinstance(plain_code, str)
        assert isinstance(hashed_code, str)
        # The plain code should be an 8-digit number
        assert len(plain_code) == 8
        assert plain_code.isdigit()
        # The hashed code should be a JSON hash (Argon2id format starts with $argon2id)
        assert hashed_code.startswith("$argon2id")


def test_verify_recovery_code_valid(test_db):
    """Test that a valid recovery code works once."""
    db, engine, SessionLocal = test_db
    # Generate codes
    codes = generate_recovery_codes()
    plain_code, stored_hash = codes[0]

    # Create a user with these codes
    from app.auth import ph

    user_id = str(uuid.uuid4())
    user = User(
        id=user_id,
        email="test@example.com",
        hashed_password=ph.hash("password"),
        is_active=True,
        is_superuser=True,
        totp_secret="JBSWY3DPEHPK3PXP",
        recovery_codes=json.dumps([h for _, h in codes]),  # Only store hashes
    )

    db.add(user)
    db.commit()

    print(f"DEBUG: user_id = {user_id}")
    print(f"DEBUG: user.recovery_codes = {user.recovery_codes}")

    # Verify the code works
    result = verify_recovery_code(plain_code, db, user_id)
    assert result is True


def test_verify_recovery_code_second_use_fails(test_db):
    """Test that a used recovery code fails on second use."""
    db, engine, SessionLocal = test_db
    # Generate codes
    codes = generate_recovery_codes()
    plain_code, _ = codes[0]

    # Create a user with these codes
    from app.auth import ph

    user = User(
        id=str(uuid.uuid4()),
        email="test@example.com",
        hashed_password=ph.hash("password"),
        is_active=True,
        is_superuser=True,
        totp_secret="JBSWY3DPEHPK3PXP",
        recovery_codes=json.dumps([h for _, h in codes]),  # Only store hashes
    )

    db.add(user)
    db.commit()

    # First use should succeed
    result1 = verify_recovery_code(plain_code, db, str(user.id))
    assert result1 is True

    # Second use should fail
    result2 = verify_recovery_code(plain_code, db, str(user.id))
    assert result2 is False


def test_verify_recovery_code_wrong_code(test_db):
    """Test that a wrong recovery code fails."""
    db, engine, SessionLocal = test_db
    # Generate codes
    codes = generate_recovery_codes()
    plain_code, _ = codes[0]

    # Create a user with these codes
    from app.auth import ph

    user = User(
        id=str(uuid.uuid4()),
        email="test@example.com",
        hashed_password=ph.hash("password"),
        is_active=True,
        is_superuser=True,
        totp_secret="JBSWY3DPEHPK3PXP",
        recovery_codes=json.dumps([h for _, h in codes]),  # Only store hashes
    )

    db.add(user)
    db.commit()
    user_uuid = str(user.id)

    # Generate a fake code
    fake_code = "12345678"

    # Should fail
    result = verify_recovery_code(fake_code, db, user_uuid)
    assert result is False


def test_verify_recovery_code_nonexistent_user(test_db):
    """Test that verifying a code for a nonexistent user fails."""
    db, engine, SessionLocal = test_db
    from fastapi import HTTPException

    # Generate codes
    codes = generate_recovery_codes()
    plain_code, _ = codes[0]

    # Use a nonexistent user ID
    nonexistent_uuid = str(uuid.uuid4())

    # Should raise 404
    with pytest.raises(HTTPException) as excinfo:
        verify_recovery_code(plain_code, db, nonexistent_uuid)
    assert excinfo.value.status_code == 404


def test_verify_recovery_code_empty_codes(test_db):
    """Test that verifying a code when recovery_codes is empty fails."""
    db, engine, SessionLocal = test_db
    # Generate codes
    codes = generate_recovery_codes()
    plain_code, _ = codes[0]

    # Create a user with empty recovery codes
    from app.auth import ph

    user = User(
        id=str(uuid.uuid4()),
        email="test@example.com",
        hashed_password=ph.hash("password"),
        is_active=True,
        is_superuser=True,
        totp_secret="JBSWY3DPEHPK3PXP",
        recovery_codes="[]",
    )

    db.add(user)
    db.commit()
    user_uuid = str(user.id)

    # Should fail
    result = verify_recovery_code(plain_code, db, user_uuid)
    assert result is False
