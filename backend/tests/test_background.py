"""A person's own background picture: upload, switch on and off, remove.
Only real pictures (by their first bytes), up to 3 MB, and only for them."""

import base64
import re
import struct
import zlib

from playwright.sync_api import expect

from app.models import User
from tests import test_ui as _ui

URL = "/api/v1/account/background"
HAS = re.compile("has-background")


def png(width=4, height=4):
    def chunk(kind, data):
        body = kind + data
        return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body))

    raw = b"".join(b"\x00" + b"\x40\x80\xc0" * width for _ in range(height))
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(raw))
        + chunk(b"IEND", b"")
    )


def data_url(data, kind="image/png"):
    return f"data:{kind};base64,{base64.b64encode(data).decode()}"


def test_upload_switch_and_remove(
    client, db, owner, make_user, new_client, login, csrf
):
    assert login(client, owner).status_code == 200
    account = client.get("/api/v1/account").json()
    assert account["background"] == {"on": False, "image": False, "version": None}
    r = client.put(f"{URL}/on", json={"on": True}, headers=csrf(client))
    assert r.status_code == 409  # nothing to show yet

    picture = png()
    r = client.put(URL, json={"image": data_url(picture)}, headers=csrf(client))
    assert r.status_code == 200, r.text
    assert r.json()["on"] is True and r.json()["version"]
    got = client.get(URL)
    assert got.status_code == 200 and got.content == picture
    assert got.headers["content-type"] == "image/png"
    assert got.headers["x-content-type-options"] == "nosniff"

    r = client.put(f"{URL}/on", json={"on": False}, headers=csrf(client))
    assert r.json() == {**r.json(), "on": False, "image": True}
    assert client.get("/api/v1/account").json()["background"]["on"] is False

    # Someone else has none, and cannot see this one.
    member = make_user(owner.home_id, role="member")
    other = new_client()
    assert login(other, member).status_code == 200
    assert other.get(URL).status_code == 404

    assert client.put(URL, json={"image": data_url(picture)}).status_code == 403  # CSRF
    r = client.delete(URL, headers=csrf(client))
    assert r.json() == {"on": False, "image": False, "version": None}
    assert client.get(URL).status_code == 404
    db.expire_all()
    assert db.get(User, owner.id).background_image is None


def test_only_pictures_up_to_3_mb(client, owner, login, csrf):
    assert login(client, owner).status_code == 200
    for bad in (
        data_url(b"<svg xmlns='http://www.w3.org/2000/svg'/>", "image/svg+xml"),
        data_url(b"<html><script>alert(1)</script>", "image/png"),  # says png, is not
        "not base64 !!",
    ):
        assert (
            client.put(URL, json={"image": bad}, headers=csrf(client)).status_code
            == 422
        )
    big = png() + b"\x00" * (3 * 1024 * 1024)
    r = client.put(URL, json={"image": data_url(big)}, headers=csrf(client))
    assert r.status_code in (413, 422)
    webp = b"RIFF\x24\x00\x00\x00WEBPVP8 " + b"\x00" * 24
    r = client.put(
        URL, json={"image": data_url(webp, "image/webp")}, headers=csrf(client)
    )
    assert r.status_code == 200
    jpeg = b"\xff\xd8\xff\xe0" + b"\x00" * 20
    r = client.put(
        URL, json={"image": base64.b64encode(jpeg).decode()}, headers=csrf(client)
    )
    assert r.status_code == 200
    assert client.get(URL).headers["content-type"] == "image/jpeg"


def test_ui_background_picture(open_page, owner, tmp_path):
    page = open_page()
    _ui.ui_login(page, owner)
    box = _ui.go_settings(page, "account").get_by_test_id("background")
    expect(box.get_by_test_id("background-on")).to_be_disabled()
    picture = tmp_path / "sky.png"
    picture.write_bytes(png(8, 8))
    box.get_by_test_id("background-file").set_input_files(str(picture))
    body = page.locator("body")
    expect(body).to_have_class(HAS)
    expect(page.get_by_test_id("status")).to_contain_text("Background picture saved")
    image = page.evaluate("getComputedStyle(document.body).backgroundImage")
    assert "/api/v1/account/background?v=" in image
    # The picture loads (same origin, allowed by the page's rules).
    ok = page.evaluate(
        "() => new Promise((done) => { const i = new Image(); i.onload = () => done(true);"
        " i.onerror = () => done(false); i.src = '/api/v1/account/background'; })"
    )
    assert ok

    box.get_by_test_id("background-on").uncheck()
    expect(body).not_to_have_class(HAS)
    page.reload()
    expect(page.get_by_test_id("app-shell")).to_be_visible()
    expect(body).not_to_have_class(HAS)
    box = _ui.go_settings(page, "account").get_by_test_id("background")
    box.get_by_test_id("background-on").check()
    expect(body).to_have_class(HAS)
    box.get_by_test_id("background-remove").click()
    expect(body).not_to_have_class(HAS)
    expect(box.get_by_test_id("background-on")).to_be_disabled()
