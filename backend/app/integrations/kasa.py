"""TP-Link Kasa plugs, power strips, switches, dimmers and bulbs, on the home
network. Two ways in, tried in turn:

- the original protocol (TCP 9999, JSON lightly scrambled with TP-Link's
  rolling XOR): older devices and firmware, no login;
- KLAP (HTTP port 80, AES): newer firmware. It needs the TP-Link (Kasa app)
  account's email and password, from which a key is derived; they are not
  sent to the device. Both versions of KLAP's key are tried.

Older devices take JSON commands ("system", "smartlife.iot..."); newer
Kasa and Tapo models take TP-Link's "SMART" API ({"method": ...}) over KLAP.
Both are handled; a device of either kind is described the same way (see
devices()). Devices that need TP-Link's other newer transport (an RSA
handshake, some early Tapo firmware) are reported as not supported.
Tests replace these functions.
"""

import base64
import hashlib
import json
import secrets
import socket
import struct
import time
import uuid
from typing import Any

import requests
from cryptography.hazmat.primitives import padding
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

PORT = 9999
TIMEOUT_SECONDS = 5
# The accounts devices accept before an owner signs in (TP-Link's defaults).
DEFAULT_LOGINS = [
    ("", ""),
    ("kasa@tp-link.net", "kasaSetup"),
    ("test@tp-link.net", "test"),
]
# Bulbs' white range in kelvin by model (the warmest the app offers is 2000).
CT_RANGES = {
    "KL120": (2700, 5000),
    "LB120": (2700, 6500),
    "KL125": (2500, 6500),
    "KL135": (2500, 6500),
    "KL130": (2500, 9000),
    "LB130": (2500, 9000),
    "LB230": (2500, 9000),
    "KL430": (2500, 9000),
    "KL400": (2500, 9000),
}
DEFAULT_CT_RANGE = (2500, 6500)

BULB = "smartlife.iot.smartbulb.lightingservice"
TERMINAL = base64.b64encode(uuid.uuid4().bytes).decode()
DIMMER = "smartlife.iot.dimmer"


class KasaError(Exception):
    """The device could not be reached or refused."""


class KasaLogin(KasaError):
    """The device wants a TP-Link login (KLAP) and the one given is wrong."""


# ------------------------------------------------------------ original (XOR)


def _scramble(text: bytes) -> bytes:
    key, out = 171, bytearray()
    for byte in text:
        key ^= byte
        out.append(key)
    return bytes(out)


def _unscramble(data: bytes) -> bytes:
    key, out = 171, bytearray()
    for byte in data:
        out.append(key ^ byte)
        key = byte
    return bytes(out)


def _xor_request(host: str, body: dict[str, Any]) -> dict[str, Any]:
    payload = _scramble(json.dumps(body).encode())
    try:
        with socket.create_connection((host, PORT), timeout=TIMEOUT_SECONDS) as sock:
            sock.sendall(struct.pack(">I", len(payload)) + payload)
            header = _read(sock, 4)
            data = _read(sock, struct.unpack(">I", header)[0])
    except OSError as error:
        raise KasaError(
            f"could not reach the device: {error.strerror or type(error).__name__}"
        ) from None
    return dict(json.loads(_unscramble(data)))


def _read(sock: socket.socket, size: int) -> bytes:
    chunks, left = [], size
    while left:
        chunk = sock.recv(min(left, 65536))
        if not chunk:
            raise OSError("closed early")
        chunks.append(chunk)
        left -= len(chunk)
    return b"".join(chunks)


# ------------------------------------------------------------ KLAP


def _sha256(data: bytes) -> bytes:
    return hashlib.sha256(data).digest()


def _auth_hashes(email: str, password: str) -> list[tuple[int, bytes]]:
    """KLAP's key from a login, both versions: v2 (sha) and v1 (md5)."""

    def sha1(data: bytes) -> bytes:
        return hashlib.sha1(data, usedforsecurity=False).digest()

    def md5(data: bytes) -> bytes:
        return hashlib.md5(data, usedforsecurity=False).digest()

    user, secret = email.encode(), password.encode()
    return [(2, _sha256(sha1(user) + sha1(secret))), (1, md5(md5(user) + md5(secret)))]


