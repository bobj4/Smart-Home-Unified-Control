"""Samsung TVs on the local network.

Three protocols, chosen per TV:
- "tizen": 2016 and newer models, through the samsungtvws library (websocket
  on port 8002). The first connection shows an "Allow" prompt on the TV; the
  token it returns is kept (encrypted by the caller) for later connections.
- "legacy": 2010-2013 models (C, D, E and F series), TCP port 55000, written
  here from the samsungctl project's protocol notes (MIT licence). The TV
  shows an "Allow" prompt the first time; there is no token.
- "encrypted": 2014-2015 models (H and J series), through samsungtvws's
  encrypted client. Pairing shows a PIN on the TV, typed into the app; the
  key and session id it returns are kept (encrypted by the caller).

The module-level functions are the only way the app talks to a TV; tests
replace them with fakes. Nothing here touches the database.
"""

import asyncio
import base64
import concurrent.futures
import socket
from typing import Any

import aiohttp
import requests
from samsungtvws import SamsungTVWS
from samsungtvws.encrypted.authenticator import (
    SamsungTVEncryptedError,
    SamsungTVEncryptedPairingExpiredError,
    SamsungTVEncryptedWSAsyncAuthenticator,
)
from samsungtvws.encrypted.remote import SamsungTVEncryptedWSAsyncRemote, SendRemoteKey
from samsungtvws.exceptions import ConnectionFailure, UnauthorizedError
from websockets.exceptions import WebSocketException

PROTOCOLS = ("tizen", "legacy")
CLIENT_NAME = "Smart Home"
TIMEOUT_SECONDS = 8
PROBE_SECONDS = 2

# Remote keys for each TV command (app/tv.py). Payloads are already validated.
KEYS = {
    "turn_off": ["KEY_POWER"],
    "volume_up": ["KEY_VOLUP"],
    "volume_down": ["KEY_VOLDOWN"],
    "toggle_mute": ["KEY_MUTE"],
    "channel_up": ["KEY_CHUP"],
    "channel_down": ["KEY_CHDOWN"],
}
INPUT_KEYS = {
    "tv": "KEY_TV",
    "hdmi1": "KEY_HDMI1",
    "hdmi2": "KEY_HDMI2",
    "hdmi3": "KEY_HDMI3",
    "hdmi4": "KEY_HDMI4",
    "usb": "KEY_SOURCE",
}
PRESS_KEYS = {
    "up": "KEY_UP",
    "down": "KEY_DOWN",
    "left": "KEY_LEFT",
    "right": "KEY_RIGHT",
    "select": "KEY_ENTER",
    "back": "KEY_RETURN",
    "home": "KEY_HOME",
    "menu": "KEY_MENU",
    "info": "KEY_INFO",
    "guide": "KEY_GUIDE",
    "play": "KEY_PLAY",
    "pause": "KEY_PAUSE",
    "stop": "KEY_STOP",
    "rewind": "KEY_REWIND",
    "fast_forward": "KEY_FF",
}
# Tizen app ids (Samsung's own store ids). Legacy TVs cannot launch apps.
APP_IDS = {
    "netflix": "3201907018807",
    "youtube": "111299001912",
    "prime_video": "3201910019365",
    "disney_plus": "3201901017640",
    "hulu": "3201601007625",
    "spotify": "3201606009684",
}


class TvError(Exception):
    """The TV could not be reached or did not accept the command."""


class TvDenied(TvError):
    """Someone pressed "Deny" on the TV, or the saved pairing was removed."""


class TvUnsupported(TvError):
    """This TV or protocol cannot do that (for example an exact volume)."""


def command_keys(command: str, payload: dict[str, Any]) -> list[str]:
    """The remote keys that carry out a TV command. Raises TvUnsupported for
    commands a real TV cannot do by key (set_volume, launch_app, turn_on)."""
    if command in KEYS:
        return list(KEYS[command])
    if command == "set_channel":
        return [f"KEY_{digit}" for digit in str(payload["channel"])] + ["KEY_ENTER"]
    if command == "set_input":
        return [INPUT_KEYS[payload["source"]]]
    if command == "press_key":
        return [PRESS_KEYS[payload["key"]]]
    raise TvUnsupported(f"{command} is not sent as remote keys")


