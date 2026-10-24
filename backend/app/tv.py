"""TV remote commands: validation and the resulting state.

Pure functions: the caller stores the new state. A real TV integration maps
the same commands to its own protocol later.
"""

from typing import Any

DEFAULTS: dict[str, Any] = {
    "on": False,
    "volume": 10,
    "muted": False,
    "channel": 1,
    "input": "tv",
    "app": None,
    "last_key": None,
}
INPUTS = ("tv", "hdmi1", "hdmi2", "hdmi3", "hdmi4", "usb")
KEYS = (
    "up",
    "down",
    "left",
    "right",
    "select",
    "back",
    "home",
    "menu",
    "info",
    "guide",
    "play",
    "pause",
    "stop",
    "rewind",
    "fast_forward",
)
APPS = ("netflix", "youtube", "prime_video", "disney_plus", "hulu", "spotify")
MAX_VOLUME = 100
MAX_CHANNEL = 9999


class RemoteError(Exception):
    def __init__(self, status_code: int, reason: str) -> None:
        self.status_code = status_code
        self.reason = reason


def _keys(payload: dict[str, Any], keys: set[str]) -> None:
    if set(payload) != keys:
        raise RemoteError(422, f"payload must contain exactly: {sorted(keys)}")


def _int(payload: dict[str, Any], key: str, low: int, high: int) -> int:
    value = payload[key]
    if (
        isinstance(value, bool)
        or not isinstance(value, int)
        or not low <= value <= high
    ):
        raise RemoteError(422, f"{key} must be a whole number from {low} to {high}")
    return value


def _choice(payload: dict[str, Any], key: str, allowed: tuple[str, ...]) -> str:
    value = payload[key]
    if value not in allowed:
        raise RemoteError(422, f"{key} must be one of {list(allowed)}")
    return str(value)


def tv_state(
    state: dict[str, Any], command: str, payload: dict[str, Any]
) -> dict[str, Any]:
    """Return the TV's state after `command`, or raise RemoteError."""
    tv = {**DEFAULTS, **state}
    if command in ("turn_on", "turn_off"):
        _keys(payload, set())
        return {**tv, "on": command == "turn_on"}
    handlers = {
        "volume_up": (
            {},
            lambda: {"volume": min(MAX_VOLUME, tv["volume"] + 1), "muted": False},
        ),
        "volume_down": (
            {},
            lambda: {"volume": max(0, tv["volume"] - 1), "muted": False},
        ),
        "set_volume": (
            {"level"},
            lambda: {"volume": _int(payload, "level", 0, MAX_VOLUME), "muted": False},
        ),
        "toggle_mute": ({}, lambda: {"muted": not tv["muted"]}),
        "channel_up": (
            {},
            lambda: {
                "channel": min(MAX_CHANNEL, tv["channel"] + 1),
                "input": "tv",
                "app": None,
            },
        ),
        "channel_down": (
            {},
            lambda: {"channel": max(1, tv["channel"] - 1), "input": "tv", "app": None},
        ),
        "set_channel": (
            {"channel"},
            lambda: {
                "channel": _int(payload, "channel", 1, MAX_CHANNEL),
                "input": "tv",
                "app": None,
            },
        ),
        "set_input": (
            {"source"},
            lambda: {"input": _choice(payload, "source", INPUTS), "app": None},
        ),
        "launch_app": ({"app"}, lambda: {"app": _choice(payload, "app", APPS)}),
        "press_key": ({"key"}, lambda: _key(payload)),
    }
    if command not in handlers:
        raise RemoteError(422, "unsupported command")
    keys, change = handlers[command]
    _keys(payload, set(keys))
    if not tv["on"]:
        raise RemoteError(409, "the TV is off")
    return {**tv, **change()}


def _key(payload: dict[str, Any]) -> dict[str, Any]:
    key = _choice(payload, "key", KEYS)
    change: dict[str, Any] = {"last_key": key}
    if key == "home":
        change["app"] = None
    return change
