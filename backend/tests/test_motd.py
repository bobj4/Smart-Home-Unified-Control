"""Message of the day: set by admins, shown after login, dismissible for good;
a new message shows again."""

from playwright.sync_api import expect

from tests import test_ui as _ui

ADMIN = "/api/v1/admin/motd"
DISMISS = "/api/v1/account/motd/dismiss"


def test_motd_api(client, owner, make_user, new_client, login, csrf):
    assert login(client, owner).status_code == 200
    assert client.get("/api/v1/account").json()["motd"] is None
    r = client.put(
        ADMIN, json={"text": "  Router reboot at 9pm  "}, headers=csrf(client)
    )
    assert r.json() == {"text": "Router reboot at 9pm", "version": 1}
    same = client.put(
        ADMIN, json={"text": "Router reboot at 9pm"}, headers=csrf(client)
    )
    assert same.json()["version"] == 1  # unchanged text: same version

    member = make_user(owner.home_id, role="member")
    m = new_client()
    assert login(m, member).status_code == 200
    assert m.get("/api/v1/account").json()["motd"] == {
        "text": "Router reboot at 9pm",
        "version": 1,
    }
    assert m.get(ADMIN).status_code == 403
    assert m.put(ADMIN, json={"text": "hi"}, headers=csrf(m)).status_code == 403
    assert m.post(DISMISS, json={"version": 1}, headers=csrf(m)).json() == {
        "motd": None
    }
    assert m.get("/api/v1/account").json()["motd"] is None
    # A new message shows again; removing it shows nothing.
    client.put(ADMIN, json={"text": "New Wi-Fi password"}, headers=csrf(client))
    assert m.get("/api/v1/account").json()["motd"]["version"] == 2
    client.put(ADMIN, json={"text": "   "}, headers=csrf(client))
    assert m.get("/api/v1/account").json()["motd"] is None
    assert (
        client.put(ADMIN, json={"text": "x" * 2001}, headers=csrf(client)).status_code
        == 422
    )
    assert m.post(DISMISS, json={"version": "2"}, headers=csrf(m)).status_code == 422


def test_ui_motd(open_page, owner, make_user):
    page = open_page()
    _ui.ui_login(page, owner)
    _ui.go_settings(page, "admin")
    page.get_by_test_id("motd-input").fill("Line one\nLine two")
    page.get_by_test_id("motd-save").click()
    expect(page.get_by_test_id("status")).to_contain_text("Message saved")

    member = make_user(owner.home_id, role="member")
    other = open_page()
    _ui.ui_login(other, member)
    popup = other.get_by_test_id("motd")
    expect(popup).to_be_visible()
    expect(other.get_by_test_id("motd-text")).to_have_text("Line one\nLine two")
    other.get_by_test_id("motd-close").click()
    expect(popup).to_have_count(0)
    other.reload()  # closed only for that visit
    expect(other.get_by_test_id("motd")).to_be_visible()
    other.get_by_test_id("motd-dismiss").click()
    expect(other.get_by_test_id("motd")).to_have_count(0)
    other.reload()
    expect(other.get_by_test_id("app-shell")).to_be_visible()
    other.wait_for_timeout(500)
    expect(other.get_by_test_id("motd")).to_have_count(0)
