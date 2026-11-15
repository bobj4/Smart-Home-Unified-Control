"""ratgdo garage door openers running ESPHome firmware, through ESPHome's
web server on the device (on by default in ratgdo's ESPHome builds): plain
HTTP on the home network. Tests replace these functions.
"""

from typing import Any

import requests

TIMEOUT_SECONDS = 5
# The door's address on the opener: by its name ("Door"), as ESPHome 2026.7
# and newer require, else by the older object id (earlier firmware).
DOOR_PATHS = ("/cover/Door", "/cover/door", "/cover/Garage%20Door")
_door_path: dict[str, str] = {}  # host -> the path that answered
STATES = {"OPEN": "open", "CLOSED": "closed"}
MOVING = {"OPENING": "opening", "CLOSING": "closing"}


class RatgdoError(Exception):
    """The opener could not be reached or refused."""


class RatgdoNotFound(RatgdoError):
    """Nothing at that path on the opener."""


def _call(method: str, url: str) -> Any:
    try:
        response = requests.request(method, url, timeout=TIMEOUT_SECONDS)
    except requests.RequestException as error:
        raise RatgdoError(
            f"could not reach the ratgdo: {type(error).__name__}"
        ) from None
    if response.status_code == 401:
        raise RatgdoError(
            "the ratgdo asks for a password: turn off its web server login"
        )
    if response.status_code == 404:
        raise RatgdoNotFound(
            "no garage door on that address (is it a ratgdo with ESPHome?)"
        )
    if response.status_code >= 400:
        raise RatgdoError(f"the ratgdo answered {response.status_code}")
    if method != "GET":
        return None
    try:
        return response.json()
    except ValueError:
        raise RatgdoError(
            "that address answered, but not as a ratgdo (is it a ratgdo with ESPHome?)"
        ) from None


def _door_call(method: str, host: str, suffix: str = "") -> Any:
    """Call the door at whichever path the opener answers (see DOOR_PATHS)."""
    known = _door_path.get(host)
    paths = ([known] if known else []) + [p for p in DOOR_PATHS if p != known]
    missing: RatgdoNotFound | None = None
    for path in paths:
        try:
            found = _call(method, f"http://{host}{path}{suffix}")
        except RatgdoNotFound as error:
            missing = error
            continue
        _door_path[host] = path
        return found
    raise missing or RatgdoError("no garage door on that address")


def door(host: str) -> dict[str, Any]:
    """{"door": open|closed|opening|closing, "position": 0-100 or None}."""
    data = _door_call("GET", host) or {}
    moving = MOVING.get(str(data.get("current_operation", "")).upper())
    state = moving or STATES.get(str(data.get("state", "")).upper(), "stopped")
    value = data.get("value")
    position = round(float(value) * 100) if isinstance(value, int | float) else None
    return {"door": state, "position": position}


def act(host: str, command: str) -> None:
    if command not in ("open", "close", "stop"):
        raise RatgdoError("not a garage door command")
    _door_call("POST", host, f"/{command}")
