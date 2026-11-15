"""Phone and desktop notifications (Web Push), with no extra library: the
browser's push service gets the message encrypted for that browser alone
(RFC 8291, aes128gcm) and signed by this server (VAPID, RFC 8292).

The server's VAPID key is made once and kept encrypted with SECRETS_KEY
(the vault); without SECRETS_KEY there are no push notifications (email
alerts still work). Tests replace `post`.
"""

import base64
import json
import os
import struct
import time
from typing import Any
from urllib.parse import urlsplit

import requests
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

TIMEOUT_SECONDS = 10
RECORD_SIZE = 4096
CONTACT = "mailto:smarthome@localhost"


class PushGone(Exception):
    """The subscription no longer exists (the browser unsubscribed)."""


class PushError(Exception):
    """The push service refused or could not be reached."""


def b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def unb64url(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def new_key() -> str:
    """A new VAPID private key (PEM text)."""
    key = ec.generate_private_key(ec.SECP256R1())
    return key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ).decode()


def _private(pem: str) -> ec.EllipticCurvePrivateKey:
    key = serialization.load_pem_private_key(pem.encode(), password=None)
    if not isinstance(key, ec.EllipticCurvePrivateKey):
        raise PushError("the saved push key is not an EC key")
    return key


def _raw_public(key: ec.EllipticCurvePublicKey) -> bytes:
    return key.public_bytes(
        serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint
    )


def public_key(pem: str) -> str:
    """The key browsers subscribe with (applicationServerKey)."""
    return b64url(_raw_public(_private(pem).public_key()))


def _hkdf(salt: bytes, ikm: bytes, info: bytes, length: int) -> bytes:
    return HKDF(hashes.SHA256(), length, salt, info).derive(ikm)


def encrypt(
    payload: bytes,
    browser_key: str,
    auth: str,
    salt: bytes | None = None,
    ours: ec.EllipticCurvePrivateKey | None = None,
) -> bytes:
    """The message body for one browser (RFC 8291). salt and ours (this
    message's own key) are only given by the RFC's worked example test."""
    ua_public = unb64url(browser_key)
    ua_key = ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), ua_public)
    ours = ours or ec.generate_private_key(ec.SECP256R1())
    as_public = _raw_public(ours.public_key())
    shared = ours.exchange(ec.ECDH(), ua_key)
    ikm = _hkdf(
        unb64url(auth), shared, b"WebPush: info\x00" + ua_public + as_public, 32
    )
    salt = salt or os.urandom(16)
    cek = _hkdf(salt, ikm, b"Content-Encoding: aes128gcm\x00", 16)
    nonce = _hkdf(salt, ikm, b"Content-Encoding: nonce\x00", 12)
    sealed = AESGCM(cek).encrypt(nonce, payload + b"\x02", None)
    header = salt + struct.pack(">IB", RECORD_SIZE, len(as_public)) + as_public
    return header + sealed


def vapid_header(pem: str, endpoint: str, now: float | None = None) -> str:
    """Authorization: this server signs for the push service's origin."""
    parts = urlsplit(endpoint)
    claims = {
        "aud": f"{parts.scheme}://{parts.netloc}",
        "exp": int((now or time.time()) + 12 * 3600),
        "sub": CONTACT,
    }
    head = b64url(json.dumps({"typ": "JWT", "alg": "ES256"}).encode())
    body = b64url(json.dumps(claims, separators=(",", ":")).encode())
    key = _private(pem)
    der = key.sign(f"{head}.{body}".encode(), ec.ECDSA(hashes.SHA256()))
    r, s = decode_dss_signature(der)
    signature = b64url(r.to_bytes(32, "big") + s.to_bytes(32, "big"))
    return f"vapid t={head}.{body}.{signature}, k={public_key(pem)}"


def post(url: str, data: bytes, headers: dict[str, str]) -> int:
    try:
        return requests.post(
            url, data=data, headers=headers, timeout=TIMEOUT_SECONDS
        ).status_code
    except requests.RequestException as error:
        raise PushError(
            f"could not reach the push service: {type(error).__name__}"
        ) from None


def send(pem: str, subscription: dict[str, str], message: dict[str, Any]) -> None:
    """Send one notification ({"title", "body", "url", "tag"})."""
    endpoint = subscription["endpoint"]
    if not endpoint.startswith("https://"):
        raise PushError("not a push service address")
    data = encrypt(
        json.dumps(message).encode(), subscription["p256dh"], subscription["auth"]
    )
    status = post(
        endpoint,
        data,
        {
            "Content-Encoding": "aes128gcm",
            "Content-Type": "application/octet-stream",
            "TTL": "3600",
            "Urgency": "high",
            "Authorization": vapid_header(pem, endpoint),
        },
    )
    if status in (404, 410):
        raise PushGone("the browser no longer takes these")
    if status >= 400:
        raise PushError(f"the push service answered {status}")
