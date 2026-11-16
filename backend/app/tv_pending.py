"""A TV being turned on or off is shown as pending ("Turning on…") until the
TV itself says it is, for at most PENDING_SECONDS; then its real state
shows. Only real TVs: a demo TV changes at once.

Kept in memory (a restart forgets it, which only ends the wait early). The
stored state is left to the command and the refreshes as before. Reading
the devices checks a pending TV every CHECK_SECONDS, so the page sees the
TV come on within seconds instead of at the next 30-second refresh.
"""

import json
import logging
import time
from collections.abc import Iterable

from sqlalchemy.orm import Session

from app.integrations import lg, roku, samsung
from app.models import Device, utcnow

PENDING_SECONDS = 60
CHECK_SECONDS = 3
REAL = ("samsung_tv", "lg_tv", "roku_tv")

log = logging.getLogger(__name__)

# device id -> (wanted on, started, last checked), monotonic seconds
_pending: dict[str, tuple[bool, float, float]] = {}


def start(device: Device, command: str) -> None:
    """After a power command was sent to a real TV."""
    if device.integration in REAL and command in ("turn_on", "turn_off"):
        now = time.monotonic()
        _pending[device.id] = (command == "turn_on", now, now)


def seen(device_id: str, on: bool) -> None:
    """A refresh read the TV: the wait is over if it is as wanted."""
    entry = _pending.get(device_id)
    if entry is not None and entry[0] == on:
        _pending.pop(device_id, None)


def pending(device_id: str) -> str | None:
    """'on' or 'off' while waiting for the TV, else None."""
    entry = _pending.get(device_id)
    if entry is None:
        return None
    if time.monotonic() - entry[1] > PENDING_SECONDS:
        _pending.pop(device_id, None)  # the TV never said: its real state shows
        return None
    return "on" if entry[0] else "off"


def _is_on(device: Device) -> bool | None:
    host = str(device.external_id)
    if device.integration == "samsung_tv":
        protocol = json.loads(device.capabilities or "{}").get("protocol", "tizen")
        return samsung.is_on(host, protocol)
    if device.integration == "lg_tv":
        return lg.is_on(host)
    return roku.is_on(host)


def check(db: Session, devices: Iterable[Device]) -> None:
    """Ask each pending TV (at most every CHECK_SECONDS) whether it is there
    yet; when it is, store it and end the wait."""
    now = time.monotonic()
    changed = False
    for device in devices:
        entry = _pending.get(device.id)
        if (
            entry is None
            or pending(device.id) is None
            or now - entry[2] < CHECK_SECONDS
        ):
            continue
        _pending[device.id] = (entry[0], entry[1], now)
        try:
            on = _is_on(device)
        except Exception as error:  # noqa: BLE001 - a TV's answer never fails the page
            log.info("pending TV check failed: %s", type(error).__name__)
            continue
        if on is entry[0]:
            state = json.loads(device.state or "{}")
            device.state = json.dumps({**state, "on": on, "reachable": True})
            device.last_updated = utcnow()
            _pending.pop(device.id, None)
            changed = True
    if changed:
        db.commit()