# ------------------------------------------------------------ tizen


def _tizen(host: str, token: str | None) -> SamsungTVWS:
    return SamsungTVWS(
        host, token=token, port=8002, timeout=TIMEOUT_SECONDS, name=CLIENT_NAME
    )


def _tizen_call(host: str, token: str | None, action: Any) -> str | None:
    tv = _tizen(host, token)
    try:
        tv.open()
        action(tv)
        return tv.token
    except UnauthorizedError:
        raise TvDenied("the TV refused the connection") from None
    except (ConnectionFailure, OSError) as error:
        raise TvError(f"could not reach the TV: {type(error).__name__}") from None
    finally:
        tv.close()


# ------------------------------------------------------------ legacy


def _legacy_string(value: bytes, raw: bool = False) -> bytes:
    if not raw:
        value = base64.b64encode(value)
    return bytes([len(value)]) + b"\x00" + value


def _legacy_read(sock: socket.socket, first: bool = False) -> None:
    header = sock.recv(3)
    name_length = int.from_bytes(header[1:3], "little")
    sock.recv(name_length)
    length = int.from_bytes(sock.recv(2), "little")
    response = sock.recv(length)
    if not response:
        raise TvError("the TV closed the connection")
    if response in (b"\x64\x00\x01\x00", b"\x00\x00\x00\x00"):
        return
    if response == b"\x64\x00\x00\x00" or response[:1] == b"\x65":
        raise TvDenied("the TV refused the connection")
    if response[:1] == b"\x0a":  # waiting for someone to press Allow
        _legacy_read(sock, first)
        return
    raise TvError("the TV sent an unexpected reply")


def _legacy_send(host: str, keys: list[str]) -> None:
    try:
        with socket.create_connection((host, 55000), timeout=TIMEOUT_SECONDS) as sock:
            own_ip = sock.getsockname()[0].encode()
            hello = (
                b"\x64\x00"
                + _legacy_string(own_ip)
                + _legacy_string(b"smart-home")
                + _legacy_string(CLIENT_NAME.encode())
            )
            sock.sendall(b"\x00\x00\x00" + _legacy_string(hello, raw=True))
            _legacy_read(sock, first=True)
            for key in keys:
                payload = b"\x00\x00\x00" + _legacy_string(key.encode())
                sock.sendall(b"\x00\x00\x00" + _legacy_string(payload, raw=True))
                _legacy_read(sock)
    except OSError as error:
        raise TvError(f"could not reach the TV: {type(error).__name__}") from None


# ------------------------------------------------------------ encrypted (2014-2015)
# H and J series: pairing shows a 4-digit PIN on the TV (port 8080); keys are
# sent AES-encrypted over socket.io (port 8000). The saved token is
# "<key hex>:<session id>".

_ENCRYPTED_ERRORS = (
    aiohttp.ClientError,
    WebSocketException,
    ConnectionFailure,
    TimeoutError,
    OSError,
)


