"""Air-filter reminders, the Cync thermostat's own (its installer settings):
every so many run hours or months since its filter count was reset. Read
from and written to the thermostat (Event_Filter_Replacement_En and
Filter_Replacement_Method, Cync app 6.20); Changed Filter resets its count
(Filter_Replacement_Reset). When due, the bell shows a notice that cannot
be dismissed until an operator or admin presses Changed Filter; it is sent
once to those who chose filter alerts. The time left shows in the
thermostat's Info. Nothing talks to Cync."""

import json
from datetime import UTC, datetime, timedelta

import pytest
from playwright.sync_api import expect

from app import (
    alerts,
    cync_live,
    features,
    filter_reminders,
    thermostat_filter,
    thermostat_settings,
)
from app.integrations import cync
from app.integrations import cync_thermostat as t
from app.models import Device, FilterReminder
from tests import test_alerts as _alerts
from tests import test_package1 as _package1
from tests import test_thermostat as _thermostat
from tests import test_ui as _ui

outbox, secrets_key, pushed = _package1.outbox, _package1.secrets_key, _alerts.pushed

REPORT = t.thermostat_state(t.parse_probe_reply(_thermostat.FULL_REPLY))
TODAY = datetime.now(UTC).date().isoformat()


def thermostat(db, owner, hours=None, reset=None, name="Hallway", cync_id=1):
    """A thermostat; its filter report: run hours and reset day (None: none)."""
    device = Device(
        home_id=owner.home_id,
        integration="cync",
        external_id=f"77-{name}",
        type="thermostat",
        name=name,
        room="Lab",
        capabilities=json.dumps({"cloud_id": cync_id} if cync_id else {}),
        state=json.dumps({**REPORT, "filter_hours": hours, "filter_reset": reset}),
        online=True,
    )
    db.add(device)
    db.commit()
    return device


def url(owner, device, end=""):
    return f"/api/v1/homes/{owner.home_id}/devices/{device.id}/filter{end}"


def report(db, device, hours, reset=None):
    state = json.loads(device.state)
    state.update(filter_hours=hours)
    if reset is not None:
        state.update(filter_reset=reset)
    device.state = json.dumps(state)
    db.commit()


@pytest.fixture
def held(monkeypatch):
    """The thermostat's filter settings: answers reads, keeps writes (unless
    told not to), and resets its count when asked."""
    state = {
        "keep": True,
        "reachable": True,
        "writes": [],
        "resets": 0,
        "values": {
            "Event_Filter_Replacement_En": 1,
            "Filter_Replacement_Method": [0, 0, 3],  # months, 3
        },
    }
    names = {54: "Event_Filter_Replacement_En", 61: "Filter_Replacement_Method"}

    def read(api, loop, cloud_id, wanted):
        if not state["reachable"]:
            raise cync.CyncError("no answer")
        return {n: state["values"][n] for n in wanted if n in state["values"]}

    def write(api, loop, cloud_id, entries, wanted):
        state["writes"].append(entries)
        if state["keep"]:
            for index, value in entries:
                stored = list(value) if isinstance(value, bytes) else int(value)
                state["values"][names[index]] = stored
        return read(api, loop, cloud_id, wanted)

    def write_points(api, loop, cloud_id, entries):
        if not state["reachable"]:
            raise cync.CyncError("no answer")
        assert entries == [(88, False)]  # as the Cync app resets it
        state["resets"] += 1
        points = dict(t.parse_probe_reply(_thermostat.REPLY))
        points[t.FILTER] = json.dumps({"ResetData": f"{TODAY}T09:30:00", "Runtime": 0})
        return points

    def connection(db, device):
        return "api", "loop", 1

    monkeypatch.setattr(thermostat_filter, "_connection", connection)
    monkeypatch.setattr(thermostat_settings, "_connection", connection)
    monkeypatch.setattr(cync, "thermostat_settings_on_open", read)
    monkeypatch.setattr(cync, "thermostat_write_settings_on_open", write)
    monkeypatch.setattr(cync, "thermostat_write_on_open", write_points)
    thermostat_settings._cache.clear()
    thermostat_filter._synced.clear()
    return state


