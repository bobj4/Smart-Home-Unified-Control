"""A Cync thermostat's own heating and cooling record (its energy reports,
kept in Cync's cloud) for the History window, and the fall back to the
app's readings when Cync does not give it."""

import asyncio
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta

from app import thermostat_runs
from app.cync_home import CyncUnavailable
from app.integrations import cync, cync_runtime
from app.models import Device, utcnow
from app.routes import thermostat as thermostat_routes

T0 = datetime(2026, 11, 6, 22, 0, tzinfo=UTC)


def run(coro):
    """On a thread of its own: the browser tests leave a loop running here."""
    with ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(asyncio.run, coro).result()


def report(status_byte: int) -> str:
    return bytes([26, 11, 6, 22, 0, status_byte]).hex()


def item(minutes: int, status_byte: int) -> dict:
    at = T0 + timedelta(minutes=minutes)
    return {
        "_id": "x",
        "snapshot_date": at.strftime("%Y-%m-%d_%H_%M_%S"),
        "86": report(status_byte),
    }


def test_report_values():
    assert cync_runtime.report_status(report(0)) == "idle"
    assert cync_runtime.report_status(report(1)) == "heating"
    assert cync_runtime.report_status(report(2)) == "cooling"
    assert cync_runtime.report_status([26, 11, 6, 22, 0, 2]) == "cooling"
    assert cync_runtime.report_status(report(3)) is None
    assert cync_runtime.report_status("000b06120a01") is None  # no year
    assert cync_runtime.report_status("1a0d06120a01") is None  # month 13
    assert cync_runtime.report_status("zz") is None
    assert cync_runtime.report_status(None) is None
    assert cync_runtime.snapshot_time("2026-11-06_22_05_09") == T0.replace(
        minute=5, second=9
    )
    assert cync_runtime.snapshot_time("06/11/2026") is None


def test_runs_last_until_the_next_report():
    reports = cync_runtime.events(
        [item(30, 0), item(0, 1), item(10, 0), item(20, 2), {"86": "zz"}, "junk"]
    )
    assert [s for _, s in reports] == ["heating", "idle", "cooling", "idle"]
    found = cync_runtime.runs(
        reports, T0 + timedelta(minutes=5), T0 + timedelta(hours=1)
    )
    assert [(round((b - a).total_seconds() / 60), s) for a, b, s in found] == [
        (5, "heating"),  # clipped to the window's start
        (10, "cooling"),
    ]
    # Still running: the run lasts until the end of the window.
    still = cync_runtime.events([item(0, 1)])
    [(start, stop, status)] = cync_runtime.runs(still, T0, T0 + timedelta(minutes=45))
    assert status == "heating" and stop - start == timedelta(minutes=45)


class FakeAuth:
    def __init__(self, pages):
        self.pages = pages
        self.calls = []

    async def _send_user_request(self, url, method="GET", json=None):
        self.calls.append((url, method, json))
        return self.pages[len(self.calls) - 1]


class FakeDevice:
    device_id = 4321
    product_id = "1607abcd"


class FakeApi:
    def __init__(self, pages):
        self._auth = FakeAuth(pages)

    def get_devices(self):
        return [FakeDevice()]


def test_fetch_asks_like_the_cync_app_and_pages():
    first = [item(i, 1 if i % 2 else 0) for i in range(cync_runtime.PAGE)]
    api = FakeApi(
        [{"count": 101, "list": first}, {"count": 101, "list": [item(200, 2)]}]
    )
    begin, end = T0, T0 + timedelta(days=1)
    found = run(cync_runtime._fetch(api, 4321, begin, end))
    assert len(found) == 101 and found[-1][1] == "cooling"
    (url, method, body), second = api._auth.calls
    assert (
        url.endswith("/v2/product/1607abcd/device/4321/snapshot") and method == "POST"
    )
    assert body == {
        "rule_id": "61d3e8eaefe8266240c306ee",
        "datapoint": [86],
        "offset": 0,
        "limit": 100,
        "date": {
            "begin": int(begin.timestamp() * 1000),
            "end": int(end.timestamp() * 1000),
        },
    }
    assert second[2]["offset"] == 100


