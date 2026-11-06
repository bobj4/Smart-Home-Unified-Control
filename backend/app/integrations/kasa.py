"""TP-Link Kasa plugs, power strips, switches, dimmers and bulbs, on the home
network. Two ways in, tried in turn:

- the original protocol (TCP 9999, JSON lightly scrambled with TP-Link's
  rolling XOR): older devices and firmware, no login;
- KLAP (HTTP port 80, AES): newer firmware. It needs the TP-Link (Kasa app)
  account's email and password, from which a key is derived; they are not
  sent to the device. Both versions of KLAP's key are tried.

Both carry the same JSON commands ("system", "smartlife.iot..."). Devices
that only speak TP-Link's newer "SMART" API (Tapo, some new Kasa models) are
reported as not supported. Tests replace these functions.
"""

import hashlib
import json
import secrets
import socket
import struct
from typing import Any

import requests
from cryptography.hazmat.primitives import padding
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

PORT = 9999
TIMEOUT_SECONDS = 5
# The accounts devices accept before an owner signs in (TP-Link's defaults).
DEFAULT_LOGINS = [("", ""), ("kasa@tp-link.net", "kasaSetup")]

BULB = "smartlife.iot.smartbulb.lightingservice"
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
    """Send one command, by the original protocol or else KLAP."""
    try:
        return _xor_request(host, body)
    except KasaError:
        pass
    logins = ([login] if login else []) + DEFAULT_LOGINS
    return _Klap(host, logins).request(body)


# ------------------------------------------------------------ devices


def _check(answer: dict[str, Any]) -> dict[str, Any]:
    for module in answer.values():
        for result in (module or {}).values():
            if isinstance(result, dict) and result.get("err_code", 0) != 0:
                raise KasaError(f"the device refused: {result.get('err_msg', 'error')}")
    return answer


def devices(host: str, login: tuple[str, str] | None = None) -> list[dict[str, Any]]:
    """What is at an address: one entry per plug, outlet, switch or bulb."""
    info = (
        request(host, {"system": {"get_sysinfo": {}}}, login)
        .get("system", {})
        .get("get_sysinfo")
    )
    if not info:
        raise KasaError(
            "not a Kasa device (or one that needs the newer TP-Link app API)"
        )
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
                "on": bool(light.get("on_off")),
                "brightness": light.get("brightness"),
            }
        ]
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
        }
    ]


def body_for(
    command: str, state: dict[str, Any], bulb: bool, child: str | None
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
            light.update({"on_off": 1, "color_temp": int(state["color_temp"])})
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


def send(host: str, body: dict[str, Any], login: tuple[str, str] | None = None) -> None:
    _check(request(host, body, login))
