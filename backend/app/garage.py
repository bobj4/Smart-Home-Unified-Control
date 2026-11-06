"""Garage door commands: validation and the resulting state. Pure functions:
the caller stores the new state (a ratgdo reports the real one)."""

from typing import Any

DOOR_STATES = ("open", "closed", "opening", "closing", "stopped")
COMMANDS = {"open": "opening", "close": "closing", "stop": "stopped"}


class GarageError(Exception):
    def __init__(self, status_code: int, reason: str) -> None:
        self.status_code = status_code
        self.reason = reason


def garage_state(
    state: dict[str, Any], command: str, payload: dict[str, Any]
) -> dict[str, Any]:
    if command not in COMMANDS:
        raise GarageError(422, "unsupported command")
    if payload:
        raise GarageError(422, "payload must be empty")
    return {**state, "door": COMMANDS[command]}
