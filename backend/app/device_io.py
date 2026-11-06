"""Sends an accepted command to a real device. The simulated integration has
no device: its new state is simply stored."""

import time
from typing import Any

from sqlalchemy.orm import Session

from app.cync_home import CyncUnavailable
from app.cync_home import send_command as send_cync_command
from app.hue_home import HueUnavailable
from app.hue_home import send_command as send_hue_command
from app.lg_home import LgUnavailable
from app.lg_home import send_tv_command as send_lg_command
from app.models import Device
from app.ratgdo_home import RatgdoUnavailable
from app.ratgdo_home import send_command as send_ratgdo_command
from app.rheem_home import RheemUnavailable
from app.rheem_home import send_command as send_rheem_command
from app.roku_home import RokuUnavailable
from app.roku_home import send_tv_command as send_roku_command
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
    if device.integration not in (
        "rheem_econet",
        "samsung_tv",
        "roku_tv",
        "lg_tv",
        "hue",
        "ratgdo",
        "cync",
    ):
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
    elif device.integration == "hue":
        try:
            send_hue_command(db, device, command, state)
        except HueUnavailable as error:
            raise DeviceUnavailable(error.status_code, error.reason) from None
    elif device.integration == "lg_tv":
        try:
            send_lg_command(db, device, command, payload)
        except LgUnavailable as error:
            raise DeviceUnavailable(error.status_code, error.reason) from None
    elif device.integration == "ratgdo":
        try:
            send_ratgdo_command(device, command)
        except RatgdoUnavailable as error:
            raise DeviceUnavailable(error.status_code, error.reason) from None
    elif device.integration == "roku_tv":
        try:
            send_roku_command(device, command, payload)
        except RokuUnavailable as error:
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
