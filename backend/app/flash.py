"""Flashing lights: a scene (or schedule) step "flash" on a light or a group.

Payload: {"times" (1 to MAX_TIMES), "on_seconds" (how long a flash lasts),
"off_seconds" (how long between flashes)}, seconds from MIN_SECONDS to
MAX_SECONDS, at most MAX_TOTAL_SECONDS in all.

A flash is the light on for on_seconds, then off for off_seconds. A light
that is on first goes off for off_seconds, so the first flash shows. When
done, each light is back on or off as it was (its brightness and color are
not touched). The flashing runs in the background, after the scene's other
steps, so it shows what they set; a light already flashing is left to
finish. Each on and off is sent like any command, without filling the
Activity Log: one "light_flash" entry covers it.
"""

import json
import logging
import threading
import time
from collections.abc import Callable
from typing import Any

from app.audit import record_event
from app.db_config import SessionLocal
from app.models import Device, utcnow

log = logging.getLogger(__name__)
COMMAND = "flash"
MAX_TIMES = 20
MIN_SECONDS = 0.5
MAX_SECONDS = 10.0
MAX_TOTAL_SECONDS = 300.0
DEFAULTS = {"times": 3, "on_seconds": 1.0, "off_seconds": 1.0}

_busy: set[str] = set()
_lock = threading.Lock()


class FlashError(ValueError):
    """A flash step that does not fit."""


def check(payload: dict[str, Any]) -> dict[str, Any]:
    """The payload, checked: raises FlashError."""
    if set(payload) != set(DEFAULTS):
        raise FlashError("payload must contain exactly: off_seconds, on_seconds, times")
    times = payload["times"]
    if (
        isinstance(times, bool)
        or not isinstance(times, int)
        or not 1 <= times <= MAX_TIMES
    ):
        raise FlashError(f"times must be a whole number from 1 to {MAX_TIMES}")
    out: dict[str, Any] = {"times": times}
    for key in ("on_seconds", "off_seconds"):
        value = payload[key]
        if isinstance(value, bool) or not isinstance(value, int | float):
            raise FlashError(f"{key} must be a number")
        if not MIN_SECONDS <= value <= MAX_SECONDS:
            raise FlashError(f"{key} must be from {MIN_SECONDS} to {MAX_SECONDS:g}")
        out[key] = round(float(value), 1)
    total = times * (out["on_seconds"] + out["off_seconds"])
    if total > MAX_TOTAL_SECONDS:
        raise FlashError(f"at most {MAX_TOTAL_SECONDS:g} seconds of flashing in all")
    return out


def start(
    home_id: str,
    device_ids: list[str],
    payload: dict[str, Any],
    user_id: str | None,
    run: Callable[..., None] | None = None,
) -> list[str]:
    """Begin flashing these lights in the background; returns the ones
    started (not those already flashing)."""
    checked = check(payload)
    with _lock:
        mine = [d for d in dict.fromkeys(device_ids) if d not in _busy]
        _busy.update(mine)
    if not mine:
        return []
    target = run or _flash
    thread = threading.Thread(
        target=target, args=(home_id, mine, checked, user_id), daemon=True
    )
    thread.start()
    return mine


def _switch(db: Any, device: Device, on: bool) -> bool:
    """One on or off; False when the light cannot take it."""
    from app.device_io import DeviceUnavailable, send_to_device
    from app.routes.devices import CommandRejected, DeviceCommand, _new_state

    command = DeviceCommand(command="turn_on" if on else "turn_off", payload={})
    try:
        state = _new_state(db, device, command)
        send_to_device(db, device, command.command, {}, state)
    except (CommandRejected, DeviceUnavailable) as error:
        log.info("flash: %s: %s", device.name, getattr(error, "reason", error))
        return False
    device.state = json.dumps(state)
    device.last_updated = utcnow()
    db.commit()
    return True


def _flash(
    home_id: str,
    device_ids: list[str],
    payload: dict[str, Any],
    user_id: str | None,
    sleep: Callable[[float], None] = time.sleep,
) -> None:
    try:
        with SessionLocal() as db:
            lights = [
                d
                for d in (db.get(Device, i) for i in device_ids)
                if d is not None and d.home_id == home_id
            ]
            was_on = {d.id: bool(json.loads(d.state or "{}").get("on")) for d in lights}
            record_event(
                db,
                "light_flash",
                user_id=user_id,
                home_id=home_id,
                details={"device_ids": [d.id for d in lights], **payload},
            )
            working = list(lights)
            if any(was_on.values()):  # off first, so the first flash shows
                working = [
                    d for d in working if not was_on[d.id] or _switch(db, d, False)
                ]
                sleep(payload["off_seconds"])
            for number in range(payload["times"]):
                working = [d for d in working if _switch(db, d, True)]
                sleep(payload["on_seconds"])
                working = [d for d in working if _switch(db, d, False)]
                if number < payload["times"] - 1:
                    sleep(payload["off_seconds"])
            for device in lights:  # back as they were
                db.refresh(device)
                if was_on[device.id] != bool(
                    json.loads(device.state or "{}").get("on")
                ):
                    _switch(db, device, was_on[device.id])
    except Exception:  # a background thread: note it, never crash the server
        log.exception("flashing lights failed")
    finally:
        with _lock:
            _busy.difference_update(device_ids)
