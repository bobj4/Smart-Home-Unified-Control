"""Sends an accepted command to a real device. The simulated integration has
no device: its new state is simply stored."""

import time
from typing import Any

from sqlalchemy.orm import Session

from app.cync_home import CyncUnavailable
from app.cync_home import send_command as send_cync_command
from app.models import Device
from app.rheem_home import RheemUnavailable
from app.rheem_home import send_command as send_rheem_command
from app.samsung_home import SamsungUnavailable, send_tv_command
from app.verbose import ms_since, note_apart


class DeviceUnavailable(Exception):
    def __init__(self, status_code: int, reason: str) -> None:
        self.status_code = status_code
        self.reason = reason


def send_to_device(
    db: Session,
    device: Device,
    command: str,
    payload: dict[str, Any],
    state: dict[str, Any],
) -> None:
    """Raise DeviceUnavailable if the device refused or could not be reached;
    the caller then leaves the stored state unchanged."""
    if device.integration not in ("rheem_econet", "samsung_tv", "cync"):
        return  # simulated: nothing to send
    start = time.monotonic()
    result: dict[str, Any] = {"result": "ok"}
    try:
        _send(db, device, command, payload, state)
    except DeviceUnavailable as error:
        result = {
            "result": "failed",
            "status": error.status_code,
            "reason": error.reason,
        }
        raise
    finally:
        # In its own session: the caller's changes are not committed here.
        note_apart(
            "vendor_command",
            home_id=device.home_id,
            details={
                "integration": device.integration,
                "device": device.name,
                "command": command,
                **result,
                "ms": ms_since(start),
            },
        )


def _send(
    db: Session,
    device: Device,
    command: str,
    payload: dict[str, Any],
    state: dict[str, Any],
) -> None:
    if device.integration == "rheem_econet":
        try:
            send_rheem_command(db, device, command, payload, state)
        except RheemUnavailable as error:
            raise DeviceUnavailable(error.status_code, error.reason) from None
    elif device.integration == "samsung_tv":
        try:
            send_tv_command(db, device, command, payload)
        except SamsungUnavailable as error:
            raise DeviceUnavailable(error.status_code, error.reason) from None
    elif device.integration == "cync":
        try:
            send_cync_command(db, device, command, state)
        except CyncUnavailable as error:
            raise DeviceUnavailable(error.status_code, error.reason) from None
