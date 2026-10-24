#!/usr/bin/env python
"""Tests for create_owner.py"""

import os
import shutil
import tempfile
import uuid
from unittest.mock import patch

import pytest

from app import db_config
from app.auth import hash_password
from app.models import User


@pytest.fixture
def temp_db():
    """Create a temporary in-memory database for testing."""
    import importlib

    # Create a temp directory for the database file
    temp_dir = tempfile.mkdtemp()
    db_path = os.path.join(temp_dir, "test.db")

    # Set the DATABASE_URL for testing
    os.environ["DATABASE_URL"] = f"sqlite:///{db_path}"

    # Reload db_config to pick up the new DATABASE_URL
    from app import db_config

    importlib.reload(db_config)

    # Create tables
    from app.models import Base

    Base.metadata.create_all(bind=db_config.engine)

    yield db_path

    # Cleanup
    shutil.rmtree(temp_dir, ignore_errors=True)

    # Clean up db_config
    importlib.reload(db_config)


def test_create_owner_success(temp_db):
    """Test successful owner creation with valid credentials."""

    from scripts.create_owner import main

    # Create a mock input function
    mock_input = [
        "test@example.com",
        "SecurePass123",
    ]
    input_mock = iter(mock_input)

    def mock_input_func(prompt=""):
        return next(input_mock)

    # Run the script
    with patch("builtins.input", mock_input_func):
        result = main()

    assert result == 0

    # Verify owner was created
    with db_config.SessionLocal() as session:
        owner = session.query(User).filter(User.is_superuser).first()

    assert owner is not None
    assert owner.email == "test@example.com"
    assert owner.is_superuser is True
    assert owner.is_active is True
    assert owner.id is not None


def test_create_owner_already_exists(temp_db):
    """Test that script refuses to create owner if one already exists."""

    from scripts.create_owner import main

    # First, create an owner manually
    with db_config.SessionLocal() as session:
        existing_owner = User(
            id=str(uuid.uuid4()),
            email="existing@example.com",
            hashed_password=hash_password("ExistingPass123"),
            is_active=True,
            is_superuser=True,
        )
        session.add(existing_owner)
        session.commit()

    # Now try to create another owner
    mock_input = [
        "new@example.com",
        "NewPass123",
    ]
    input_mock = iter(mock_input)

    def mock_input_func(prompt=""):
        return next(input_mock)

    # Run the script
    with patch("builtins.input", mock_input_func):
        result = main()

    assert result == 1  # Script should return 1 for failure

    # Verify no new owner was created
    with db_config.SessionLocal() as session:
        owner = session.query(User).filter(User.is_superuser.is_(True)).one()

    assert owner.email == "existing@example.com"


def test_create_owner_invalid_email(temp_db):
    """Test that script rejects invalid email addresses."""
    from scripts.create_owner import main

    mock_input = [
        "invalid-email",  # No @ symbol
        "SecurePass123",
    ]
    input_mock = iter(mock_input)

    def mock_input_func(prompt=""):
        return next(input_mock)

    # Run the script
    with patch("builtins.input", mock_input_func):
        result = main()

    assert result == 1  # Script should return 1 for failure


def test_create_owner_empty_email(temp_db):
    """Test that script rejects empty email."""
    from scripts.create_owner import main

    mock_input = [
        "",  # Empty email
        "SecurePass123",
    ]
    input_mock = iter(mock_input)

    def mock_input_func(prompt=""):
        return next(input_mock)

    # Run the script
    with patch("builtins.input", mock_input_func):
        result = main()

    assert result == 1  # Script should return 1 for failure


def test_create_owner_empty_password(temp_db):
    """Test that script rejects empty password."""
    from scripts.create_owner import main

    mock_input = [
        "test@example.com",
        "",  # Empty password
    ]
    input_mock = iter(mock_input)

    def mock_input_func(prompt=""):
        return next(input_mock)

    # Run the script
    with patch("builtins.input", mock_input_func):
        result = main()

    assert result == 1  # Script should return 1 for failure


def test_create_owner_password_too_short(temp_db):
    """Test that script rejects password shorter than 12 characters."""
    from scripts.create_owner import main

    mock_input = [
        "test@example.com",
        "ShortPass",  # Only 9 characters
    ]
    input_mock = iter(mock_input)

    def mock_input_func(prompt=""):
        return next(input_mock)

    # Run the script
    with patch("builtins.input", mock_input_func):
        result = main()

    assert result == 1  # Script should return 1 for failure


def test_create_owner_password_meets_requirements(temp_db):
    """Test that password with exactly 12 characters is accepted."""
    from scripts.create_owner import main

    mock_input = [
        "test@example.com",
        "SecurePass12",  # Exactly 12 characters
    ]
    input_mock = iter(mock_input)

    def mock_input_func(prompt=""):
        return next(input_mock)

    # Run the script
    with patch("builtins.input", mock_input_func):
        result = main()

    assert result == 0  # Script should return 0 for success

    # Verify owner was created
    with db_config.SessionLocal() as session:
        owner = session.query(User).filter(User.is_superuser.is_(True)).first()

    assert owner is not None
    assert owner.email == "test@example.com"
    # Verify password was hashed
    assert owner.hashed_password != "SecurePass12"


def test_owner_uses_hash_password(temp_db):
    """Test that the owner's password is properly hashed with Argon2id."""
    from scripts.create_owner import main

    original_password = "TestPass123!"
    mock_input = [
        "test@example.com",
        original_password,
    ]
    input_mock = iter(mock_input)

    def mock_input_func(prompt=""):
        return next(input_mock)

    # Run the script
    with patch("builtins.input", mock_input_func):
        result = main()

    assert result == 0

    # Verify owner was created
    with db_config.SessionLocal() as session:
        owner = session.query(User).filter(User.is_superuser.is_(True)).first()

    assert owner is not None

    # Verify password was hashed (should not be plain text)
    assert owner.hashed_password != original_password

    # Verify it starts with Argon2 hash prefix
    assert owner.hashed_password.startswith("$argon2")

    # Verify that verify_password works
    from backend.app.auth import verify_password

    assert verify_password(original_password, owner.hashed_password) is True
