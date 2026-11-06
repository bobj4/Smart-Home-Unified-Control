"""Roku TVs and players (TCL, Hisense, Sharp, Philips and other Roku TVs)
over Roku's local control protocol (ECP): plain HTTP on port 8060 of the
device, on the home network. No pairing and no account.

The device must allow it: Settings > System > Advanced system settings >
Control by mobile apps > Network access: Default (or Permissive).
Tests replace these functions.
"""

import html
import re

import requests

PORT = 8060
TIMEOUT_SECONDS = 5

# The usual quick-app buttons, by Roku channel id.
APP_IDS = {
    "netflix": "12",
    "youtube": "837",
    "prime_video": "13",
    "disney_plus": "291097",
    "hulu": "2285",
    "spotify": "22297",
}
KEYS = {
    "up": "Up",
    "down": "Down",
    "left": "Left",
    "right": "Right",
    "select": "Select",
    "back": "Back",
    "home": "Home",
    "info": "Info",
    "menu": "Info",
    "guide": "Info",
    "play": "Play",
    "pause": "Play",
    "stop": "Back",
    "rewind": "Rev",
    "fast_forward": "Fwd",
}
INPUTS = {
    "tv": "InputTuner",
    "hdmi1": "InputHDMI1",
    "hdmi2": "InputHDMI2",
    "hdmi3": "InputHDMI3",
    "hdmi4": "InputHDMI4",
    "usb": "InputAV1",
}
SIMPLE = {
    "turn_on": "PowerOn",
    "turn_off": "PowerOff",
    "volume_up": "VolumeUp",
    "volume_down": "VolumeDown",
    "toggle_mute": "VolumeMute",
    "channel_up": "ChannelUp",
    "channel_down": "ChannelDown",
}


class RokuError(Exception):
    """The device could not be reached or refused."""


class RokuUnsupported(RokuError):
    """This device cannot do that (a player has no inputs or tuner)."""


def _url(host: str, path: str) -> str:
    return f"http://{host}:{PORT}{path}"


def _get(host: str, path: str) -> str:
    try:
        response = requests.get(_url(host, path), timeout=TIMEOUT_SECONDS)
    except requests.RequestException as error:
        raise RokuError(f"could not reach the Roku: {type(error).__name__}") from None
    if response.status_code == 403:
        raise RokuError(
            "the Roku refused: allow Control by mobile apps in its settings"
        )
    if response.status_code >= 400:
        raise RokuError(f"the Roku answered {response.status_code}")
    return response.text


def _post(host: str, path: str) -> None:
    try:
        response = requests.post(_url(host, path), timeout=TIMEOUT_SECONDS)
    except requests.RequestException as error:
        raise RokuError(f"could not reach the Roku: {type(error).__name__}") from None
    if response.status_code == 403:
        raise RokuError(
            "the Roku refused: allow Control by mobile apps in its settings"
        )
    if response.status_code >= 400:
        raise RokuError(f"the Roku answered {response.status_code}")


def _tag(text: str, name: str) -> str | None:
    # A few flat fields from Roku's small XML answers; read with a pattern
    # rather than an XML parser, which would need hardening against entity
    # tricks from a device on the network.
    found = re.search(rf"<{name}>([^<]*)</{name}>", text)
    return html.unescape(found.group(1)).strip() if found else None


def info(host: str) -> dict[str, object]:
    """Name, model, whether it is a TV, and whether it is on."""
    text = _get(host, "/query/device-info")
    power = _tag(text, "power-mode") or "PowerOn"
    return {
        "name": _tag(text, "user-device-name") or _tag(text, "friendly-device-name"),
        "model": _tag(text, "model-name"),
        "is_tv": (_tag(text, "is-tv") or "false") == "true",
        "on": power == "PowerOn",
    }


def is_on(host: str) -> bool | None:
    """On, off (standby), or None when it cannot be reached."""
    try:
        return bool(info(host)["on"])
    except RokuError:
        return None


def apps(host: str) -> list[dict[str, str]]:
    """The installed channels (apps): [{"id", "name"}]."""
    text = _get(host, "/query/apps")
    found = re.findall(r'<app id="([0-9A-Za-z._-]+)"[^>]*>([^<]*)</app>', text)
    return [{"id": i, "name": html.unescape(n).strip()} for i, n in found]


def keypress(host: str, key: str) -> None:
    if not re.fullmatch(r"[A-Za-z0-9]+", key):
        raise RokuError("not a Roku key")
    _post(host, f"/keypress/{key}")


def launch(host: str, app_id: str) -> None:
    if not re.fullmatch(r"[A-Za-z0-9._-]{1,100}", app_id):
        raise RokuError("not a Roku app id")
    _post(host, f"/launch/{app_id}")


def tune(host: str, channel: int) -> None:
    """A channel on a Roku TV's antenna input."""
    _post(host, f"/launch/tvinput.dtv?ch={int(channel)}")


def command(host: str, name: str, payload: dict[str, object]) -> None:
    """Carry out an already validated TV command."""
    if name in SIMPLE:
        keypress(host, SIMPLE[name])
    elif name == "press_key":
        keypress(host, KEYS[str(payload["key"])])
    elif name == "set_input":
        keypress(host, INPUTS[str(payload["source"])])
    elif name == "launch_app":
        launch(host, APP_IDS[str(payload["app"])])
    elif name == "open_app":
        launch(host, str(payload["app_id"]))
    elif name == "set_channel":
        tune(host, int(str(payload["channel"])))
    elif name == "set_volume":
        raise RokuUnsupported(
            "a Roku cannot set an exact volume; use volume up and down"
        )
    else:
        raise RokuUnsupported("a Roku cannot do that")
