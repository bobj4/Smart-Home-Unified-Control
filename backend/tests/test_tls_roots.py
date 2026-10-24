"""Outbound HTTPS trusts the public root certificates too (Rheem's server
moved to a root Windows had not downloaded). Written by the reviewer. Do not
edit, skip, mark or delete these tests."""

import os
import ssl

import certifi

import app


def test_public_roots_are_added(monkeypatch):
    monkeypatch.delenv("SSL_CERT_FILE", raising=False)
    app.trust_public_roots()
    assert os.environ["SSL_CERT_FILE"] == certifi.where()
    # The default context, as aiohttp and pycync build it, now has them.
    context = ssl.create_default_context()
    assert context.cert_store_stats()["x509_ca"] > 50
    assert context.verify_mode == ssl.CERT_REQUIRED and context.check_hostname


def test_an_owner_setting_is_kept(monkeypatch):
    monkeypatch.setenv("SSL_CERT_FILE", "C:/certs/mine.pem")
    app.trust_public_roots()
    assert os.environ["SSL_CERT_FILE"] == "C:/certs/mine.pem"
