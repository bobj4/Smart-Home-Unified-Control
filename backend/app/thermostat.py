"""Thermostat commands besides the dial: mode, fan and schedule hold, and which set point the
dial changes. Validation and the resulting state; the device is told by
device_io (Cync) or not at all (demo thermostats, which only have a target).
Set points stay within the safety limits (checked by the caller)."""

from typing import Any

THERMOSTAT_COMMANDS = ("set_mode", "set_fan", "set_hold")
FANS = ("auto", "on")
# Follow the schedule, hold until the next scheduled change, or hold for good.
HOLDS = ("schedule", "temporary", "permanent")
ECO_REFUSED = "leave Eco mode first: the thermostat ignores set points in Eco"


class ThermostatError(Exception):
    def __init__(self, status_code: int, reason: str) -> None:
        self.status_code = status_code
        self.reason = reason


def _one(payload: dict[str, Any], key: str) -> Any:
    if set(payload) != {key}:
        raise ThermostatError(422, f"payload must have exactly: {key}")
    return payload[key]


def thermostat_state(
    state: dict[str, Any], command: str, payload: dict[str, Any]
) -> dict[str, Any]:
    """New state for set_mode, set_fan or set_hold."""
    if command == "set_mode":
        mode = _one(payload, "mode")
        if mode not in state.get("modes", []):
            raise ThermostatError(422, "this thermostat does not have that mode")
        new = {**state, "mode": mode}
        if mode == "cool" and state.get("cool_setpoint") is not None:
            new["target_temperature"] = state["cool_setpoint"]
        elif mode != "cool" and state.get("heat_setpoint") is not None:
            new["target_temperature"] = state["heat_setpoint"]
        return new
    if command == "set_fan":
        fan = _one(payload, "fan")
        if "fan" not in state:
            raise ThermostatError(422, "this thermostat has no fan setting")
        if fan not in FANS:
            raise ThermostatError(422, "fan must be auto or on")
        return {**state, "fan": fan}
    if command == "set_hold":
        hold = _one(payload, "hold")
        if state.get("hold") is None:
            raise ThermostatError(
                422, "this thermostat does not report its schedule hold"
            )
        if hold not in HOLDS:
            raise ThermostatError(422, "hold must be schedule, temporary or permanent")
        return {**state, "hold": hold}
    raise ThermostatError(422, "unsupported command")


def set_point_state(
    state: dict[str, Any], new: dict[str, Any], command: str, temperature: float
) -> dict[str, Any]:
    """Which set point a set_temperature (the dial) or set_cool_temperature
    (cooling in Auto) changes. Demo thermostats have no mode: only the target."""
    mode = state.get("mode")
    if mode is None:
        if command != "set_temperature":
            raise ThermostatError(422, "unsupported command")
        return new
    if mode == "eco":
        raise ThermostatError(409, ECO_REFUSED)
    if command == "set_cool_temperature":
        if mode != "auto":
            raise ThermostatError(422, "a separate cooling set point is for Auto mode")
        heat = state.get("heat_setpoint")
        if heat is not None and temperature <= heat:
            raise ThermostatError(422, "cooling must be set above heating")
        return {**state, "cool_setpoint": temperature, "unit": new["unit"]}
    if mode == "cool":
        return {**new, "cool_setpoint": temperature}
    cool = state.get("cool_setpoint")
    if mode == "auto" and cool is not None and temperature >= cool:
        raise ThermostatError(422, "heating must be set below cooling")
    return {**new, "heat_setpoint": temperature}