class _Klap:
    def __init__(self, host: str, logins: list[tuple[str, str]]) -> None:
        self.host = host
        self.http = requests.Session()
        local = secrets.token_bytes(16)
        try:
            first = self.http.post(
                f"http://{host}/app/handshake1", data=local, timeout=TIMEOUT_SECONDS
            )
        except requests.RequestException as error:
            raise KasaError(
                f"could not reach the device: {type(error).__name__}"
            ) from None
        if first.status_code != 200 or len(first.content) < 48:
            raise KasaError("the device does not answer KLAP")
        remote, server_hash = first.content[:16], first.content[16:48]
        for email, password in logins:
            for version, auth in _auth_hashes(email, password):
                expected = (
                    _sha256(local + remote + auth)
                    if version == 2
                    else _sha256(local + auth)
                )
                if expected == server_hash:
                    self._finish(local, remote, auth, version)
                    return
        raise KasaLogin(
            "the device wants the TP-Link (Kasa app) account it was set up with"
        )

    def _finish(self, local: bytes, remote: bytes, auth: bytes, version: int) -> None:
        proof = (
            _sha256(remote + local + auth) if version == 2 else _sha256(remote + auth)
        )
        r = self.http.post(
            f"http://{self.host}/app/handshake2", data=proof, timeout=TIMEOUT_SECONDS
        )
        if r.status_code != 200:
            raise KasaLogin("the device refused the login")
        seeds = local + remote + auth
        self.key = _sha256(b"lsk" + seeds)[:16]
        iv = _sha256(b"iv" + seeds)
        self.iv_base, self.seq = iv[:12], struct.unpack(">i", iv[-4:])[0]
        self.sig = _sha256(b"ldk" + seeds)[:28]

    def _iv(self) -> bytes:
        return self.iv_base + struct.pack(">i", self.seq)

    def request(self, body: dict[str, Any]) -> dict[str, Any]:
        self.seq += 1
        padder = padding.PKCS7(128).padder()
        plain = padder.update(json.dumps(body).encode()) + padder.finalize()
        encryptor = Cipher(algorithms.AES(self.key), modes.CBC(self._iv())).encryptor()
        sealed = encryptor.update(plain) + encryptor.finalize()
        signature = _sha256(self.sig + struct.pack(">i", self.seq) + sealed)
        try:
            r = self.http.post(
                f"http://{self.host}/app/request",
                params={"seq": self.seq},
                data=signature + sealed,
                timeout=TIMEOUT_SECONDS,
            )
        except requests.RequestException as error:
            raise KasaError(
                f"could not reach the device: {type(error).__name__}"
            ) from None
        if r.status_code != 200:
            raise KasaError(f"the device answered {r.status_code}")
        decryptor = Cipher(algorithms.AES(self.key), modes.CBC(self._iv())).decryptor()
        unpadder = padding.PKCS7(128).unpadder()
        clear = decryptor.update(r.content[32:]) + decryptor.finalize()
        return dict(json.loads(unpadder.update(clear) + unpadder.finalize()))


def request(
    host: str, body: dict[str, Any], login: tuple[str, str] | None = None
) -> dict[str, Any]:
    """Send one command, by the original protocol or else KLAP. A SMART
    command ({"method": ...}) only goes by KLAP."""
    if "method" not in body:
        try:
            return _xor_request(host, body)
        except KasaError:
            pass
    logins = ([login] if login else []) + DEFAULT_LOGINS
    return _Klap(host, logins).request(body)


def smart(
    host: str,
    method: str,
    params: dict[str, Any] | None = None,
    login: tuple[str, str] | None = None,
) -> dict[str, Any]:
    """One SMART API call; its result."""
    body: dict[str, Any] = {
        "method": method,
        "request_time_milis": round(time.time() * 1000),
        "terminal_uuid": TERMINAL,
    }
    if params is not None:
        body["params"] = params
    answer = request(host, body, login)
    code = answer.get("error_code", 0)
    if code == -1501:
        raise KasaLogin(
            "the device wants the TP-Link (Kasa or Tapo app) account it was set up with"
        )
    if code != 0:
        raise KasaError(f"the device refused (error {code})")
    result = answer.get("result")
    return dict(result) if isinstance(result, dict) else {}


# ------------------------------------------------------------ devices


def _check(answer: dict[str, Any]) -> dict[str, Any]:
    for module in answer.values():
        for result in (module or {}).values():
            if isinstance(result, dict) and result.get("err_code", 0) != 0:
                raise KasaError(f"the device refused: {result.get('err_msg', 'error')}")
    return answer


