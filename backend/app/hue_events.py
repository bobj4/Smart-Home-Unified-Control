"""Hue lights change here as soon as they change anywhere (the Hue app, a
dimmer switch, a motion sensor), not only at the next refresh: the bridge's
event stream (Hue API v2, https://<bridge>/eventstream/clip/v2) is kept
open, and any event reads that home's lights again (hue_home.refresh),
at most once every SETTLE_SECONDS.

The bridge's certificate is its own (signed by Signify, not a public
authority), so it is not checked; the key in the header is what lets this
server in, as on every other bridge call. A first-generation (round)
bridge has no event stream: it keeps the normal refresh.
"""

import logging
import threading
import time
from typing import Any

import requests
from sqlalchemy import select

from app import credentials, hue_home
from app.db_config import SessionLocal
from app.features import integration_enabled
from app.models import Home

log = logging.getLogger(__name__)
CHECK_SECONDS = 60  # look for newly paired bridges this often
SETTLE_SECONDS = 0.5
RETRY_SECONDS = (5, 30, 120, 600)
NO_STREAM_SECONDS = 3600  # a bridge without the stream: ask again in an hour
_streams: dict[str, threading.Thread] = {}
_stop = threading.Event()


def _bridges() -> dict[str, tuple[str, str]]:
    """Paired bridges by home: home id -> (host, key)."""
    found: dict[str, tuple[str, str]] = {}
    with SessionLocal() as db:
        for home_id in db.scalars(select(Home.id)).all():
            if not integration_enabled(db, home_id, hue_home.INTEGRATION):
                continue
            if credentials.label(db, home_id, hue_home.INTEGRATION) is None:
                continue
            try:
                found[home_id] = hue_home._bridge(db, home_id)  # noqa: SLF001
            except hue_home.HueUnavailable:
                continue
    return found


def changed(home_id: str) -> None:
    """Read the home's lights again (an event arrived)."""
    with SessionLocal() as db:
        try:
            hue_home.refresh(db, home_id)
        except Exception:  # the next event or refresh tries again
            db.rollback()
            log.exception("hue: reading lights after an event failed")


def open_stream(host: str, key: str) -> Any:
    return requests.get(
        f"https://{host}/eventstream/clip/v2",
        headers={"hue-application-key": key, "Accept": "text/event-stream"},
        stream=True,
        timeout=(5, 120),  # the bridge sends a keep-alive well within this
        # The bridge's own certificate (see the module notes).
        verify=False,  # nosec B501
    )


def follow(home_id: str, host: str, key: str) -> None:
    """Keep the bridge's stream open until stopped or the bridge changes."""
    misses = 0
    while not _stop.is_set():
        if _bridges().get(home_id) != (host, key):
            return  # unpaired, turned off or paired again: a new thread follows
        try:
            with open_stream(host, key) as response:
                if response.status_code == 404:
                    _stop.wait(NO_STREAM_SECONDS)
                    continue
                if response.status_code != 200:
                    raise requests.RequestException(f"HTTP {response.status_code}")
                misses = 0
                last = 0.0
                for line in response.iter_lines():
                    if _stop.is_set():
                        return
                    if (
                        line.startswith(b"data:")
                        and time.monotonic() - last > SETTLE_SECONDS
                    ):
                        last = time.monotonic()
                        changed(home_id)
        except requests.RequestException as error:
            log.info("hue: event stream for a home closed: %s", type(error).__name__)
        _stop.wait(RETRY_SECONDS[min(misses, len(RETRY_SECONDS) - 1)])
        misses += 1


def check() -> None:
    """Start a stream for each paired bridge that has none."""
    for home_id, (host, key) in _bridges().items():
        thread = _streams.get(home_id)
        if thread is not None and thread.is_alive():
            continue
        thread = threading.Thread(
            target=follow,
            args=(home_id, host, key),
            daemon=True,
            name=f"hue-{home_id[:8]}",
        )
        _streams[home_id] = thread
        thread.start()


async def run_forever() -> None:
    import asyncio

    import urllib3

    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
    try:
        while True:
            await asyncio.to_thread(check)
            await asyncio.sleep(CHECK_SECONDS)
    finally:
        _stop.set()
