"""Air-filter reminders (a thermostat's installer settings): every so many
run hours or days since the last change. When due, the bell shows a notice
that cannot be dismissed until an operator or admin presses Changed Filter;
it is sent once to those who chose filter alerts. The time left shows in
the thermostat's Info."""

import json
from datetime import timedelta

from playwright.sync_api import expect

from app import alerts, filter_reminders, thermostat_settings
from app.integrations import cync_thermostat as t
from app.models import Device, FilterReminder
from tests import test_alerts as _alerts
from tests import test_package1 as _package1
from tests import test_thermostat as _thermostat
from tests import test_ui as _ui

outbox, secrets_key, pushed = _package1.outbox, _package1.secrets_key, _alerts.pushed


REPORT = t.thermostat_state(t.parse_probe_reply(_thermostat.FULL_REPLY))


def thermostat(db, owner, hours=None, name="Hallway"):
    device = Device(
        home_id=owner.home_id,
        integration="cync",
        external_id=f"77-{name}",
        type="thermostat",
        name=name,
        room="Lab",
        capabilities=json.dumps({"cloud_id": 1}),
        state=json.dumps({**REPORT, "filter_hours": hours}),
        online=True,
    )
    db.add(device)
    db.commit()
    return device


def url(owner, device, end=""):
    return f"/api/v1/homes/{owner.home_id}/devices/{device.id}/filter{end}"


def run_hours(db, device, hours):
    state = json.loads(device.state)
    device.state = json.dumps({**state, "filter_hours": hours})
    db.commit()


def test_days_reminder_notice_and_changed(
    client, new_client, db, owner, make_user, login, csrf, secrets_key, outbox, pushed
):
    hall = thermostat(db, owner)
    _alerts.ready(client, db, owner, login, csrf, ["filter"], push=False)
    assert client.get(url(owner, hall)).json()["mode"] == "off"
    r = client.put(
        url(owner, hall), json={"mode": "days", "every": 90}, headers=csrf(client)
    )
    assert r.status_code == 200, r.text
    assert r.json()["left"] == 90 and r.json()["due"] is False
    for bad in (
        {"mode": "days", "every": 3},
        {"mode": "hours", "every": 9000},
        {"mode": "week"},
    ):
        assert (
            client.put(url(owner, hall), json=bad, headers=csrf(client)).status_code
            == 422
        )
    feed = f"/api/v1/homes/{owner.home_id}/alerts/feed"
    assert client.get(feed).json()["items"] == []
    # 91 days on: due.
    row = db.get(FilterReminder, hall.id)
    row.changed_at = row.changed_at - timedelta(days=91)
    db.commit()
    shown = client.get(feed).json()
    assert shown["unseen"] == 1
    notice = shown["items"][0]
    assert notice["sticky"] is True and notice["kind"] == "filter"
    assert notice["title"] == "Hallway: change the air filter"
    assert client.get(url(owner, hall)).json()["due"] is True
    # Sent once by email; the bell keeps showing it (Dismiss All leaves it).
    assert alerts.check_home(db, owner.home_id, now=0) == 1
    assert "change the air filter" in outbox[-1][1]
    assert alerts.check_home(db, owner.home_id, now=60) == 0
    client.delete(feed, headers=csrf(client))
    assert client.get(feed).json()["items"][0]["sticky"] is True
    # Members cannot press Changed Filter; operators and admins can.
    member = make_user(owner.home_id, role="member")
    other = new_client()
    assert login(other, member).status_code == 200
    assert (
        other.post(url(owner, hall, "/changed"), headers=csrf(other)).status_code == 403
    )
    r = other.put(url(owner, hall), json={"mode": "off"}, headers=csrf(other))
    assert r.status_code == 403  # an installer setting
    r = client.post(url(owner, hall, "/changed"), headers=csrf(client))
    assert r.status_code == 200 and r.json()["left"] == 90
    assert client.get(feed).json() == {"unseen": 0, "items": []}
    # Off: no reminder, no notice.
    client.put(url(owner, hall), json={"mode": "off"}, headers=csrf(client))
    assert (
        client.post(url(owner, hall, "/changed"), headers=csrf(client)).status_code
        == 409
    )


