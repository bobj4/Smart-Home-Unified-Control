"""Live state: the server re-reads real devices in the background.

Samsung TVs are probed every pass (a quick local request). Rheem EcoNet is
read at most every RHEEM_SECONDS per home, because EcoNet refuses accounts
that log in too often. Frigate is read by the browser when the Cameras page
is open, so it is not polled here.
"""

import asyncio
import json
import logging
import time

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import cync_home, rheem_home, samsung_home, verbose
from app.db_config import SessionLocal
from app.features import integration_enabled
from app.integrations import samsung
from app.models import Device, Home, utcnow

RHEEM_SECONDS = 300
CYNC_SECONDS = 300  # each read opens a connection to Cync's server
log = logging.getLogger(__name__)
_rheem_read_at: dict[str, float] = {}
_cync_read_at: dict[str, float] = {}


def refresh_tvs(db: Session, home_id: str) -> int:
    """Update the on/off state of the home's paired TVs; returns how many
    changed."""
    if not integration_enabled(db, home_id, samsung_home.INTEGRATION):
        return 0
    changed = 0
    for tv in samsung_home.list_tvs(db, home_id):
        settings = samsung_home.config(tv)
        if not settings["paired"]:
            continue
        on = samsung.is_on(str(tv.external_id), settings["protocol"])
        state = json.loads(tv.state or "{}")
        if state.get("on") != on:
            tv.state = json.dumps({**state, "on": on})
            tv.last_updated = utcnow()
            changed += 1
    db.commit()
    return changed


def refresh_rheem(db: Session, home_id: str, now: float | None = None) -> bool:
    """Re-read the home's water heaters if the last read is old enough.
    Returns whether EcoNet was read."""
    now = time.monotonic() if now is None else now
    last = _rheem_read_at.get(home_id)
    if last is not None and now - last < RHEEM_SECONDS:
        return False
    has_heaters = db.scalars(
        select(Device.id).where(
            Device.home_id == home_id, Device.integration == rheem_home.INTEGRATION
        )
    ).first()
    if has_heaters is None:
        return False
    _rheem_read_at[home_id] = now
    try:
        rheem_home.sync(db, home_id)
    except rheem_home.RheemUnavailable as error:
        db.rollback()
        log.info("Rheem refresh skipped for a home: %s", error.reason)
        verbose.note(
            db,
            "refresh",
            home_id=home_id,
            details={
                "integration": "rheem_econet",
                "result": "failed",
                "reason": error.reason,
            },
        )
        return False
    return True


def refresh_cync(db: Session, home_id: str, now: float | None = None) -> bool:
    """Re-sync the home's Cync account (devices and their state) at most
    every CYNC_SECONDS. Returns whether Cync was read."""
    now = time.monotonic() if now is None else now
    last = _cync_read_at.get(home_id)
    if last is not None and now - last < CYNC_SECONDS:
        return False
    if not integration_enabled(db, home_id, cync_home.INTEGRATION):
        return False
    _cync_read_at[home_id] = now
    try:
        cync_home.sync(db, home_id)
    except cync_home.CyncUnavailable as error:
        db.rollback()
        log.info("Cync refresh skipped for a home: %s", error.reason)
        verbose.note(
            db,
            "refresh",
            home_id=home_id,
            details={"integration": "cync", "result": "failed", "reason": error.reason},
        )
        return False
    return True


def refresh_all(db: Session) -> None:
    for home_id in db.scalars(select(Home.id)).all():
        steps = (
            (refresh_tvs, "samsung_tv"),
            (refresh_rheem, "rheem_econet"),
            (refresh_cync, "cync"),
        )
        for step, integration in steps:
            start = time.monotonic()
            try:
                result = step(db, home_id)
            except Exception as error:  # one broken home must not stop the others
                db.rollback()
                log.exception("live refresh failed (%s)", step.__name__)
                verbose.note(
                    db,
                    "refresh",
                    home_id=home_id,
                    details={
                        "integration": integration,
                        "result": "error",
                        "reason": type(error).__name__,
                        "ms": verbose.ms_since(start),
                    },
                )
                continue
            if result:  # it really read the integration (not skipped as recent)
                verbose.note(
                    db,
                    "refresh",
                    home_id=home_id,
                    details={
                        "integration": integration,
                        "result": "ok",
                        "changed": result if result is not True else None,
                        "ms": verbose.ms_since(start),
                    },
                )


def _pass() -> None:
    with SessionLocal() as db:
        refresh_all(db)


async def run_forever(every_seconds: int) -> None:
    """The background task started with the app (REFRESH_SECONDS)."""
    while True:
        await asyncio.sleep(every_seconds)
        await asyncio.to_thread(_pass)
