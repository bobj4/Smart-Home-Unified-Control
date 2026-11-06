"""LG webOS TVs (2014 and newer) over the TV's local websocket API.

Pairing: the TV shows a prompt; someone accepts it with the remote, and the
TV gives a key that later connections send. Newer firmware listens on
wss://TV:3001 (a self-signed certificate, so it is not checked: the TV is
on the home network and the key is what protects it); older on ws://TV:3000.
Tests replace these functions.
"""

import itertools
import json
import socket
import ssl
from typing import Any

import websocket

PAIR_TIMEOUT_SECONDS = 60
TIMEOUT_SECONDS = 6
PERMISSIONS = [
    "LAUNCH",
    "LAUNCH_WEBAPP",
    "APP_TO_APP",
    "CONTROL_AUDIO",
    "CONTROL_DISPLAY",
    "CONTROL_INPUT_JOYSTICK",
    "CONTROL_INPUT_MEDIA_PLAYBACK",
    "CONTROL_INPUT_TV",
    "CONTROL_POWER",
    "READ_APP_STATUS",
    "READ_CURRENT_CHANNEL",
    "READ_INPUT_DEVICE_LIST",
    "READ_INSTALLED_APPS",
    "READ_TV_CHANNEL_LIST",
    "READ_RUNNING_APPS",
    "READ_POWER_STATE",
    "WRITE_NOTIFICATION_TOAST",
    "CONTROL_INPUT_TEXT",
    "CONTROL_MOUSE_AND_KEYBOARD",
    "READ_NETWORK_STATE",
    "READ_COUNTRY_INFO",
    "READ_LGE_SDX",
]
APP_IDS = {
    "netflix": "netflix",
    "youtube": "youtube.leanback.v4",
    "prime_video": "amazon",
    "disney_plus": "com.disney.disneyplus-prod",
    "hulu": "hulu",
    "spotify": "spotify-beehive",
}
INPUTS = {"hdmi1": "HDMI_1", "hdmi2": "HDMI_2", "hdmi3": "HDMI_3", "hdmi4": "HDMI_4"}
BUTTONS = {
    "up": "UP",
    "down": "DOWN",
    "left": "LEFT",
    "right": "RIGHT",
    "select": "ENTER",
    "back": "BACK",
    "home": "HOME",
    "menu": "MENU",
    "info": "INFO",
    "guide": "GUIDE",
}
MEDIA = {
    "play": "play",
    "pause": "pause",
    "stop": "stop",
    "rewind": "rewind",
    "fast_forward": "fastForward",
}
SIMPLE = {
    "turn_off": "ssap://system/turnOff",
    "volume_up": "ssap://audio/volumeUp",
    "volume_down": "ssap://audio/volumeDown",
    "channel_up": "ssap://tv/channelUp",
    "channel_down": "ssap://tv/channelDown",
}


class LgError(Exception):
    """The TV could not be reached or refused."""


class LgDenied(LgError):
    """The TV refused the key or the prompt was declined."""


class LgUnsupported(LgError):
    """The TV cannot do that."""


def _open(host: str, timeout: float) -> Any:
    errors = []
    for url, options in (
        (f"wss://{host}:3001", {"cert_reqs": ssl.CERT_NONE, "check_hostname": False}),
        (f"ws://{host}:3000", None),
    ):
        try:
            return websocket.create_connection(url, timeout=timeout, sslopt=options)
        except (OSError, websocket.WebSocketException) as error:
            errors.append(type(error).__name__)
    raise LgError(f"could not reach the TV ({', '.join(errors)}); is it on?")