def test_run_hours_count_from_the_change(client, db, owner, login, csrf):
    hall = thermostat(db, owner, hours=100)
    assert login(client, owner).status_code == 200
    r = client.put(
        url(owner, hall), json={"mode": "hours", "every": 500}, headers=csrf(client)
    )
    assert r.json()["left"] == 500
    run_hours(db, hall, 350)
    assert client.get(url(owner, hall)).json()["left"] == 250
    run_hours(db, hall, 650)
    shown = client.get(url(owner, hall)).json()
    assert shown["left"] == -50 and shown["due"] is True
    client.post(url(owner, hall, "/changed"), headers=csrf(client))
    run_hours(db, hall, 700)
    assert client.get(url(owner, hall)).json()["left"] == 450
    run_hours(db, hall, 20)  # the thermostat's own counter was reset
    assert client.get(url(owner, hall)).json()["left"] == 480
    run_hours(db, hall, None)  # not reported: unknown, not due
    shown = client.get(url(owner, hall)).json()
    assert shown["left"] is None and shown["due"] is False


def test_status_rounding():
    device = Device(state="{}")
    row = FilterReminder(mode="days", every=30, changed_at=filter_reminders.utcnow())
    assert filter_reminders.status(device, row)["left"] == 30
    later = filter_reminders.utcnow() + timedelta(days=29, hours=1)
    assert filter_reminders.status(device, row, later)["left"] == 1
    assert (
        filter_reminders.status(device, row, later + timedelta(days=2))["due"] is True
    )


def test_ui_settings_bell_and_info(open_page, db, owner, monkeypatch):
    hall = thermostat(db, owner, hours=40)
    from app import features

    features.set_integration(db, owner.home_id, "cync", True, None, None)

    def fake_read(db_, device, refresh=False):
        return {
            "settings": {k: None for k in thermostat_settings.SETTINGS},
            "missing": [],
            "editable": list(thermostat_settings.SETTINGS),
            "limits": {},
        }

    monkeypatch.setattr("app.routes.thermostat.read_settings", fake_read)
    page = open_page()
    _ui.ui_login(page, owner)
    _ui.card(page, "Hallway").get_by_test_id("thermo-settings-open").click()
    panel = page.get_by_test_id("thermo-settings-panel")
    expect(panel.get_by_test_id("thermo-filter-left")).to_have_count(0)  # off
    panel.get_by_test_id("thermo-group-filter").locator("summary").click()
    panel.get_by_test_id("thermo-filter-mode").select_option("hours")
    expect(panel.get_by_test_id("thermo-filter-every")).to_have_value("500")
    panel.get_by_test_id("thermo-filter-every").fill("300")
    panel.get_by_test_id("thermo-filter-save").click()
    expect(page.get_by_test_id("status")).to_contain_text("Filter reminder saved")
    expect(panel.get_by_test_id("thermo-filter-left")).to_contain_text(
        "300 run hours left"
    )
    expect(panel.get_by_test_id("thermo-group-filter")).to_have_attribute("open", "")
    panel.get_by_test_id("thermo-settings-close").click()
    # Due: the bell's notice, no X, with Changed Filter.
    run_hours(db, hall, 400)
    page.evaluate("window.alertBell.check(window.smartHomeApp.home.id)")
    expect(page.get_by_test_id("alert-bell-count")).to_have_text("1")
    page.get_by_test_id("alert-bell").click()
    notice = page.get_by_test_id("alert-bell-standing")
    expect(notice).to_contain_text("Hallway: change the air filter")
    expect(notice.get_by_test_id("alert-bell-dismiss")).to_have_count(0)
    expect(page.get_by_test_id("alert-bell-dismiss-all")).to_have_count(
        0
    )  # nothing else
    notice.get_by_test_id("alert-bell-filter-changed").click()
    expect(page.get_by_test_id("status")).to_contain_text("Filter change noted")
    expect(notice).to_have_count(0)
    expect(page.get_by_test_id("alert-bell-empty")).to_have_text("No notifications")
    db.expire_all()
    assert db.get(FilterReminder, hall.id).runtime_at_change == 400


def test_ui_members_see_the_notice_without_the_button(open_page, db, owner, make_user):
    hall = thermostat(db, owner, hours=0)
    db.add(
        FilterReminder(device_id=hall.id, mode="hours", every=50, runtime_at_change=0)
    )
    db.commit()
    run_hours(db, hall, 60)
    member = make_user(owner.home_id, role="member")
    page = open_page()
    _ui.ui_login(page, member)
    page.get_by_test_id("alert-bell").click()
    notice = page.get_by_test_id("alert-bell-standing")
    expect(notice).to_contain_text("change the air filter")
    expect(notice.get_by_test_id("alert-bell-filter-changed")).to_have_count(0)