def devices(host: str, login: tuple[str, str] | None = None) -> list[dict[str, Any]]:
    """What is at an address: one entry per plug, outlet, switch or bulb."""
    answer = request(host, {"system": {"get_sysinfo": {}}}, login)
    info = (answer.get("system") or {}).get("get_sysinfo")
    if not info:
        return _smart_devices(host, login)  # a newer model: the SMART API
    kind_text = str(info.get("mic_type") or info.get("type") or "").lower()
    model = str(info.get("model") or "Kasa")
    if "bulb" in kind_text:
        light = info.get("light_state") or {}
        return [
            {
                "id": host,
                "name": info.get("alias") or model,
                "kind": "light",
                "model": model,
                "bulb": True,
                "dimming": bool(info.get("is_dimmable")),
                "white": bool(info.get("is_variable_color_temp")),
                "color": bool(info.get("is_color")),
                "ct_range": list(ct_range(model)),
                "on": bool(light.get("on_off")),
                "brightness": light.get("brightness"),
            }
        ]
    metered = "ENE" in str(info.get("feature") or "")  # power monitoring
    children = info.get("children") or []
    if children:  # a power strip: one device per outlet
        return [
            {
                "id": f"{host}/{child['id']}",
                "name": child.get("alias") or f"{model} outlet",
                "kind": "plug",
                "model": model,
                "on": bool(child.get("state")),
                "child": child["id"],
                "energy": metered,
            }
            for child in children
        ]
    dimmer = "brightness" in info
    return [
        {
            "id": host,
            "name": info.get("alias") or model,
            "kind": "light" if dimmer else "plug",
            "model": model,
            "dimming": dimmer,
            "on": bool(info.get("relay_state")),
            "brightness": info.get("brightness"),
            "energy": metered,
        }
    ]


def ct_range(model: str) -> tuple[int, int]:
    """A bulb's white range in kelvin, from its model."""
    for prefix, found in CT_RANGES.items():
        if model.upper().startswith(prefix):
            return found
    return DEFAULT_CT_RANGE


def _kelvin(state: dict[str, Any], limits: list[int] | tuple[int, int] | None) -> int:
    low, high = limits or DEFAULT_CT_RANGE
    return min(int(high), max(int(low), int(state["color_temp"])))


def _name(raw: Any, fallback: str) -> str:
    """A SMART nickname (base64 text)."""
    try:
        text = base64.b64decode(str(raw)).decode()
    except (ValueError, UnicodeDecodeError):
        text = ""
    return (text or fallback)[:100]


def _smart_devices(host: str, login: tuple[str, str] | None) -> list[dict[str, Any]]:
    try:
        info = smart(host, "get_device_info", login=login)
    except KasaLogin:
        raise
    except KasaError:
        raise KasaError(
            "not a Kasa device (or one that needs a TP-Link transport not supported)"
        ) from None
    model = str(info.get("model") or "Kasa")
    kind_text = str(info.get("type") or "").upper()
    if "HUB" in kind_text or "CAMERA" in kind_text:
        raise KasaError("TP-Link hubs and cameras are not supported")
    if info.get("device_on") is None:  # a power strip: one device per outlet
        children = smart(host, "get_child_device_list", login=login)
        return [
            {
                "id": f"{host}/{child['device_id']}",
                "name": _name(child.get("nickname"), f"{model} outlet"),
                "kind": "plug",
                "model": model,
                "smart": True,
                "on": bool(child.get("device_on")),
                "child": str(child["device_id"]),
            }
            for child in children.get("child_device_list") or []
            if child.get("device_id")
        ]
    bulb = "BULB" in kind_text
    dimmer = "brightness" in info
    limits = info.get("color_temp_range")
    try:  # power monitoring: only models that have it answer
        smart(host, "get_energy_usage", login=login)
        metered = True
    except KasaLogin:
        raise
    except KasaError:
        metered = False
    entry: dict[str, Any] = {
        "id": host,
        "name": _name(info.get("nickname"), model),
        "kind": "light" if bulb or dimmer else "plug",
        "model": model,
        "smart": True,
        "bulb": bulb,
        "dimming": dimmer,
        "on": bool(info.get("device_on")),
        "brightness": info.get("brightness"),
        "energy": metered,
    }
    if bulb:
        entry["white"] = "color_temp" in info
        entry["color"] = "hue" in info
        entry["ct_range"] = (
            list(limits)
            if isinstance(limits, list) and len(limits) == 2
            else list(ct_range(model))
        )
    return [entry]


def smart_params(command: str, state: dict[str, Any], ct: Any = None) -> dict[str, Any]:
    """set_device_info's params for one of the app's commands (SMART API)."""
    if command in ("turn_on", "turn_off"):
        return {"device_on": command == "turn_on"}
    if command == "set_brightness":
        level = int(state["brightness"])
        if level == 0:
            return {"device_on": False}
        return {"device_on": True, "brightness": max(1, level)}
    if command == "set_color_temp":
        return {"device_on": True, "color_temp": _kelvin(state, ct)}
    if command == "set_color":
        rgb = [int(str(state["color"])[i : i + 2], 16) for i in (1, 3, 5)]
        hue, sat, val = _hsv(*rgb)
        return {
            "device_on": True,
            "hue": hue,
            "saturation": sat,
            "brightness": max(1, val),
            "color_temp": 0,
        }
    raise KasaError("this device cannot do that")


