"""HTTPS: uploading a certificate in Settings > Admin and the HTTPS switch.

Written by the reviewer (HTTPS phase). Do not edit, skip, mark or delete
these tests. If one looks wrong, stop and report the test name and its full
failure output instead of changing it.
"""

import os
import shutil
from datetime import UTC, datetime, timedelta

import pytest
from cryptography import x509
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID
from playwright.sync_api import expect

from app import tls
from app.models import AuditEvent, SystemSettings
from tests import test_ui as _ui

go_settings, ui_login = _ui.go_settings, _ui.ui_login
HTTPS = "/api/v1/admin/https"


def make_pair(host="home.example", days=90, password=None):
    key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, host)])
    now = datetime.now(UTC)
    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(days=2))
        .not_valid_after(now + timedelta(days=days))
        .add_extension(x509.SubjectAlternativeName([x509.DNSName(host)]), False)
        .sign(key, hashes.SHA256())
    )
    encryption = (
        serialization.BestAvailableEncryption(password)
        if password
        else serialization.NoEncryption()
    )
    key_pem = key.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, encryption
    ).decode()
    return cert.public_bytes(serialization.Encoding.PEM).decode(), key_pem


@pytest.fixture
def secrets_key(monkeypatch):
    monkeypatch.setenv("SECRETS_KEY", Fernet.generate_key().decode())


def upload(client, csrf, cert, key):
    return client.put(
        f"{HTTPS}/certificate",
        json={"certificate": cert, "private_key": key},
        headers=csrf(client),
    )


def switch(client, csrf, enabled):
    return client.put(HTTPS, json={"enabled": enabled}, headers=csrf(client))


def test_only_owners_manage_https(
    client, new_client, owner, make_user, login, csrf, secrets_key
):
    admin = make_user(owner.home_id, role="operator")
    a = new_client()
    assert login(a, admin).status_code == 200
    cert, key = make_pair()
    assert a.get(HTTPS).status_code == 403
    assert upload(a, csrf, cert, key).status_code == 403
    assert switch(a, csrf, True).status_code == 403
    assert login(client, owner).status_code == 200
    assert client.put(HTTPS, json={"enabled": True}).status_code == 403  # no CSRF token


def test_upload_switch_and_remove(client, db, owner, login, csrf, secrets_key):
    assert login(client, owner).status_code == 200
    r = client.get(HTTPS)
    assert r.status_code == 200
    # The test client talks to https://testserver, so the page is "active".
    assert r.json() == {
        "enabled": False,
        "active": True,
        "restart_needed": True,
        "certificate": None,
    }
    assert switch(client, csrf, True).status_code == 409  # no certificate yet

    cert, key = make_pair()
    r = upload(client, csrf, cert, key)
    assert r.status_code == 200, r.text
    info = r.json()["certificate"]
    assert info["subject"] == "home.example"
    assert info["hostnames"] == ["home.example"]
    assert info["self_signed"] is True
    row = db.get(SystemSettings, 1)
    db.refresh(row)
    assert "PRIVATE KEY" not in row.tls_private_key  # stored encrypted
    assert "BEGIN CERTIFICATE" in row.tls_certificate
    assert "PRIVATE" not in r.text

    r = switch(client, csrf, True)
    assert r.status_code == 200
    assert (r.json()["enabled"], r.json()["restart_needed"]) == (True, False)
    assert switch(client, csrf, "yes").status_code == 422

    r = client.delete(f"{HTTPS}/certificate", headers=csrf(client))
    assert r.status_code == 200
    assert (r.json()["enabled"], r.json()["certificate"]) == (False, None)
    events = {e.event_type for e in db.query(AuditEvent).all()}
    assert {
        "https_certificate_saved",
        "https_switched",
        "https_certificate_removed",
    } <= events
    for e in db.query(AuditEvent).filter(AuditEvent.event_type.like("https%")):
        assert "PRIVATE" not in (e.details or "")


def test_bad_certificates_are_refused(client, owner, login, csrf, secrets_key):
    assert login(client, owner).status_code == 200
    cert, key = make_pair()
    other_cert, other_key = make_pair("other.example")
    expired_cert, expired_key = make_pair(days=-1)
    locked_cert, locked_key = make_pair(password=b"secret")
    cases = [
        ("not a certificate", key, "not a PEM certificate"),
        (cert, "not a key", "not a PEM private key"),
        (cert, other_key, "does not belong"),
        (expired_cert, expired_key, "expired"),
        (locked_cert, locked_key, "password"),
    ]
    for c, k, message in cases:
        r = upload(client, csrf, c, k)
        assert r.status_code == 422, (message, r.text)
        assert message in r.text
    assert upload(client, csrf, cert, "x" * 20000).status_code == 422  # too large
    assert client.get(HTTPS).json()["certificate"] is None


def test_upload_needs_the_secrets_key(client, owner, login, csrf, monkeypatch):
    monkeypatch.delenv("SECRETS_KEY", raising=False)
    assert login(client, owner).status_code == 200
    cert, key = make_pair()
    assert upload(client, csrf, cert, key).status_code == 409


def test_server_files_for_uvicorn(client, db, owner, login, csrf, secrets_key):
    assert login(client, owner).status_code == 200
    assert tls.server_files(db) is None  # HTTPS off
    cert, key = make_pair()
    assert upload(client, csrf, cert, key).status_code == 200
    assert tls.server_files(db) is None  # certificate but still off
    assert switch(client, csrf, True).status_code == 200
    db.expire_all()
    files = tls.server_files(db)
    assert files is not None
    try:
        cert_path, key_path = files
        assert cert_path.read_text().strip() == cert.strip()
        loaded = serialization.load_pem_private_key(key_path.read_bytes(), None)
        assert loaded.public_key().public_bytes(
            serialization.Encoding.PEM,
            serialization.PublicFormat.SubjectPublicKeyInfo,
        ) == x509.load_pem_x509_certificate(cert.encode()).public_key().public_bytes(
            serialization.Encoding.PEM,
            serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        if os.name == "posix":
            assert key_path.stat().st_mode & 0o077 == 0  # only the owner can read
    finally:
        shutil.rmtree(files[0].parent)


# ------------------------------------------------------------ browser


def test_ui_https_upload_and_switch(open_page, db, owner, secrets_key, tmp_path):
    cert, key = make_pair("lights.home.arpa")
    (tmp_path / "cert.pem").write_text(cert)
    (tmp_path / "key.pem").write_text(key)
    page = open_page()
    ui_login(page, owner)
    section = go_settings(page, "admin")
    box = section.get_by_test_id("https-box")
    expect(box.get_by_test_id("https-no-certificate")).to_be_visible()
    expect(box.get_by_test_id("https-toggle")).to_be_disabled()
    box.get_by_test_id("https-cert-file").set_input_files(str(tmp_path / "cert.pem"))
    box.get_by_test_id("https-key-file").set_input_files(str(tmp_path / "key.pem"))
    box.get_by_test_id("https-upload").click()
    expect(page.get_by_test_id("status")).to_have_attribute("data-kind", "success")
    expect(box.get_by_test_id("https-certificate")).to_contain_text("lights.home.arpa")
    box.get_by_test_id("https-toggle").check()
    expect(page.get_by_test_id("status")).to_have_attribute("data-kind", "success")
    expect(box.get_by_test_id("https-state")).to_contain_text("Restart the server")
    db.expire_all()
    assert db.get(SystemSettings, 1).https_enabled is True
    box.get_by_test_id("https-remove").click()
    expect(box.get_by_test_id("https-no-certificate")).to_be_visible()