def test_method_bytes_as_the_cync_app_has_them():
    decode, encode = thermostat_filter.decode_method, thermostat_filter.encode_method
    assert decode([0, 0, 3]) == ("months", 3)
    assert decode([1, 1, 244]) == ("hours", 500)
    assert decode("0105dc") == ("hours", 1500)  # hex text works too
    assert decode([2, 0, 1]) is None and decode([0]) is None and decode(None) is None
    assert encode("months", 12) == bytes([0, 0, 12])
    assert encode("hours", 1000) == bytes([1, 3, 232])
    assert t.entry(61, encode("hours", 100)) == bytes([61, 0xA0, 3, 1, 0, 100])


def test_settings_read_follows_the_thermostat(client, db, owner, login, held):
    hall = thermostat(db, owner, hours=984, reset="2026-06-17")
    features.set_integration(db, owner.home_id, "cync", True, None, None)
    assert login(client, owner).status_code == 200
    settings = f"/api/v1/homes/{owner.home_id}/devices/{hall.id}/settings"
    r = client.get(settings)
    assert r.status_code == 200, r.text
    shown = r.json()["filter"]
    # Every 3 months from its reset on 17 June: due on 17 September.
    assert (shown["mode"], shown["every"]) == ("months", 3)
    assert shown["due_at"].startswith("2026-09-17") and shown["due"] is True
    # Turned off in the Cync app: followed on the next read.
    held["values"]["Event_Filter_Replacement_En"] = False
    client.get(settings + "?refresh=true")
    assert client.get(url(owner, hall)).json()["mode"] == "off"


def test_write_reset_and_notice(
    client,
    new_client,
    db,
    owner,
    make_user,
    login,
    csrf,
    secrets_key,
    outbox,
    pushed,
    held,
):
    hall = thermostat(db, owner, hours=984, reset="2026-06-17")
    _alerts.ready(client, db, owner, login, csrf, ["filter"], push=False)
    assert client.get(url(owner, hall)).json()["mode"] == "off"
    r = client.put(
        url(owner, hall), json={"mode": "hours", "every": 1000}, headers=csrf(client)
    )
    assert r.status_code == 200, r.text
    assert held["writes"][-1] == [(54, True), (61, bytes([1, 3, 232]))]
    assert r.json()["left"] == 16  # 1000 less the thermostat's 984
    for bad in (
        {"mode": "hours", "every": 1050},  # hundreds only
        {"mode": "hours", "every": 2000},
        {"mode": "months", "every": 13},
        {"mode": "days", "every": 90},
    ):
        r = client.put(url(owner, hall), json=bad, headers=csrf(client))
        assert r.status_code == 422, bad
    held["keep"] = False  # the thermostat does not take it
    r = client.put(url(owner, hall), json={"mode": "months"}, headers=csrf(client))
    assert r.status_code == 502
    assert client.get(url(owner, hall)).json()["mode"] == "hours"
    held["keep"] = True
    feed = f"/api/v1/homes/{owner.home_id}/alerts/feed"
    assert client.get(feed).json()["items"] == []
    # 20 more run hours: due.
    report(db, hall, 1004)
    shown = client.get(feed).json()
    assert shown["unseen"] == 1
    notice = shown["items"][0]
    assert notice["sticky"] is True and notice["kind"] == "filter"
    assert notice["title"] == "Hallway: change the air filter"
    assert notice["body"] == "Due after 1000 run hours."
    # Sent once by email; the bell keeps showing it (Dismiss All leaves it).
    assert alerts.check_home(db, owner.home_id, now=0) == 1
    assert "change the air filter" in outbox[-1][1]
    assert alerts.check_home(db, owner.home_id, now=60) == 0
    client.delete(feed, headers=csrf(client))
    assert client.get(feed).json()["items"][0]["sticky"] is True
    # Members cannot press Changed Filter or change the setting.
    member = make_user(owner.home_id, role="member")
    other = new_client()
    assert login(other, member).status_code == 200
    changed = url(owner, hall, "/changed")
    assert other.post(changed, headers=csrf(other)).status_code == 403
    r = other.put(url(owner, hall), json={"mode": "off"}, headers=csrf(other))
    assert r.status_code == 403  # an installer setting
    # Changed Filter resets the thermostat's own count.
    r = client.post(changed, headers=csrf(client))
    assert r.status_code == 200, r.text
    assert r.json()["thermostat_reset"] is True and held["resets"] == 1
    assert r.json()["left"] == 1000
    db.refresh(hall)
    assert json.loads(hall.state)["filter_reset"] == TODAY
    assert client.get(feed).json() == {"unseen": 0, "items": []}
    # Off: written to the thermostat; no reminder, no notice.
    client.put(url(owner, hall), json={"mode": "off"}, headers=csrf(client))
    assert held["writes"][-1] == [(54, False)]
    assert client.post(changed, headers=csrf(client)).status_code == 409