class _Session:
    def __init__(self, host: str, key: str | None, timeout: float = TIMEOUT_SECONDS):
        self.host = host
        self.ws = _open(host, timeout)
        self.ids = itertools.count(1)
        self.key = self._register(key, timeout)

    def _read(self) -> dict[str, Any]:
        try:
            return dict(json.loads(self.ws.recv()))
        except (OSError, websocket.WebSocketException, ValueError) as error:
            raise LgError(f"the TV stopped answering: {type(error).__name__}") from None

    def _register(self, key: str | None, timeout: float) -> str:
        payload: dict[str, Any] = {
            "forcePairing": False,
            "pairingType": "PROMPT",
            "manifest": {
                "manifestVersion": 1,
                "appVersion": "1.0",
                "permissions": PERMISSIONS,
                "signed": {
                    "appId": "com.smarthome.unifiedcontrol",
                    "vendorId": "smarthome",
                },
            },
        }
        if key:
            payload["client-key"] = key
        self.ws.settimeout(timeout if key else PAIR_TIMEOUT_SECONDS)
        self.ws.send(
            json.dumps({"type": "register", "id": "register_0", "payload": payload})
        )
        while True:
            message = self._read()
            if message.get("type") == "registered":
                self.ws.settimeout(TIMEOUT_SECONDS)
                return str(
                    (message.get("payload") or {}).get("client-key") or key or ""
                )
            if message.get("type") == "error":
                raise LgDenied("the TV refused: pair it again (and accept the prompt)")

    def request(
        self, uri: str, payload: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        msg_id = f"req_{next(self.ids)}"
        body: dict[str, Any] = {"type": "request", "id": msg_id, "uri": uri}
        if payload is not None:
            body["payload"] = payload
        self.ws.send(json.dumps(body))
        while True:
            message = self._read()
            if message.get("id") != msg_id:
                continue
            if message.get("type") == "error":
                raise LgUnsupported(f"the TV refused that: {message.get('error', '')}")
            return dict(message.get("payload") or {})

    def button(self, name: str) -> None:
        found = self.request(
            "ssap://com.webos.service.networkinput/getPointerInputSocket"
        )
        path = str(found.get("socketPath") or "")
        if not path.startswith(("ws://", "wss://")):
            raise LgError("the TV gave no remote-control socket")
        options = {"cert_reqs": ssl.CERT_NONE, "check_hostname": False}
        try:
            pointer = websocket.create_connection(
                path, timeout=TIMEOUT_SECONDS, sslopt=options
            )
            pointer.send(f"type:button\nname:{name}\n\n")
            pointer.close()
        except (OSError, websocket.WebSocketException) as error:
            raise LgError(
                f"the TV did not take the key: {type(error).__name__}"
            ) from None

    def close(self) -> None:
        try:
            self.ws.close()
        except (OSError, websocket.WebSocketException):
            pass


def pair(host: str) -> str:
    """Show the prompt on the TV and wait for it to be accepted; the key."""
    session = _Session(host, None)
    try:
        if not session.key:
            raise LgDenied("the TV gave no key")
        return session.key
    finally:
        session.close()


def is_on(host: str) -> bool:
    """On if the TV's control port answers (off TVs close it)."""
    for port in (3001, 3000):
        try:
            with socket.create_connection((host, port), timeout=1.5):
                return True
        except OSError:
            continue
    return False


def apps(host: str, key: str) -> list[dict[str, str]]:
    session = _Session(host, key)
    try:
        found = session.request("ssap://com.webos.applicationManager/listLaunchPoints")
    finally:
        session.close()
    return [
        {"id": str(p["id"]), "name": str(p.get("title") or p["id"])}
        for p in found.get("launchPoints") or []
        if p.get("id")
    ]


def command(host: str, key: str, name: str, payload: dict[str, Any]) -> None:
    """Carry out an already validated TV command (turning on is by Wake-on-LAN,
    done by the caller)."""
    session = _Session(host, key)
    try:
        if name in SIMPLE:
            session.request(SIMPLE[name])
        elif name == "set_volume":
            session.request("ssap://audio/setVolume", {"volume": int(payload["level"])})
        elif name == "toggle_mute":
            status = session.request("ssap://audio/getStatus")
            session.request("ssap://audio/setMute", {"mute": not status.get("mute")})
        elif name == "set_channel":
            session.request(
                "ssap://tv/openChannel", {"channelNumber": str(payload["channel"])}
            )
        elif name == "set_input":
            source = str(payload["source"])
            if source == "tv":
                session.request(
                    "ssap://system.launcher/launch", {"id": "com.webos.app.livetv"}
                )
            elif source in INPUTS:
                session.request("ssap://tv/switchInput", {"inputId": INPUTS[source]})
            else:
                raise LgUnsupported("this TV has no such input")
        elif name == "launch_app":
            session.request(
                "ssap://system.launcher/launch", {"id": APP_IDS[str(payload["app"])]}
            )
        elif name == "open_app":
            session.request(
                "ssap://system.launcher/launch", {"id": str(payload["app_id"])}
            )
        elif name == "press_key":
            key_name = str(payload["key"])
            if key_name in MEDIA:
                session.request(f"ssap://media.controls/{MEDIA[key_name]}")
            else:
                session.button(BUTTONS[key_name])
        else:
            raise LgUnsupported("an LG TV cannot do that")
    finally:
        session.close()
