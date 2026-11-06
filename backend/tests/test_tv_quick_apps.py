# ruff: noqa: F811 (fixtures shared with test_samsung)
"""A TV tile's ⋯ menu: choose up to six installed apps for the remote's
quick buttons; those buttons start the app by the TV's own id."""

import json

from playwright.sync_api import expect

from app import features
from app.integrations import samsung
from app.models import Device
from app.routes import samsung as samsung_routes
from tests import test_ui as _ui
from tests.test_samsung import command, ready_tv, secrets_key, tv, url  # noqa: F401

APPS = [
    {"id": "3201907018807", "name": "Netflix"},
    {"id": "111299001912", "name": "YouTube"},
    {"id": "3201910019365", "name": "Plex"},
]


def quick(client, csrf, home_id, device_id, apps):
    return client.put(
        url(home_id, f"/integrations/samsung_tv/tvs/{device_id}/quick-apps"),
        json={"apps": apps},
        headers=csrf(client),
    )


def test_installed_apps_sorted(
    client, owner, login, csrf, tv, secrets_key, monkeypatch
):
    device_id = ready_tv(client, csrf, login, owner, tv)
    monkeypatch.setattr(samsung, "installed_apps", lambda host, protocol, token: APPS)
    r = client.get(url(owner.home_id, f"/integrations/samsung_tv/tvs/{device_id}/apps"))
    assert r.status_code == 200, r.text
    assert [a["name"] for a in r.json()] == ["Netflix", "Plex", "YouTube"]


def test_choose_and_open_quick_app(
    client,
    db,
    owner,
    login,
    csrf,
    tv,
    secrets_key,
    monkeypatch,
):
    device_id = ready_tv(client, csrf, login, owner, tv)
    r = quick(client, csrf, owner.home_id, device_id, APPS[2:])
    assert r.status_code == 200, r.text
    assert r.json()["quick_apps"] == APPS[2:]
    devices = client.get(url(owner.home_id, "/devices")).json()
    assert next(d for d in devices if d["id"] == device_id)["quick_apps"] == APPS[2:]

    started = []
    monkeypatch.setattr(
        samsung, "_tizen_call", lambda host, token, action: action(object())
    )
    monkeypatch.setattr(
        samsung, "_start_app", lambda tv, app_id: started.append(app_id)
    )
    r = command(
        client, csrf, owner.home_id, device_id, "open_app", app_id="3201910019365"
    )
    assert r.status_code == 200, r.text
    assert started == ["3201910019365"]
    assert json.loads(db.get(Device, device_id).state)["app"] == "3201910019365"
    for bad in ("", "a b", "x" * 101, 5):
        r = command(client, csrf, owner.home_id, device_id, "open_app", app_id=bad)
        assert r.status_code == 422, bad


def test_quick_apps_rules(client, db, owner, login, csrf, tv, secrets_key):
    device_id = ready_tv(client, csrf, login, owner, tv)
    seven = [{"id": str(n), "name": f"App {n}"} for n in range(7)]
    assert quick(client, csrf, owner.home_id, device_id, seven).status_code == 422
    twice = [APPS[0], APPS[0]]
    assert quick(client, csrf, owner.home_id, device_id, twice).status_code == 422
    bad_id = [{"id": "no spaces", "name": "X"}]
    assert quick(client, csrf, owner.home_id, device_id, bad_id).status_code == 422
    assert quick(client, csrf, owner.home_id, device_id, seven[:6]).status_code == 200
    # Editing the TV keeps them.
    r = client.put(
        url(owner.home_id, f"/integrations/samsung_tv/tvs/{device_id}"),
        json={"name": "Den TV", "host": "192.168.1.50"},
        headers=csrf(client),
    )
    assert r.status_code == 200, r.text
    devices = client.get(url(owner.home_id, "/devices")).json()
    assert len(next(d for d in devices if d["id"] == device_id)["quick_apps"]) == 6
    assert quick(client, csrf, owner.home_id, device_id, []).json()["quick_apps"] == []


def _ui_tv(db, owner, make_device, quick_apps=None):
    device_id = make_device(owner.home_id, device_type="tv", name="Den TV")
    device = db.get(Device, device_id)
    device.integration = "samsung_tv"
    device.external_id = "192.168.1.60"
    device.capabilities = json.dumps(
        {"protocol": "tizen", "paired": True, "quick_apps": quick_apps or []}
    )
    device.state = json.dumps({"on": True})
    db.commit()
    features.set_integration(db, owner.home_id, "samsung_tv", True, None, None)
    return device_id


def test_ui_pick_quick_apps(open_page, db, owner, make_device, monkeypatch):
    device_id = _ui_tv(db, owner, make_device)
    many = [{"id": f"app{n}", "name": f"App {n}"} for n in range(8)]
    monkeypatch.setattr(samsung_routes, "tv_apps", lambda db, device: many)
    page = open_page()
    _ui.ui_login(page, owner)
    tile = _ui.card(page, "Den TV")
    tile.get_by_test_id("tv-quick-menu").click()
    panel = page.get_by_test_id("quick-apps-panel")
    for n in range(6):
        panel.get_by_test_id(f"quick-app-app{n}").check()
    expect(panel.get_by_test_id("quick-app-app6")).to_be_disabled()
    expect(panel.get_by_test_id("quick-apps-count")).to_have_text("6 of 6 chosen")
    panel.get_by_test_id("quick-app-app5").uncheck()
    panel.get_by_test_id("quick-app-app4").uncheck()
    panel.get_by_test_id("quick-apps-save").click()
    expect(panel).to_be_hidden()
    db.expire_all()
    saved = json.loads(db.get(Device, device_id).capabilities)["quick_apps"]
    assert [a["id"] for a in saved] == ["app0", "app1", "app2", "app3"]

    tile.get_by_test_id("tv-remote-open").click()
    buttons = page.get_by_test_id("remote-apps").locator("button")
    expect(buttons).to_have_count(4)
    # Three on the first row; the fourth has the second row to itself.
    first, fourth = buttons.nth(0).bounding_box(), buttons.nth(3).bounding_box()
    assert fourth["y"] > first["y"] and fourth["width"] > first["width"] * 2


def test_ui_three_apps_one_row(open_page, db, owner, make_device):
    _ui_tv(db, owner, make_device, quick_apps=APPS)
    page = open_page()
    _ui.ui_login(page, owner)
    _ui.card(page, "Den TV").get_by_test_id("tv-remote-open").click()
    buttons = page.get_by_test_id("remote-apps").locator("button")
    expect(buttons).to_have_count(3)
    ys = {round(buttons.nth(i).bounding_box()["y"]) for i in range(3)}
    assert len(ys) == 1


def test_ui_no_menu_for_members_or_old_tvs(
    open_page, db, owner, make_device, make_user
):
    _ui_tv(db, owner, make_device)
    old = make_device(owner.home_id, device_type="tv", name="Old TV")
    device = db.get(Device, old)
    device.integration = "samsung_tv"
    device.capabilities = json.dumps({"protocol": "legacy", "paired": True})
    db.commit()
    page = open_page()
    _ui.ui_login(page, owner)
    expect(_ui.card(page, "Den TV").get_by_test_id("tv-quick-menu")).to_be_visible()
    expect(_ui.card(page, "Old TV").get_by_test_id("tv-quick-menu")).to_have_count(0)
    member = make_user(owner.home_id, role="member")
    other = open_page()
    _ui.ui_login(other, member)
    expect(_ui.card(other, "Den TV")).to_be_visible()
    expect(_ui.card(other, "Den TV").get_by_test_id("tv-quick-menu")).to_have_count(0)
