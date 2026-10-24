"""Light and plug commands: validation and the resulting state.

Pure functions: the caller stores the new state. A real light integration
(Cync) maps the same commands to its own protocol later.
"""

import re
from typing import Any

LIGHT_DEFAULTS: dict[str, Any] = {
    "on": False,
    "brightness": 100,
    "color_mode": "temp",
    "color_temp": 2700,
    "color": "#ffffff",
}
PLUG_DEFAULTS: dict[str, Any] = {"on": False}
MIN_KELVIN, MAX_KELVIN = 2000, 6500
HEX_COLOR = re.compile(r"^#[0-9a-f]{6}$")


class LightError(Exception):
    def __init__(self, status_code: int, reason: str) -> None:
        self.status_code = status_code
        self.reason = reason


def _keys(payload: dict[str, Any], keys: set[str]) -> None:
    if set(payload) != keys:
        raise LightError(422, f"payload must contain exactly: {sorted(keys)}")


def _whole(payload: dict[str, Any], key: str, low: int, high: int) -> int:
    value = payload[key]
    if (
        isinstance(value, bool)
        or not isinstance(value, int | float)
        or value != int(value)
    ):
        raise LightError(422, f"{key} must be a whole number from {low} to {high}")
    if not low <= value <= high:
        raise LightError(422, f"{key} must be a whole number from {low} to {high}")
    return int(value)


def light_state(
    device_type: str, state: dict[str, Any], command: str, payload: dict[str, Any]
) -> dict[str, Any]:
    """Return the state after `command` for a light or plug, or raise LightError."""
    defaults = LIGHT_DEFAULTS if device_type == "light" else PLUG_DEFAULTS
    current = {**defaults, **state}
    if command in ("turn_on", "turn_off"):
        _keys(payload, set())
        return {**current, "on": command == "turn_on"}
    if device_type != "light":
        raise LightError(422, "unsupported command")
    if command == "set_brightness":
        _keys(payload, {"brightness"})
        return {**current, "brightness": _whole(payload, "brightness", 0, 100)}
    if command == "set_color_temp":
        _keys(payload, {"kelvin"})
        kelvin = _whole(payload, "kelvin", MIN_KELVIN, MAX_KELVIN)
        return {**current, "on": True, "color_mode": "temp", "color_temp": kelvin}
    if command == "set_color":
        _keys(payload, {"color"})
        color = payload["color"]
        if not isinstance(color, str) or not HEX_COLOR.match(color.lower()):
            raise LightError(422, 'color must look like "#ff8800"')
        return {**current, "on": True, "color_mode": "rgb", "color": color.lower()}
    raise LightError(422, "unsupported command")
