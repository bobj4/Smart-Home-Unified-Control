"""Heating and cooling runs from a Cync thermostat's own reports (kept in
Cync's cloud, see app.integrations.cync_runtime), for its History window.

They are fetched over the home's open Cync connection and kept a few
minutes. Anything that stops them (Cync not connected, a demo thermostat,
Cync not answering) gives None, and History falls back to the runs worked
out from the app's own readings.
"""

import logging
import time
from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from app.cync_home import CyncUnavailable
from app.integrations import cync, cync_runtime
from app.models import Device, utcnow
from app.thermostat_schedule import _connection

CACHE_SECONDS = 300
RETRY_SECONDS = 60  # after a failure, readings are used this long
LEAD = timedelta(days=1)  # a run that began before the window still counts

log = logging.getLogger(__name__)

Run = tuple[datetime, datetime, str]
# (device id, days) -> (monotonic time, runs or None)
_cache: dict[tuple[str, int], tuple[float, list[Run] | None]] = {}


def cloud_runs(db: Session, device: Device, days: int) -> list[Run] | None:
    key = (device.id, days)
    cached = _cache.get(key)
    if cached is not None:
        age = time.monotonic() - cached[0]
        if age < (CACHE_SECONDS if cached[1] is not None else RETRY_SECONDS):
            return cached[1]
    found: list[Run] | None
    end = utcnow()
    begin = end - timedelta(days=days)
    try:
        api, loop, cloud_id = _connection(db, device)
        reports = cync_runtime.reports_on_open(api, loop, cloud_id, begin - LEAD, end)
        found = cync_runtime.runs(reports, begin, end)
    except (CyncUnavailable, cync.CyncError, LookupError) as error:
        log.info("thermostat runs not read from Cync: %s", error)
        found = None
    _cache[key] = (time.monotonic(), found)
    return found
