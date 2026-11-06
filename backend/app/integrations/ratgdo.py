"""ratgdo garage door openers running ESPHome firmware, through ESPHome's
web server on the device (on by default in ratgdo's ESPHome builds): plain
HTTP on the home network. Tests replace these functions.
"""

from typing import Any

import requests

TIMEOUT_SECONDS = 5
STATES = {"OPEN": "open", "CLOSED": "closed"}
MOVING = {"OPENING": "opening", "CLOSING": "closing"}


class RatgdoError(Exception):
    """The opener could not be reached or refused."""


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
        raise RatgdoError(
            "no garage door on that address (is it a ratgdo with ESPHome?)"
        )
    if response.status_code >= 400:
        raise RatgdoError(f"the ratgdo answered {response.status_code}")
    return response.json() if method == "GET" else None


def door(host: str) -> dict[str, Any]:
    """{"door": open|closed|opening|closing, "position": 0-100 or None}."""
    data = _call("GET", f"http://{host}/cover/door") or {}
    moving = MOVING.get(str(data.get("current_operation", "")).upper())
    state = moving or STATES.get(str(data.get("state", "")).upper(), "stopped")
    value = data.get("value")
    position = round(float(value) * 100) if isinstance(value, int | float) else None
    return {"door": state, "position": position}


def act(host: str, command: str) -> None:
    if command not in ("open", "close", "stop"):
        raise RatgdoError("not a garage door command")
    _call("POST", f"http://{host}/cover/door/{command}")
