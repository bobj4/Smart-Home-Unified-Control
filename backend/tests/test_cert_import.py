# ruff: noqa: F811 (a fixture shared with test_https)
"""Taking the HTTPS certificate from the server's web server: the setting,
the app-side import, and how deploy/linux/smarthome finds the files for
Apache, nginx, Caddy and certbot (in a folder standing in for /)."""

import os
import subprocess
from pathlib import Path

import pytest
from playwright.sync_api import expect

from app.models import AuditEvent
from scripts import import_certificate as importer
from tests import test_ui as _ui
from tests.test_https import make_pair, secrets_key  # noqa: F401

REPO = Path(__file__).resolve().parents[2]
URL = "/api/v1/admin/https"


def test_setting(client, owner, make_user, new_client, login, csrf):
    assert login(client, owner).status_code == 200
    assert client.get(f"{URL}/auto-import").json() == {
        "on": False,
        "source": None,
        "imported_at": None,
    }
    r = client.put(f"{URL}/auto-import", json={"enabled": True}, headers=csrf(client))
    assert r.status_code == 200 and r.json()["on"] is True
    operator = make_user(owner.home_id, role="operator")
    o = new_client()
    assert login(o, operator).status_code == 200
    assert (
        o.put(f"{URL}/auto-import", json={"enabled": True}, headers=csrf(o)).status_code
        == 403
    )


def test_parse():
    source, cert, key = importer.parse(
        f"/etc/httpd/conf.d/ssl.conf\nCERT\n{importer.SPLIT}\nKEY\n"
    )
    assert (source, cert, key) == ("/etc/httpd/conf.d/ssl.conf", "CERT\n", "KEY\n")
    with pytest.raises(ValueError):
        importer.parse("source\nonly a certificate")


def test_apply(db, secrets_key):
    from app.login_policy import settings

    cert, key = make_pair()
    assert importer.apply(db, "certbot", cert, key) == "off"
    settings(db).cert_auto_import = True
    db.commit()
    assert importer.apply(db, "certbot", cert, key) == "changed"
    assert importer.apply(db, "certbot", cert, key) == "same"
    row = settings(db)
    assert row.cert_import_source == "certbot" and row.cert_imported_at is not None
    assert (
        db.query(AuditEvent).filter_by(event_type="https_certificate_imported").count()
        == 1
    )
    other_cert, _ = make_pair()
    with pytest.raises(ValueError):  # tls.TlsError
        importer.apply(db, "certbot", other_cert, key)  # key does not match


def find(root: Path) -> str:
    script = (
        'conf_get() { printf "%s" "$2"; }; '
        f'. "{REPO}/deploy/linux/certificates.sh"; cert_find'
    )
    r = subprocess.run(  # noqa: S603
        ["bash", "-c", script],
        env={**os.environ, "SMARTHOME_CERT_ROOT": str(root)},
        capture_output=True,
        text=True,
        timeout=30,
    )
    return r.stdout.strip() if r.returncode == 0 else ""


def put(root: Path, path: str, text: str = "x") -> None:
    target = root / path.lstrip("/")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text)


@pytest.mark.skipif(os.name == "nt", reason="Linux deploy script")
def test_finding_the_web_servers_certificate(tmp_path):
    assert find(tmp_path) == ""
    # certbot alone
    put(tmp_path, "/etc/letsencrypt/live/home.example/fullchain.pem")
    put(tmp_path, "/etc/letsencrypt/live/home.example/privkey.pem")
    assert find(tmp_path).startswith(
        "/etc/letsencrypt/live/home.example/fullchain.pem "
    )
    # Apache wins; its self-signed placeholder is skipped
    put(
        tmp_path,
        "/etc/httpd/conf.d/ssl.conf",
        "SSLCertificateFile /etc/pki/tls/certs/localhost.crt\nSSLCertificateKeyFile /etc/pki/tls/private/localhost.key\n",
    )
    put(tmp_path, "/etc/pki/tls/certs/localhost.crt")
    put(tmp_path, "/etc/pki/tls/private/localhost.key")
    put(
        tmp_path,
        "/etc/httpd/conf.d/smarthome.conf",
        "  SSLCertificateFile /etc/ssl/home.crt  # ours\n  SSLCertificateKeyFile /etc/ssl/home.key\n",
    )
    put(tmp_path, "/etc/ssl/home.crt")
    put(tmp_path, "/etc/ssl/home.key")
    assert (
        find(tmp_path)
        == "/etc/ssl/home.crt /etc/ssl/home.key /etc/httpd/conf.d/smarthome.conf"
    )


@pytest.mark.skipif(os.name == "nt", reason="Linux deploy script")
def test_finding_nginx_and_caddy(tmp_path):
    put(
        tmp_path,
        "/var/lib/caddy/.local/share/caddy/certificates/acme/home.example/home.example.crt",
    )
    put(
        tmp_path,
        "/var/lib/caddy/.local/share/caddy/certificates/acme/home.example/home.example.key",
    )
    assert find(tmp_path).endswith(" Caddy")
    put(
        tmp_path,
        "/etc/nginx/conf.d/home.conf",
        "ssl_certificate /etc/ssl/n.crt;\nssl_certificate_key /etc/ssl/n.key;\n",
    )
    put(tmp_path, "/etc/ssl/n.crt")
    put(tmp_path, "/etc/ssl/n.key")
    assert find(tmp_path) == "/etc/ssl/n.crt /etc/ssl/n.key /etc/nginx/conf.d/home.conf"


def test_ui_toggle(open_page, owner):
    page = open_page()
    _ui.ui_login(page, owner)
    _ui.go_settings(page, "admin")
    page.get_by_test_id("https-auto-import").check()
    expect(page.get_by_test_id("status")).to_contain_text("imports the certificate")
    expect(page.get_by_test_id("https-auto-status")).to_contain_text("cert-auto-setup")