def test_changed_while_the_thermostat_is_unreachable(
    client, db, owner, login, csrf, held
):
    hall = thermostat(db, owner, hours=984, reset="2026-06-17")
    assert login(client, owner).status_code == 200
    body = {"mode": "hours", "every": 500}
    client.put(url(owner, hall), json=body, headers=csrf(client))
    assert client.get(url(owner, hall)).json()["due"] is True
    held["reachable"] = False
    r = client.post(url(owner, hall, "/changed"), headers=csrf(client))
    assert r.json()["thermostat_reset"] is False
    # Counted here from the press until the thermostat is reset again.
    assert r.json()["left"] == 500
    report(db, hall, 1084)
    assert client.get(url(owner, hall)).json()["left"] == 400
    # Reset in the Cync app later: its count again.
    later = (datetime.now(UTC) + timedelta(days=1)).date().isoformat()
    report(db, hall, 30, reset=later)
    assert client.get(url(owner, hall)).json()["left"] == 470


def test_months_count_from_the_reset_day():
    device = Device(state=json.dumps({"filter_reset": "2026-01-31", "filter_hours": 5}))
    row = FilterReminder(
        mode="months", every=1, changed_at=datetime(2026, 1, 31, tzinfo=UTC)
    )
    on = datetime(2026, 2, 20, tzinfo=UTC)
    shown = filter_reminders.status(device, row, on)
    assert shown["due_at"].startswith("2026-02-28") and shown["left"] == 8
    assert filter_reminders.status(device, row, on + timedelta(days=9))["due"] is True
    add = filter_reminders.add_months
    nov, dec = datetime(2026, 11, 15, tzinfo=UTC), datetime(2026, 12, 1, tzinfo=UTC)
    assert add(nov, 3) == datetime(2027, 2, 15, tzinfo=UTC)
    assert add(dec, 12) == datetime(2027, 12, 1, tzinfo=UTC)


def test_alerts_check_follows_the_cync_app(db, owner, held, monkeypatch):
    hall = thermostat(db, owner, hours=984, reset="2026-06-17")
    monkeypatch.setattr(cync_live, "connection", lambda home_id: ("api", "loop"))
    thermostat_filter.sync(db, owner.home_id, now=0)
    assert filter_reminders.for_device(db, hall)["mode"] == "months"
    # Changed in the Cync app: read again only after a while.
    held["values"]["Filter_Replacement_Method"] = [1, 1, 244]
    thermostat_filter.sync(db, owner.home_id, now=60)
    assert filter_reminders.for_device(db, hall)["mode"] == "months"
    thermostat_filter.sync(db, owner.home_id, now=thermostat_filter.SYNC_SECONDS + 1)
    shown = filter_reminders.for_device(db, hall)
    assert (shown["mode"], shown["every"], shown["left"]) == ("hours", 500, -484)
    # Not connected: nothing is asked.
    monkeypatch.setattr(cync_live, "connection", lambda home_id: None)
    held["reachable"] = False
    thermostat_filter.sync(db, owner.home_id, now=10**9)


def test_sent_again_after_a_reset_elsewhere(db, owner):
    hall = thermostat(db, owner, hours=600, reset="2026-06-17")
    db.add(
        FilterReminder(
            device_id=hall.id,
            mode="hours",
            every=500,
            notified=True,
            changed_at=datetime(2026, 6, 17, tzinfo=UTC),
        )
    )
    db.commit()
    assert len(filter_reminders.due(db, owner.home_id)) == 1
    report(db, hall, 10, reset=TODAY)  # reset in the Cync app
    assert filter_reminders.due(db, owner.home_id) == []
    assert db.get(FilterReminder, hall.id).notified is False


