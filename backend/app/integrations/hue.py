"""Philips Hue, through the Hue Bridge's local API on the home network.
Pairing: press the round button on the bridge, then ask it for a key within
30 seconds. Tests replace these functions.
"""

from typing import Any

import requests

TIMEOUT_SECONDS = 6
DEVICE_TYPE = "smarthome#unifiedcontrol"
PLUG_TYPES = {"On/Off plug-in unit", "On/Off light", "On/Off plug"}


class HueError(Exception):
    """The bridge could not be reached or refused."""


class HueButton(HueError):
    """The bridge's link button was not pressed."""


def _call(method: str, url: str, body: Any = None) -> Any:
    try:
        response = requests.request(method, url, json=body, timeout=TIMEOUT_SECONDS)
    except requests.RequestException as error:
        raise HueError(
            f"could not reach the Hue Bridge: {type(error).__name__}"
        ) from None
    if response.status_code >= 400:
        raise HueError(f"the Hue Bridge answered {response.status_code}")
    data = response.json()
    # The v1 API answers errors as [{"error": {...}}] with status 200.
    if (
        isinstance(data, list)
        and data
        and isinstance(data[0], dict)
        and "error" in data[0]
    ):
        problem = data[0]["error"]
        if problem.get("type") == 101:
            raise HueButton(
                "press the button on the Hue Bridge, then try again within 30 seconds"
            )
        if problem.get("type") == 1:
            raise HueError("the Hue Bridge no longer knows this app: pair it again")
        raise HueError(
            f"the Hue Bridge refused: {problem.get('description', 'unknown error')}"
        )
    return data


def _base(host: str, key: str) -> str:
    return f"http://{host}/api/{key}"


def pair(host: str) -> str:
    """The key the bridge gives once its button has been pressed."""
    data = _call("POST", f"http://{host}/api", {"devicetype": DEVICE_TYPE})
    try:
        return str(data[0]["success"]["username"])
    except (KeyError, IndexError, TypeError):
        raise HueError("the Hue Bridge gave no key") from None


def lights(host: str, key: str) -> list[dict[str, Any]]:
    """Every light and smart plug: id, name, kind, what it can do, its state."""
    data = _call("GET", f"{_base(host, key)}/lights") or {}
    out = []
    for light_id, info in data.items():
        state = info.get("state") or {}
        control = (info.get("capabilities") or {}).get("control") or {}
        plug = info.get("type") in PLUG_TYPES or "bri" not in state
        out.append(
            {
                "id": str(light_id),
                "name": str(info.get("name") or "Hue light")[:100],
                "kind": "plug" if plug else "light",
                "white": "ct" in control or "ct" in state,
                "color": "colorgamut" in control or "xy" in state,
                "online": bool(state.get("reachable", True)),
                "on": bool(state.get("on")),
                "brightness": round(int(state.get("bri", 254)) * 100 / 254)
                if "bri" in state
                else None,
            }
        )
    return out


def set_state(host: str, key: str, light_id: str, body: dict[str, Any]) -> None:
    if not light_id.isdigit():
        raise HueError("not a Hue light id")
    _call("PUT", f"{_base(host, key)}/lights/{light_id}/state", body)


def hex_to_xy(color: str) -> list[float]:
    """An sRGB colour ("#ff8800") as the CIE xy the bridge takes."""
    rgb = [int(color[i : i + 2], 16) / 255 for i in (1, 3, 5)]
    lin = [((c + 0.055) / 1.055) ** 2.4 if c > 0.04045 else c / 12.92 for c in rgb]
    r, g, b = lin
    x = r * 0.4124 + g * 0.3576 + b * 0.1805
    y = r * 0.2126 + g * 0.7152 + b * 0.0722
    z = r * 0.0193 + g * 0.1192 + b * 0.9505
    total = x + y + z
    if total == 0:
        return [0.3227, 0.329]  # white point, for black
    return [round(x / total, 4), round(y / total, 4)]


def body_for(command: str, state: dict[str, Any]) -> dict[str, Any]:
    """The bridge's state change for one of the app's light commands."""
    if command in ("turn_on", "turn_off"):
        return {"on": command == "turn_on"}
    if command == "set_brightness":
        level = int(state["brightness"])
        if level == 0:
            return {"on": False}
        return {"on": True, "bri": max(1, round(level * 254 / 100))}
    if command == "set_color_temp":
        mired = round(1_000_000 / int(state["color_temp"]))
        return {"on": True, "ct": min(500, max(153, mired))}
    if command == "set_color":
        return {"on": True, "xy": hex_to_xy(str(state["color"]))}
    raise HueError("unsupported command")
