"""Installing on a phone: manifest with normal and maskable icons, iPhone
icon, and a service worker at the site root that stores nothing."""

import json
import pathlib
import struct

from playwright.sync_api import expect

WEB = pathlib.Path(__file__).parent.parent.parent / "web"


def size(name):
    data = (WEB / "icons" / name).read_bytes()
    assert data.startswith(b"\x89PNG\r\n\x1a\n"), name
    return struct.unpack(">II", data[16:24])


def test_manifest_is_installable(client):
    manifest = client.get("/manifest.json").json()
    assert manifest["display"] == "standalone" and manifest["start_url"] == "/"
    purposes = {}
    for icon in manifest["icons"]:
        name = icon["src"].removeprefix("/icons/")
        w, h = size(name)
        assert icon["sizes"] == f"{w}x{h}"
        assert client.get(icon["src"]).status_code == 200
        purposes.setdefault(icon["purpose"], []).append(w)
    assert 192 in purposes["any"] and 512 in purposes["any"]
    assert 512 in purposes["maskable"]
    assert size("apple-touch-icon.png") == (180, 180)
    json.dumps(manifest)


def test_service_worker_served_from_root(client):
    r = client.get("/sw.js")
    assert r.status_code == 200
    assert "javascript" in r.headers["content-type"]
    assert r.headers["cache-control"] == "no-cache"
    # It never caches: no Cache Storage use, so no home data stays on a phone.
    assert "caches." not in r.text


def test_page_links_install_pieces(client):
    page = client.get("/").text
    for piece in (
        'rel="manifest"',
        'rel="apple-touch-icon" href="/icons/apple-touch-icon.png"',
        'src="/js/pwa.js"',
        'name="apple-mobile-web-app-capable"',
    ):
        assert piece in page, piece


def test_ui_service_worker_registers(open_page, owner):
    page = open_page()
    expect(page.get_by_test_id("login-page")).to_be_visible()
    expect(page.locator(".auth-logo")).to_be_visible()
    scope = page.evaluate(
        "() => navigator.serviceWorker.ready.then((r) => new URL(r.scope).pathname)"
    )
    assert scope == "/"
