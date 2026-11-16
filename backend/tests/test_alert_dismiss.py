"""Dismissing alerts from the bell: an X on a computer, a swipe on a phone.
Each person's own list: the others still see the alert."""

from playwright.sync_api import expect

from app import alerts
from app.models import AlertDismissed, AlertItem
from tests import test_ui as _ui


def two_alerts(db, owner):
    alerts.remember(db, owner.home_id, "offline", "Hall is offline", "Not answering.")
    alerts.remember(db, owner.home_id, "camera", "Person at cam202", "Seen at 6:34.")
    return [i.id for i in db.query(AlertItem).order_by(AlertItem.id)]


def test_dismissing_is_per_person(
    client, new_client, db, owner, make_user, login, csrf, monkeypatch
):
    first, second = two_alerts(db, owner)
    other = make_user(owner.home_id, role="operator")
    them = new_client()
    assert login(client, owner).status_code == 200
    assert login(them, other).status_code == 200
    feed = f"/api/v1/homes/{owner.home_id}/alerts/feed"
    assert client.get(feed).json()["unseen"] == 2
    r = client.delete(f"{feed}/{second}", headers=csrf(client))
    assert r.status_code == 200, r.text
    mine = r.json()
    assert [i["id"] for i in mine["items"]] == [first] and mine["unseen"] == 1
    assert client.delete(f"{feed}/{second}", headers=csrf(client)).status_code == 200
    assert len(them.get(feed).json()["items"]) == 2  # theirs is untouched
    assert client.delete(f"{feed}/999999", headers=csrf(client)).status_code == 404
    r = client.delete(feed, headers=csrf(client))  # Dismiss All
    assert r.status_code == 200 and r.json() == {"unseen": 0, "items": []}
    assert len(them.get(feed).json()["items"]) == 2
    assert client.delete(feed).status_code == 403  # needs CSRF
    assert client.delete(f"{feed}/{first}").status_code == 403  # needs CSRF
    # An alert dropped from the home (only the newest are kept) goes too.
    monkeypatch.setattr(alerts, "KEEP_ALERTS", 1)
    alerts.remember(db, owner.home_id, "offline", "Den is offline", "Not answering.")
    assert db.query(AlertDismissed).count() == 0


def test_ui_x_dismisses_on_a_computer(open_page, db, owner):
    two_alerts(db, owner)
    page = open_page()
    _ui.ui_login(page, owner)
    page.get_by_test_id("alert-bell").click()
    items = page.get_by_test_id("alert-bell-item")
    expect(items).to_have_count(2)
    x = items.first.get_by_test_id("alert-bell-dismiss")
    expect(x).to_be_visible()
    box, row = x.bounding_box(), items.first.bounding_box()
    assert box["x"] + box["width"] > row["x"] + row["width"] - 4  # top right
    assert box["y"] < row["y"] + 16
    x.click()
    expect(items).to_have_count(1)
    expect(page.get_by_test_id("alert-bell-menu")).to_be_visible()  # stays open
    expect(items.first).to_contain_text("Hall is offline")
    items.first.get_by_test_id("alert-bell-dismiss").click()
    expect(page.get_by_test_id("alert-bell-empty")).to_be_visible()
    expect(page.get_by_test_id("alert-bell-dismiss-all")).to_have_count(0)
    assert db.query(AlertDismissed).count() == 2


def test_ui_dismiss_all_at_the_bottom(open_page, db, owner):
    two_alerts(db, owner)
    page = open_page()
    _ui.ui_login(page, owner)
    page.get_by_test_id("alert-bell").click()
    items = page.get_by_test_id("alert-bell-item")
    expect(items).to_have_count(2)
    button = page.get_by_test_id("alert-bell-dismiss-all")
    expect(button).to_have_text("Dismiss All")
    assert button.bounding_box()["y"] > items.last.bounding_box()["y"]  # below them
    button.click()
    expect(items).to_have_count(0)
    expect(page.get_by_test_id("alert-bell-empty")).to_be_visible()
    expect(button).to_have_count(0)
    assert db.query(AlertDismissed).count() == 2
    # A new alert still shows.
    alerts.remember(db, owner.home_id, "offline", "Den is offline", "Not answering.")
    page.evaluate("window.alertBell.check(window.smartHomeApp.home.id)")
    expect(page.get_by_test_id("alert-bell-count")).to_have_text("1")


def test_ui_swipe_dismisses_on_a_phone(browser, live_server, db, owner):
    two_alerts(db, owner)
    context = browser.new_context(
        base_url=live_server,
        viewport={"width": 412, "height": 900},
        is_mobile=True,
        has_touch=True,
    )
    context.set_default_timeout(5000)
    page = context.new_page()
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.goto("/")
    try:
        _ui.ui_login(page, owner)
        page.get_by_test_id("alert-bell").tap()
        items = page.get_by_test_id("alert-bell-item")
        expect(items).to_have_count(2)
        expect(items.first.get_by_test_id("alert-bell-dismiss")).to_be_hidden()
        expect(page.locator(".bell-hint")).to_be_visible()

        def swipe(row, distance):
            row.evaluate(
                """(n, d) => {
                  const box = n.getBoundingClientRect();
                  const at = (x) => ({ pointerId: 7, pointerType: 'touch', bubbles: true,
                    clientX: x, clientY: box.top + 10 });
                  const x0 = box.left + box.width / 2;
                  n.dispatchEvent(new PointerEvent('pointerdown', at(x0)));
                  n.dispatchEvent(new PointerEvent('pointermove', at(x0 + d / 2)));
                  n.dispatchEvent(new PointerEvent('pointermove', at(x0 + d)));
                  n.dispatchEvent(new PointerEvent('pointerup', at(x0 + d)));
                }""",
                distance,
            )

        swipe(items.first, 30)  # too short: springs back
        expect(items).to_have_count(2)
        swipe(items.first, -150)
        expect(items).to_have_count(1)
        expect(items.first).to_contain_text("Hall is offline")
        swipe(items.first, 150)
        expect(page.get_by_test_id("alert-bell-empty")).to_be_visible()
        assert db.query(AlertDismissed).count() == 2
        assert errors == []
    finally:
        context.close()
