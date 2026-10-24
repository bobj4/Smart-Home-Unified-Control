"""Shared test setup. Written by the reviewer (Review 2). Do not edit.

Points the app at a throwaway database before any app module is imported, so
tests never read or write smart_home.db, and gives every test an empty schema.
"""

import os
import tempfile
from pathlib import Path

_TMP_DIR = Path(tempfile.mkdtemp(prefix="smarthome-tests-"))
TEST_DATABASE_URL = "sqlite:///" + (_TMP_DIR / "test.db").as_posix()
os.environ["DATABASE_URL"] = TEST_DATABASE_URL
os.environ["CORS_ORIGINS"] = ""

import importlib  # noqa: E402
import json  # noqa: E402
import socket  # noqa: E402
import threading  # noqa: E402
import time  # noqa: E402
import uuid  # noqa: E402
from types import SimpleNamespace  # noqa: E402

import pyotp  # noqa: E402
import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from playwright.sync_api import Page, sync_playwright  # noqa: E402

from app import db_config  # noqa: E402
from app.auth import generate_recovery_codes, hash_password  # noqa: E402
from app.models import Base, Device, Home, HomeMembership, User  # noqa: E402

BACKEND_DIR = Path(__file__).resolve().parents[1]
REPO_DIR = BACKEND_DIR.parent
PASSWORD = "correct horse battery staple 7"
# https so the test client sends Secure cookies back, like a browser would.
BASE_URL = "https://testserver"
LOGIN_URL = "/api/v1/auth/login"


@pytest.fixture(autouse=True)
def _fresh_database():
    # Another test may have pointed db_config at its own database; undo that.
    if (
        os.environ.get("DATABASE_URL") != TEST_DATABASE_URL
        or str(db_config.engine.url) != TEST_DATABASE_URL
    ):
        os.environ["DATABASE_URL"] = TEST_DATABASE_URL
        importlib.reload(db_config)
    Base.metadata.drop_all(bind=db_config.engine)
    Base.metadata.create_all(bind=db_config.engine)
    from app import rate_limiter

    reset = getattr(rate_limiter, "reset_rate_limits", None)
    if reset is not None:
        reset()
    yield


@pytest.fixture
def db():
    session = db_config.SessionLocal()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def app():
    from main import app as fastapi_app

    return fastapi_app


@pytest.fixture
def client(app):
    with TestClient(app, base_url=BASE_URL) as test_client:
        yield test_client


@pytest.fixture
def new_client(app):
    """Factory for extra clients (a second browser, an attacker)."""
    made = []

    def _make():
        test_client = TestClient(app, base_url=BASE_URL)
        made.append(test_client)
        return test_client

    yield _make
    for test_client in made:
        test_client.close()


@pytest.fixture
def make_home(db):
    def _make(name="Home"):
        home = Home(id=str(uuid.uuid4()), name=name, type="residential")
        db.add(home)
        db.commit()
        return home.id

    return _make


@pytest.fixture
def make_user(db):
    """Create an active user with TOTP enabled and a membership in one home."""

    def _make(home_id, role="admin"):
        role = "admin" if role == "owner" else role  # owner was folded into admin
        secret = pyotp.random_base32()
        codes = generate_recovery_codes()
        user = User(
            id=str(uuid.uuid4()),
            email=f"user-{uuid.uuid4().hex[:10]}@example.com",
            hashed_password=hash_password(PASSWORD),
            is_active=True,
            totp_secret=secret,
            is_totp_enabled=True,
            recovery_codes=json.dumps([hashed for _, hashed in codes]),
        )
        db.add(user)
        db.flush()
        db.add(
            HomeMembership(
                id=str(uuid.uuid4()), user_id=user.id, home_id=home_id, role=role
            )
        )
        db.commit()
        return SimpleNamespace(
            id=user.id,
            email=user.email,
            password=PASSWORD,
            totp_secret=secret,
            totp=pyotp.TOTP(secret),
            recovery_codes=[plain for plain, _ in codes],
            home_id=home_id,
        )

    return _make


@pytest.fixture
def owner(make_home, make_user):
    # There is no owner role any more: the first person is an admin.
    return make_user(make_home("Home A"), role="admin")


@pytest.fixture
def make_device(db):
    def _make(home_id, device_type="light", name="Lamp"):
        device = Device(
            id=str(uuid.uuid4()),
            home_id=home_id,
            integration="simulated",
            type=device_type,
            name=name,
            room="Lab",
            capabilities="{}",
            state="{}",
            online=True,
        )
        db.add(device)
        db.commit()
        return device.id

    return _make


@pytest.fixture
def login():
    """Log a user in with password and the current TOTP code."""

    def _login(test_client, user, totp_code=None):
        code = totp_code if totp_code is not None else user.totp.now()
        return test_client.post(
            LOGIN_URL,
            json={"email": user.email, "password": user.password, "totp_code": code},
        )

    return _login


@pytest.fixture
def csrf():
    """Headers a browser client sends on state-changing requests."""

    def _headers(test_client):
        return {"X-CSRF-Token": test_client.cookies.get("csrf_token") or ""}

    return _headers


# ------------------------------------------------------------ browser tests
# Shared by every browser test file (test_ui*.py). Added in the UI phase.


@pytest.fixture(scope="session")
def live_server():
    import uvicorn

    from main import app as fastapi_app

    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    config = uvicorn.Config(
        fastapi_app, host="127.0.0.1", port=port, log_level="warning", lifespan="off"
    )
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + 15
    while not server.started:
        assert time.monotonic() < deadline, "test server did not start"
        time.sleep(0.05)
    # localhost, not 127.0.0.1: browsers treat it as secure, so Secure
    # cookies work over plain HTTP.
    yield f"http://localhost:{port}"
    server.should_exit = True
    thread.join(timeout=10)


@pytest.fixture(scope="session")
def browser():
    executable = os.environ.get("PLAYWRIGHT_CHROMIUM_EXECUTABLE") or None
    with sync_playwright() as p:
        b = p.chromium.launch(executable_path=executable)
        yield b
        b.close()


@pytest.fixture
def open_page(browser, live_server):
    """Factory for pages, each in its own browser context (its own cookies).
    Fails the test on any uncaught script error or console.error call."""
    contexts, problems = [], []

    def _open(width=1280, height=900) -> Page:
        context = browser.new_context(
            base_url=live_server, viewport={"width": width, "height": height}
        )
        context.set_default_timeout(5000)
        contexts.append(context)
        page = context.new_page()
        page.on("pageerror", lambda e: problems.append(f"pageerror: {e}"))
        page.on(
            "console",
            lambda m: (
                problems.append(f"console.error: {m.text}")
                if m.type == "error" and "Failed to load resource" not in m.text
                else None
            ),
        )
        page.goto("/")
        return page

    yield _open
    for context in contexts:
        context.close()
    assert not problems, problems