def test_ui_settings_bell_and_info(open_page, db, owner, monkeypatch, held):
    hall = thermostat(db, owner, hours=40, reset=TODAY)
    features.set_integration(db, owner.home_id, "cync", True, None, None)
    held["values"]["Event_Filter_Replacement_En"] = 0  # off on the thermostat

    def fake_read(db_, device, refresh=False):
        thermostat_filter.store(db_, device, held["values"])
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
    mode = panel.get_by_test_id("thermo-filter-mode")
    expect(mode.locator("option")).to_have_text(
        ["Off", "After run hours", "After months"]
    )
    every = panel.get_by_test_id("thermo-filter-every")
    mode.select_option("months")
    expect(every).to_have_value("3")
    expect(every).to_have_attribute("max", "12")
    mode.select_option("hours")
    expect(every).to_have_value("500")
    expect(every).to_have_attribute("step", "100")
    every.fill("300")
    panel.get_by_test_id("thermo-filter-save").click()
    expect(page.get_by_test_id("status")).to_contain_text("Filter reminder saved")
    assert held["writes"][-1] == [(54, True), (61, bytes([1, 1, 44]))]
    expect(panel.get_by_test_id("thermo-filter-left")).to_contain_text(
        "260 run hours left"
    )
    expect(panel.get_by_test_id("thermo-group-filter")).to_have_attribute("open", "")
    panel.get_by_test_id("thermo-settings-close").click()
    # Due: the bell's notice, no X, with Changed Filter.
    report(db, hall, 400)
    page.evaluate("window.alertBell.check(window.smartHomeApp.home.id)")
    expect(page.get_by_test_id("alert-bell-count")).to_have_text("1")
    page.get_by_test_id("alert-bell").click()
    notice = page.get_by_test_id("alert-bell-standing")
    expect(notice).to_contain_text("Hallway: change the air filter")
    expect(notice.get_by_test_id("alert-bell-dismiss")).to_have_count(0)
    expect(page.get_by_test_id("alert-bell-dismiss-all")).to_have_count(0)
    notice.get_by_test_id("alert-bell-filter-changed").click()
    expect(page.get_by_test_id("status")).to_have_text("Filter change noted.")
    expect(notice).to_have_count(0)
    empty = page.get_by_test_id("alert-bell-empty")
    expect(empty).to_have_text("No notifications")
    expect(empty).to_have_css("text-align", "center")
    assert held["resets"] == 1


def test_ui_info_shows_months_left(open_page, db, owner, monkeypatch, held):
    thermostat(db, owner, hours=40, reset=TODAY)
    features.set_integration(db, owner.home_id, "cync", True, None, None)

    def fake_read(db_, device, refresh=False):
        thermostat_filter.store(db_, device, held["values"])  # 3 months
        return {"settings": {}, "missing": [], "editable": [], "limits": {}}

    monkeypatch.setattr("app.routes.thermostat.read_settings", fake_read)
    page = open_page()
    _ui.ui_login(page, owner)
    _ui.card(page, "Hallway").get_by_test_id("thermo-settings-open").click()
    expect(page.get_by_test_id("thermo-filter-left")).to_contain_text("days left (due ")


def test_ui_members_see_the_notice_without_the_button(open_page, db, owner, make_user):
    hall = thermostat(db, owner, hours=0, cync_id=None)
    db.add(
        FilterReminder(device_id=hall.id, mode="hours", every=100, runtime_at_change=0)
    )
    db.commit()
    report(db, hall, 160)
    member = make_user(owner.home_id, role="member")
    page = open_page()
    _ui.ui_login(page, member)
    page.get_by_test_id("alert-bell").click()
    notice = page.get_by_test_id("alert-bell-standing")
    expect(notice).to_contain_text("change the air filter")
    expect(notice.get_by_test_id("alert-bell-filter-changed")).to_have_count(0)


def test_odd_answers_change_nothing(db, owner):
    hall = thermostat(db, owner, hours=10, reset=TODAY)
    store = thermostat_filter.store
    store(db, hall, {"Event_Filter_Replacement_En": 1})  # no method: nothing
    store(
        db,
        hall,
        {"Event_Filter_Replacement_En": 1, "Filter_Replacement_Method": [0, 0, 0]},
    )
    assert db.get(FilterReminder, hall.id) is None
    store(
        db,
        hall,
        {"Event_Filter_Replacement_En": 1, "Filter_Replacement_Method": [0, 0, 6]},
    )
    store(
        db,
        hall,
        {"Event_Filter_Replacement_En": 1, "Filter_Replacement_Method": [1, 0, 7]},
    )
    shown = filter_reminders.for_device(db, hall)
    assert (shown["mode"], shown["every"]) == ("months", 6)
