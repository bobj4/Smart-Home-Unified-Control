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


# The ratgdo's other parts: the state key, ESPHome domain, the names it may
# answer to (by name on ESPHome 2026.7+, else the object id), and how its
# state reads as True.
EXTRAS = {
    "obstruction": ("binary_sensor", ("Obstruction", "obstruction"), ("ON",)),
    "light": ("light", ("Light", "light"), ("ON",)),
    "locked": ("lock", ("Lock%20remotes", "lock_remotes"), ("LOCKED",)),
}
EXTRA_ACTIONS = {
    "light_on": ("light", "turn_on"),
    "light_off": ("light", "turn_off"),
    "lock": ("locked", "lock"),
    "unlock": ("locked", "unlock"),
}
_extra_path: dict[tuple[str, str], str | None] = {}  # None: the opener has none


def _extra_call(method: str, host: str, key: str, suffix: str = "") -> Any:
    domain, names, _ = EXTRAS[key]
    known = _extra_path.get((host, key), "")
    if known is None:
        raise RatgdoNotFound("this opener has none")
    paths = [known] if known else [f"/{domain}/{name}" for name in names]
    for path in paths:
        try:
            found = _call(method, f"http://{host}{path}{suffix}")
        except RatgdoNotFound:
            continue
        _extra_path[(host, key)] = path
        return found
    _extra_path[(host, key)] = None
    raise RatgdoNotFound("this opener has none")


def extras(host: str) -> dict[str, bool | None]:
    """Obstruction, light and remote lockout: True, False, or None when
    the opener has no such part (or would not say)."""
    out: dict[str, bool | None] = {}
    for key, (_, _, truthy) in EXTRAS.items():
        try:
            data = _extra_call("GET", host, key) or {}
        except RatgdoError:
            out[key] = None
            continue
        out[key] = str(data.get("state", "")).upper() in truthy
    return out


def act(host: str, command: str) -> None:
    if command in EXTRA_ACTIONS:
        key, action = EXTRA_ACTIONS[command]
        try:
            _extra_call("POST", host, key, f"/{action}")
        except RatgdoNotFound:
            raise RatgdoError("this opener has no such part") from None
        return
    if command not in ("open", "close", "stop"):
        raise RatgdoError("not a garage door command")
    _door_call("POST", host, f"/{command}")
