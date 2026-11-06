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
    got = client.get(f"{URL}/auto-import").json()
    assert {k: got[k] for k in ("on", "source", "imported_at", "pending")} == {
        "on": False,
        "source": None,
        "imported_at": None,
        "pending": False,
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


def test_ui_toggle_without_a_shared_folder(open_page, owner, monkeypatch):
    from app.routes import https_admin

    def no_folder():
        raise https_admin.BackupError("not SQLite")

    monkeypatch.setattr(https_admin, "database_path", no_folder)
    page = open_page()
    _ui.ui_login(page, owner)
    _ui.go_settings(page, "admin")
    page.get_by_test_id("https-auto-import").check()
    expect(page.get_by_test_id("cert-popup-text")).to_contain_text("cert-import")
    expect(page.get_by_test_id("cert-popup-retry")).to_be_visible()
    page.get_by_test_id("cert-popup-close").click()
    expect(page.get_by_test_id("cert-popup")).to_have_count(0)
    expect(page.get_by_test_id("https-auto-status")).to_contain_text("Not imported")


def test_ui_popup_shows_the_servers_answer(open_page, owner, tmp_path, monkeypatch):
    from app.routes import https_admin

    monkeypatch.setattr(
        https_admin, "database_path", lambda: tmp_path / "smart_home.db"
    )
    (tmp_path / "cert-import-result").write_text("same\nold\n")  # cleared
    page = open_page()
    _ui.ui_login(page, owner)
    _ui.go_settings(page, "admin")
    page.evaluate("window.smartHomeApp.certPollMs = 200")
    page.get_by_test_id("https-auto-import").check()
    expect(page.get_by_test_id("cert-popup-text")).to_contain_text("Asking the server")
    assert (tmp_path / "cert-import-requested").exists()
    assert not (tmp_path / "cert-import-result").exists()
    # What smarthome-cert.service does on the server.
    (tmp_path / "cert-import-result").write_text(
        "refused\nFrom /etc/httpd/conf.d/ssl.conf: the key does not match\n"
    )
    (tmp_path / "cert-import-requested").unlink()
    text = page.get_by_test_id("cert-popup-text")
    expect(text).to_contain_text("The app refused the certificate. From /etc/httpd")
    expect(text).to_have_attribute("data-result", "refused")
    # Try again asks the server once more, in the same popup.
    page.get_by_test_id("cert-popup-retry").click()
    expect(text).to_contain_text("Asking the server")
    expect(page.get_by_test_id("cert-popup-retry")).to_be_hidden()
    assert (tmp_path / "cert-import-requested").exists()
    (tmp_path / "cert-import-result").write_text("changed\nFrom /etc/x.\n")
    (tmp_path / "cert-import-requested").unlink()
    expect(text).to_contain_text("Imported")
    expect(page.get_by_test_id("cert-popup-retry")).to_be_hidden()
    page.get_by_test_id("cert-popup-close").click()
    # Fetch now asks again.
    page.get_by_test_id("https-auto-fetch").click()
    expect(page.get_by_test_id("cert-popup-text")).to_contain_text("Asking the server")
    (tmp_path / "cert-import-result").write_text("same\nFrom /etc/x.\n")
    (tmp_path / "cert-import-requested").unlink()
    expect(page.get_by_test_id("cert-popup-text")).to_contain_text("already has")


def test_fetch_now_needs_it_on(client, owner, login, csrf):
    assert login(client, owner).status_code == 200
    r = client.post(f"{URL}/auto-import/request", json={}, headers=csrf(client))
    assert r.status_code == 409


def test_last_check_is_read_safely(tmp_path):
    from app.routes import https_admin

    (tmp_path / "cert-import-result").write_text("<script>\n" + "x" * 900)
    check = https_admin._last_check(tmp_path)
    assert check is not None
    assert check["status"] == "unknown" and len(check["message"]) == 500
    assert https_admin._last_check(tmp_path / "missing") is None


def test_switching_on_asks_the_server(
    client, owner, login, csrf, tmp_path, monkeypatch
):
    from app.routes import https_admin

    monkeypatch.setattr(
        https_admin, "database_path", lambda: tmp_path / "smart_home.db"
    )
    assert login(client, owner).status_code == 200
    client.put(f"{URL}/auto-import", json={"enabled": False}, headers=csrf(client))
    assert not (tmp_path / "cert-import-requested").exists()
    client.put(f"{URL}/auto-import", json={"enabled": True}, headers=csrf(client))
    assert (tmp_path / "cert-import-requested").exists()


@pytest.mark.skipif(os.name == "nt", reason="Linux deploy script")
def test_units_watch_for_the_request(tmp_path):
    units, data = tmp_path / "systemd", tmp_path / "volume"
    units.mkdir()
    data.mkdir()
    script = (
        f'ROOT="{REPO}"; SELF=smarthome; SERVICE=smart-home; OFFSITE_DIR="{units}"; '
        f'compose() {{ echo abc123; }}; docker() {{ echo "{data}"; }}; '
        'as_root() { "$@"; }; systemctl() { echo "systemctl $*" >> "$OFFSITE_DIR/calls"; }; '
        f'. "{REPO}/deploy/linux/certificates.sh"; cert_units_install'
    )
    r = subprocess.run(
        ["bash", "-c", script], capture_output=True, text=True, timeout=30
    )  # noqa: S603, S607
    assert r.returncode == 0, r.stderr
    path_unit = (units / "smarthome-cert.path").read_text()
    assert f"PathExists={data}/cert-import-requested" in path_unit
    service = (units / "smarthome-cert.service").read_text()
    # bash runs the script: SELinux does not let systemd run one in /root.
    assert (
        f"ExecStart=/bin/bash {REPO}/deploy/linux/smarthome cert-import --quiet --report"
        in service
    )
    assert f"ExecStopPost=/bin/rm -f {data}/cert-import-requested" in service
    calls = (units / "calls").read_text()
    assert (
        "enable --now smarthome-cert.path" in calls
        and "enable --now smarthome-cert.timer" in calls
    )
    # Nothing changed: nothing is reinstalled or restarted.
    (units / "calls").unlink()
    subprocess.run(["bash", "-c", script], capture_output=True, text=True, timeout=30)  # noqa: S603, S607
    assert not (units / "calls").exists()


def run_import(tmp_path, stubs):
    data = tmp_path / "volume"
    data.mkdir(exist_ok=True)
    script = (
        f'ROOT="{REPO}"; SELF=smarthome; SERVICE=smart-home; '
        'say() { :; }; die() { echo "$*" >&2; exit 1; }; need_docker() { :; }; '
        'as_root() { "$@"; }; wait_healthy() { :; }; '
        f'docker() {{ echo "{data}"; }}; '
        f'. "{REPO}/deploy/linux/certificates.sh"; '
        f"{stubs}; cmd_cert_import --quiet --report"
    )
    r = subprocess.run(
        ["bash", "-c", script], capture_output=True, text=True, timeout=30
    )  # noqa: S603, S607
    return r, (data / "cert-import-result").read_text().splitlines()


@pytest.mark.skipif(os.name == "nt", reason="Linux deploy script")
def test_import_reports_for_the_popup(tmp_path):
    r, lines = run_import(
        tmp_path, "cert_find() { return 1; }; compose() { echo abc123; }"
    )
    assert r.returncode == 1 and lines[0] == "not_found"
    found = "cert_find() { echo /c.crt /c.key /etc/httpd/conf.d/ssl.conf; }; cert_read() { echo PEM; }"
    refuse = 'compose() { [[ $1 == ps ]] && { echo abc; return; }; cat >/dev/null; echo "refused: no match" >&2; return 2; }'
    r, lines = run_import(tmp_path, f"{found}; {refuse}")
    assert r.returncode == 1
    assert lines == ["refused", "From /etc/httpd/conf.d/ssl.conf: no match"]
    accept = "compose() { [[ $1 == ps ]] && { echo abc; return; }; [[ $1 == exec ]] && { cat >/dev/null; echo changed; }; return 0; }"
    r, lines = run_import(tmp_path, f"{found}; {accept}")
    assert r.returncode == 0, r.stderr
    assert lines == ["changed", "From /etc/httpd/conf.d/ssl.conf."]
