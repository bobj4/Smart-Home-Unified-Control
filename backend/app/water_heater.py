"""Water heater commands besides the target temperature: power, mode, away
and resuming the schedule. Validation and the resulting state; the device
is told by device_io (Rheem) or not at all (demo devices)."""

from typing import Any

WATER_HEATER_COMMANDS = (
    "turn_on",
    "turn_off",
    "set_mode",
    "set_away",
    "resume_schedule",
)
FOLLOWING = "Following Schedule"


class WaterHeaterError(Exception):
    def __init__(self, status_code: int, reason: str) -> None:
        self.status_code = status_code
        self.reason = reason


def _keys(payload: dict[str, Any], keys: set[str]) -> None:
    if set(payload) != keys:
        raise WaterHeaterError(
            422, f"payload must have exactly: {', '.join(sorted(keys)) or 'nothing'}"
        )


def _off(state: dict[str, Any]) -> dict[str, Any]:
    last = (
        state.get("mode")
        if state.get("mode") not in (None, "off")
        else state.get("last_mode")
    )
    return {
        **state,
        "enabled": False,
        "mode": "off",
        "last_mode": last,
        "status": "off",
        "running": False,
    }


def water_heater_state(
    state: dict[str, Any], command: str, payload: dict[str, Any]
) -> dict[str, Any]:
    """The state after `command`, or raise WaterHeaterError."""
    modes = [m for m in state.get("modes") or [] if isinstance(m, str)]
    if command == "turn_off":
        _keys(payload, set())
        return _off(state)
    if command == "turn_on":
        _keys(payload, set())
        mode = state.get("last_mode") or next((m for m in modes if m != "off"), None)
        return {**state, "enabled": True, "mode": mode, "status": "idle"}
    if command == "set_mode":
        _keys(payload, {"mode"})
        mode = payload["mode"]
        if not isinstance(mode, str) or mode not in modes:
            raise WaterHeaterError(
                422, f"mode must be one of: {', '.join(modes) or 'none'}"
            )
        if mode == "off":
            return _off(state)
        return {
            **state,
            "enabled": True,
            "mode": mode,
            "status": state.get("status") if state.get("enabled") else "idle",
        }
    if command == "set_away":
        _keys(payload, {"away"})
        if not isinstance(payload["away"], bool):
            raise WaterHeaterError(422, "away must be true or false")
        if state.get("away") is None:
            raise WaterHeaterError(422, "this water heater has no away mode")
        return {**state, "away": payload["away"]}
    if command == "resume_schedule":
        _keys(payload, set())
        if state.get("schedule") is None:
            raise WaterHeaterError(422, "this water heater has no schedule")
        return {
            **state,
            "schedule": FOLLOWING,
            "away": False if state.get("away") is not None else None,
        }
    raise WaterHeaterError(422, "unsupported command")