def _run(coro: Any) -> Any:
    """asyncio.run, in a separate thread if this one already runs a loop."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(asyncio.run, coro).result()


async def _show_pin(host: str) -> None:
    async with aiohttp.ClientSession() as web:
        auth = SamsungTVEncryptedWSAsyncAuthenticator(
            host, web_session=web, timeout=TIMEOUT_SECONDS
        )
        await auth.start_pairing()


async def _check_pin(host: str, pin: str) -> str:
    async with aiohttp.ClientSession() as web:
        auth = SamsungTVEncryptedWSAsyncAuthenticator(
            host, web_session=web, timeout=TIMEOUT_SECONDS
        )
        key = await auth.try_pin(pin)
        if not key:
            raise TvDenied("the TV did not accept that PIN")
        session_id = await auth.get_session_id_and_close()
        return f"{key}:{session_id}"


async def _encrypted_keys(host: str, token: str, keys: list[str]) -> None:
    key, _, session_id = token.partition(":")
    async with aiohttp.ClientSession() as web:
        async with SamsungTVEncryptedWSAsyncRemote(
            host,
            web_session=web,
            token=key,
            session_id=session_id,
            timeout=TIMEOUT_SECONDS,
            key_press_delay=0.3,
        ) as remote:
            await remote.send_commands([SendRemoteKey.click(k) for k in keys])


def _encrypted(coro: Any) -> Any:
    try:
        return _run(coro)
    except TvError:
        raise
    except SamsungTVEncryptedPairingExpiredError:
        raise TvDenied("the PIN expired: press Pair again") from None
    except SamsungTVEncryptedError:
        raise TvDenied("the TV refused the pairing: press Pair again") from None
    except _ENCRYPTED_ERRORS as error:
        raise TvError(f"could not reach the TV: {type(error).__name__}") from None


def start_pin_pairing(host: str) -> None:
    """2014-2015 TVs: show the pairing PIN on the TV. Raises TvError."""
    _encrypted(_show_pin(host))


def finish_pin_pairing(host: str, pin: str) -> str:
    """Pair with the PIN shown on the TV; returns the token to keep (encrypted).
    Raises TvDenied (wrong or expired PIN) or TvError."""
    return str(_encrypted(_check_pin(host, pin)))


# ------------------------------------------------------------ the interface


def pair(host: str, protocol: str) -> str | None:
    """Connect once so the TV shows its "Allow" prompt. Returns the token to
    keep (tizen) or None (legacy). Raises TvDenied or TvError."""
    if protocol == "legacy":
        _legacy_send(host, [])
        return None
    if protocol == "encrypted":
        raise TvUnsupported("2014-2015 TVs pair with a PIN")
    token = _tizen_call(host, None, lambda tv: None)
    if not token:
        raise TvError("the TV did not return a pairing token")
    return token


def send_keys(host: str, protocol: str, token: str | None, keys: list[str]) -> None:
    if protocol == "legacy":
        _legacy_send(host, keys)
        return
    if protocol == "encrypted":
        if not token or ":" not in token:
            raise TvDenied("pair the TV again")
        _encrypted(_encrypted_keys(host, token, keys))
        return

    def press(tv: SamsungTVWS) -> None:
        for key in keys:
            tv.send_key(key)

    _tizen_call(host, token, press)


def launch_app(host: str, protocol: str, token: str | None, app: str) -> None:
    if protocol != "tizen":
        raise TvUnsupported("only 2016 and newer TVs can launch apps")
    _tizen_call(host, token, lambda tv: tv.run_app(APP_IDS[app]))


def wake(mac: str) -> None:
    """Turn the TV on with a Wake-on-LAN packet (the TV must allow it)."""
    target = bytes.fromhex(mac.replace(":", "").replace("-", ""))
    if len(target) != 6:
        raise TvError("not a MAC address")
    packet = b"\xff" * 6 + target * 16
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
            sock.sendto(packet, ("255.255.255.255", 9))
    except OSError as error:
        raise TvError(
            f"could not send the wake-up packet: {type(error).__name__}"
        ) from None


def is_on(host: str, protocol: str) -> bool:
    """Whether the TV is on. 2016+ TVs report standby at :8001/api/v2/;
    older ones only answer on port 55000 (2010-2013) or 8000 (2014-2015)
    while they are on."""
    if protocol in ("legacy", "encrypted"):
        port = 55000 if protocol == "legacy" else 8000
        try:
            with socket.create_connection((host, port), timeout=PROBE_SECONDS):
                return True
        except OSError:
            return False
    try:
        response = requests.get(f"http://{host}:8001/api/v2/", timeout=PROBE_SECONDS)
        info = response.json()
    except (requests.RequestException, ValueError):
        return False
    device = info.get("device") if isinstance(info, dict) else None
    power = device.get("PowerState") if isinstance(device, dict) else None
    return power in (None, "on")
