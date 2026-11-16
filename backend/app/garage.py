"""Garage door commands: validation and the resulting state. Pure functions:
the caller stores the new state (a ratgdo reports the real one)."""

from typing import Any

DOOR_STATES = ("open", "closed", "opening", "closing", "stopped")
COMMANDS = {"open": "opening", "close": "closing", "stop": "stopped"}
# A ratgdo's opener light and remote lockout (the wall button and remotes
# do nothing while locked): the state key and value each command sets.
EXTRA_COMMANDS = {
    "light_on": ("light", True),
    "light_off": ("light", False),
    "lock": ("locked", True),
    "unlock": ("locked", False),
    "laser_on": ("laser", True),  # ratgdo32 disco: the parking-assist laser
    "laser_off": ("laser", False),
}
PARKING_RANGE = (100, 5000)  # mm from the opener where the car should stop


class GarageError(Exception):
    def __init__(self, status_code: int, reason: str) -> None:
        self.status_code = status_code
        self.reason = reason


def garage_state(
    state: dict[str, Any], command: str, payload: dict[str, Any]
) -> dict[str, Any]:
    if command == "set_parking_target":
        if state.get("parking_target_mm") is None:
            raise GarageError(422, "this opener has no parking assist")
        mm = payload.get("mm") if set(payload) == {"mm"} else None
        low, high = PARKING_RANGE
        if not isinstance(mm, int) or isinstance(mm, bool) or not low <= mm <= high:
            raise GarageError(422, f"the stopping point is {low}-{high} mm")
        return {**state, "parking_target_mm": mm}
    if command not in COMMANDS and command not in EXTRA_COMMANDS:
        raise GarageError(422, "unsupported command")
    if payload:
        raise GarageError(422, "payload must be empty")
    if command in EXTRA_COMMANDS:
        key, value = EXTRA_COMMANDS[command]
        if state.get(key) is None:
            what = {"light": "light", "locked": "remote lockout"}.get(
                key, "parking laser"
            )
            raise GarageError(422, f"this opener reports no {what}")
        return {**state, key: value}
    return {**state, "door": COMMANDS[command]}