def send_smart(
    host: str,
    params: dict[str, Any],
    child: str | None,
    login: tuple[str, str] | None = None,
) -> None:
    if child:
        smart(
            host,
            "control_child",
            {
                "device_id": child,
                "requestData": {"method": "set_device_info", "params": params},
            },
            login,
        )
    else:
        smart(host, "set_device_info", params, login)


def body_for(
    command: str,
    state: dict[str, Any],
    bulb: bool,
    child: str | None,
    ct: Any = None,
) -> dict[str, Any]:
    """The JSON for one of the app's light or plug commands."""
    if bulb:
        light: dict[str, Any] = {"ignore_default": 1, "transition_period": 300}
        if command in ("turn_on", "turn_off"):
            light["on_off"] = 1 if command == "turn_on" else 0
        elif command == "set_brightness":
            level = int(state["brightness"])
            light.update({"on_off": 1 if level else 0, "brightness": max(1, level)})
        elif command == "set_color_temp":
            light.update({"on_off": 1, "color_temp": _kelvin(state, ct)})
        elif command == "set_color":
            rgb = [int(str(state["color"])[i : i + 2], 16) for i in (1, 3, 5)]
            hue, sat, val = _hsv(*rgb)
            light.update(
                {
                    "on_off": 1,
                    "hue": hue,
                    "saturation": sat,
                    "brightness": max(1, val),
                    "color_temp": 0,
                }
            )
        else:
            raise KasaError("unsupported command")
        return {BULB: {"transition_light_state": light}}
    if command in ("turn_on", "turn_off"):
        body: dict[str, Any] = {
            "system": {"set_relay_state": {"state": 1 if command == "turn_on" else 0}}
        }
        if child:
            body["context"] = {"child_ids": [child]}
        return body
    if command == "set_brightness":
        level = int(state["brightness"])
        if level == 0:
            return {"system": {"set_relay_state": {"state": 0}}}
        return {
            DIMMER: {"set_brightness": {"brightness": level}},
            "system": {"set_relay_state": {"state": 1}},
        }
    raise KasaError("this device cannot do that")


def _hsv(r: int, g: int, b: int) -> tuple[int, int, int]:
    high, low = max(r, g, b), min(r, g, b)
    delta = high - low
    if delta == 0:
        hue = 0.0
    elif high == r:
        hue = 60 * (((g - b) / delta) % 6)
    elif high == g:
        hue = 60 * ((b - r) / delta + 2)
    else:
        hue = 60 * ((r - g) / delta + 4)
    sat = 0 if high == 0 else delta / high
    return round(hue), round(sat * 100), round(high / 255 * 100)


DAY_SECONDS = 600  # today's total is read at most this often
_today: dict[tuple[str, str | None], tuple[float, float | None]] = {}


def energy(
    host: str,
    login: tuple[str, str] | None = None,
    child: str | None = None,
    is_smart: bool = False,
) -> dict[str, float | None]:
    """A metered plug's power now (W) and use today (kWh)."""
    if is_smart:
        usage = smart(host, "get_energy_usage", login=login)
        power = usage.get("current_power")
        today = usage.get("today_energy")
        return {
            "power_w": round(float(power) / 1000, 1) if power is not None else None,
            "today_kwh": round(float(today) / 1000, 3) if today is not None else None,
        }
    context = {"context": {"child_ids": [child]}} if child else {}
    now = _check(request(host, {"emeter": {"get_realtime": {}}, **context}, login))
    real = (now.get("emeter") or {}).get("get_realtime") or {}
    if "power_mw" in real:
        power_w: float | None = float(real["power_mw"]) / 1000
    else:
        power_w = float(real["power"]) if "power" in real else None
    key = (host, child)
    saved = _today.get(key)
    if saved is not None and time.monotonic() - saved[0] < DAY_SECONDS:
        today_kwh = saved[1]
    else:
        today_kwh = _today_kwh(host, login, context)
        _today[key] = (time.monotonic(), today_kwh)
    return {
        "power_w": round(power_w, 1) if power_w is not None else None,
        "today_kwh": today_kwh,
    }


def _today_kwh(
    host: str, login: tuple[str, str] | None, context: dict[str, Any]
) -> float | None:
    day = time.localtime()
    asked = {"get_daystat": {"year": day.tm_year, "month": day.tm_mon}}
    try:
        stats = _check(request(host, {"emeter": asked, **context}, login))
    except KasaError:
        return None
    for entry in (stats.get("emeter") or {}).get("get_daystat", {}).get(
        "day_list"
    ) or []:
        if entry.get("day") == day.tm_mday:
            if "energy_wh" in entry:
                return round(float(entry["energy_wh"]) / 1000, 3)
            return round(float(entry.get("energy", 0)), 3)
    return 0.0


def send(host: str, body: dict[str, Any], login: tuple[str, str] | None = None) -> None:
    _check(request(host, body, login))
