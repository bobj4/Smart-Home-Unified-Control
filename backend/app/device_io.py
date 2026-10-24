"""Sends an accepted command to a real device. The simulated integration has
no device: its new state is simply stored."""

from typing import Any

from sqlalchemy.orm import Session

from app.cync_home import CyncUnavailable
from app.cync_home import send_command as send_cync_command
from app.models import Device
from app.rheem_home import RheemUnavailable
from app.rheem_home import send_command as send_rheem_command
from app.samsung_home import SamsungUnavailable, send_tv_command


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
