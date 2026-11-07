"""A Cync thermostat's own heating and cooling record, from Cync's cloud.

The thermostat sends an energy report (data point 86) each time it starts
heating, starts cooling or stops; Cync's cloud keeps them. The Cync app
(6.20, ThermostatHistoryManager) asks for them with a "snapshot" request:

    POST {api}/v2/product/{product id}/device/{device id}/snapshot
    {"rule_id": RULE_ID, "datapoint": [86], "offset": page * 100,
     "limit": 100, "date": {"begin": ms, "end": ms}}

and gets {"count": n, "list": [{"86": "<hex>", "snapshot_date":
"yyyy-MM-dd_HH_mm_ss" (UTC), ...}]}. A report is six bytes: year, month,
day, hour, minute, then 0 = stopped, 1 = heating, 2 = cooling. Like the app,
a run is timed by the cloud's snapshot_date and lasts until the next report;
the report's own date bytes only tell a real report from an empty one.
"""

import asyncio
from collections.abc import Iterable
from datetime import UTC, datetime
from typing import Any

from pycync.const import REST_API_BASE_URL

from app.integrations.cync import _mapped

ENERGY_REPORT = 86
RULE_ID = "61d3e8eaefe8266240c306ee"  # fixed in the Cync app's SnapshotRequest
PAGE = 100
MAX_PAGES = 50  # 5,000 reports: far more than a month of runs
FETCH_SECONDS = 20  # the History window waits for this
STATUSES = {0: "idle", 1: "heating", 2: "cooling"}


def report_status(value: Any) -> str | None:
    """'idle', 'heating' or 'cooling' from a report's value (hex text, or a
    list of byte values); None for anything else."""
    if isinstance(value, str):
        try:
            raw = bytes.fromhex(value)
        except ValueError:
            return None
    elif isinstance(value, list) and all(
        isinstance(b, int) and not isinstance(b, bool) for b in value
    ):
        raw = bytes(b & 0xFF for b in value)
    else:
        return None
    if len(raw) < 6 or raw[0] == 0 or not 1 <= raw[1] <= 12:
        return None
    return STATUSES.get(raw[5])


def snapshot_time(text: Any) -> datetime | None:
    try:
        return datetime.strptime(str(text), "%Y-%m-%d_%H_%M_%S").replace(tzinfo=UTC)
    except ValueError:
        return None


def events(items: Iterable[Any]) -> list[tuple[datetime, str]]:
    """(time, status) for each usable report, oldest first."""
    found = []
    for item in items:
        if not isinstance(item, dict):
            continue
        at = snapshot_time(item.get("snapshot_date"))
        status = report_status(item.get(str(ENERGY_REPORT)))
        if at is not None and status is not None:
            found.append((at, status))
    return sorted(found)


def runs(
    reports: list[tuple[datetime, str]], begin: datetime, end: datetime
) -> list[tuple[datetime, datetime, str]]:
    """Heating and cooling runs within [begin, end]: each report lasts until
    the next one (the last until `end`)."""
    found = []
    for (at, status), following in zip(
        reports, [*reports[1:], None][: len(reports)], strict=True
    ):
        if status == "idle":
            continue
        start, stop = max(at, begin), min(following[0] if following else end, end)
        if stop > start:
            found.append((start, stop, status))
    return found


def _product_id(api: Any, cloud_id: int) -> str:
    for device in api.get_devices():
        if int(getattr(device, "device_id", -1) or -1) == cloud_id:
            product = getattr(device, "product_id", None)
            if product:
                return str(product)
    raise LookupError("the thermostat is not on this Cync account")


async def _fetch(
    api: Any, cloud_id: int, begin: datetime, end: datetime
) -> list[tuple[datetime, str]]:
    url = (
        f"{REST_API_BASE_URL}/v2/product/{_product_id(api, cloud_id)}"
        f"/device/{cloud_id}/snapshot"
    )
    span = {"begin": int(begin.timestamp() * 1000), "end": int(end.timestamp() * 1000)}
    items: list[Any] = []
    for page in range(MAX_PAGES):
        body = {
            "rule_id": RULE_ID,
            "datapoint": [ENERGY_REPORT],
            "offset": page * PAGE,
            "limit": PAGE,
            "date": span,
        }
        answer = await api._auth._send_user_request(url, "POST", json=body)  # noqa: SLF001
        listed = answer.get("list") if isinstance(answer, dict) else None
        if not isinstance(listed, list):
            break
        items += listed
        count = answer.get("count")
        if len(listed) < PAGE or (isinstance(count, int) and len(items) >= count):
            break
    return events(items)


def reports_on_open(
    api: Any, loop: Any, cloud_id: int, begin: datetime, end: datetime
) -> list[tuple[datetime, str]]:
    """The thermostat's reports between begin and end, over a home's open
    connection (its login and its event loop)."""

    async def limited() -> list[tuple[datetime, str]]:
        return await asyncio.wait_for(_fetch(api, cloud_id, begin, end), FETCH_SECONDS)

    result: list[tuple[datetime, str]] = _mapped(
        lambda: asyncio.run_coroutine_threadsafe(limited(), loop).result()
    )
    return result