def test_fetch_stops_on_a_short_page_and_needs_the_thermostat():
    api = FakeApi([{"count": 5, "list": [item(0, 1)]}, {"list": []}])
    run(cync_runtime._fetch(api, 4321, T0, T0 + timedelta(hours=1)))
    assert len(api._auth.calls) == 1
    try:
        run(cync_runtime._fetch(api, 999, T0, T0))
    except LookupError:
        pass
    else:
        raise AssertionError("an unknown thermostat must not be asked about")


def test_cloud_runs_cached_and_none_when_cync_cannot(
    db, owner, make_device, monkeypatch
):
    hall = db.get(
        Device, make_device(owner.home_id, device_type="thermostat", name="Hall")
    )
    thermostat_runs._cache.clear()
    asked = []

    def reports(api, loop, cloud_id, begin, end):
        asked.append((begin, end))
        return [
            (end - timedelta(minutes=30), "heating"),
            (end - timedelta(minutes=10), "idle"),
        ]

    monkeypatch.setattr(
        thermostat_runs, "_connection", lambda db, d: ("api", "loop", 7)
    )
    monkeypatch.setattr(cync_runtime, "reports_on_open", reports)
    [(start, stop, status)] = thermostat_runs.cloud_runs(db, hall, 1)
    assert status == "heating" and stop - start == timedelta(minutes=20)
    # A run that began before the window still counts: a day earlier is asked.
    assert asked[0][1] - asked[0][0] == timedelta(days=2)
    thermostat_runs.cloud_runs(db, hall, 1)
    assert len(asked) == 1  # kept a few minutes

    def unavailable(db, d):
        raise CyncUnavailable(503, "Cync is still connecting")

    monkeypatch.setattr(thermostat_runs, "_connection", unavailable)
    assert thermostat_runs.cloud_runs(db, hall, 7) is None

    def refused(*args):
        raise cync.CyncError("could not reach Cync")

    monkeypatch.setattr(thermostat_runs, "_connection", lambda db, d: ("a", "l", 7))
    monkeypatch.setattr(cync_runtime, "reports_on_open", refused)
    assert thermostat_runs.cloud_runs(db, hall, 30) is None


def test_history_uses_the_thermostats_runs(
    client, db, owner, login, make_device, monkeypatch
):
    hall_id = make_device(owner.home_id, device_type="thermostat", name="Hall")
    midnight = datetime.combine(utcnow().date(), datetime.min.time(), UTC)
    runs = [
        (midnight - timedelta(minutes=30), midnight + timedelta(minutes=15), "heating"),
        (
            midnight + timedelta(hours=1),
            midnight + timedelta(hours=1, minutes=6),
            "cooling",
        ),
    ]
    monkeypatch.setattr(thermostat_routes, "cloud_runs", lambda db, device, days: runs)
    assert login(client, owner).status_code == 200
    url = f"/api/v1/homes/{owner.home_id}/devices/{hall_id}/history?days=7"
    data = client.get(url).json()
    assert data["run_source"] == "thermostat" and len(data["runs"]) == 2
    by_day = {d["date"]: d for d in data["run_hours"]}
    before, today = (
        (midnight - timedelta(days=1)).date().isoformat(),
        midnight.date().isoformat(),
    )
    # The run across midnight is split between the two days.
    assert round(by_day[before]["heating"] * 60) == 30
    assert round(by_day[today]["heating"] * 60) == 15
    assert round(by_day[today]["cooling"] * 60) == 6

    monkeypatch.setattr(thermostat_routes, "cloud_runs", lambda db, device, days: None)
    data = client.get(url).json()
    assert data["run_source"] == "readings" and data["runs"] == []


def test_nothing_to_show(client, db, owner, login, make_device, monkeypatch):
    """No readings and no reports: an empty History, not an error."""
    assert cync_runtime.runs([], T0, T0 + timedelta(hours=1)) == []
    hall_id = make_device(owner.home_id, device_type="thermostat", name="Hall")
    monkeypatch.setattr(thermostat_routes, "cloud_runs", lambda db, device, days: None)
    assert login(client, owner).status_code == 200
    url = f"/api/v1/homes/{owner.home_id}/devices/{hall_id}/history"
    data = client.get(url).json()
    assert data["points"] == [] and data["run_hours"] == [] and data["since"] is None
