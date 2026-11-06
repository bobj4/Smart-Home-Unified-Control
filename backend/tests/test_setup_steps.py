"""Settings > Admin > Setting up: the steps left on a new server."""

import re

from playwright.sync_api import expect

from app.auth import hash_password
from app.models import Home, User
from tests import test_ui as _ui


def steps(client, home_id):
    r = client.get(f"/api/v1/admin/setup?home_id={home_id}")
    assert r.status_code == 200, r.text
    return {s["id"]: s["done"] for s in r.json()["steps"]}


def test_steps_follow_the_server(
    client, db, owner, make_user, make_device, new_client, login, csrf
):
    db.get(User, owner.id).hashed_password = hash_password(
        "admin"
    )  # first-start password
    db.get(Home, owner.home_id).name = "Home"
    db.commit()
    r = client.post(
        "/api/v1/auth/login",
        json={"email": owner.email, "password": "admin", "totp_code": owner.totp.now()},
    )
    assert r.status_code == 200, r.text
    first = steps(client, owner.home_id)
    assert first["password"] is False and first["home_name"] is False
    assert first["devices"] is False and first["people"] is False
    assert first["two_factor"] is True  # the owner fixture has it on
    db.get(User, owner.id).hashed_password = hash_password(owner.password)
    db.get(Home, owner.home_id).name = "Lake house"
    db.commit()
    make_user(owner.home_id, role="member")
    later = steps(client, owner.home_id)
    assert later["password"] and later["home_name"] and later["people"]
    member = make_user(owner.home_id, role="member")
    m = new_client()
    assert login(m, member).status_code == 200
    assert m.get("/api/v1/admin/setup").status_code == 403
    # Another home's id shows nothing about that home.
    assert steps(client, "not-a-home")["home_name"] is False
    assert make_device  # demo devices do not count as added devices


def test_ui_setup_steps(open_page, owner):
    page = open_page()
    _ui.ui_login(page, owner)
    _ui.go_settings(page, "admin")
    panel = page.get_by_test_id("setup-steps")
    expect(panel).to_be_visible()
    expect(panel.locator('[data-step="password"]')).to_have_attribute(
        "data-done", "true"
    )
    devices = panel.locator('[data-step="devices"]')
    expect(devices).to_have_attribute("data-done", "false")
    devices.get_by_role("link").click()
    expect(page).to_have_url(re.compile("#/settings/integrations$"))
