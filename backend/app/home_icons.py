"""A home's icon, shown at the top right: one of the built-in icons (drawn by
web/js/home-icons.js), or a small picture of one's own.

A picture comes as a data: URL (PNG, JPEG or WebP; the page shrinks it to
128 pixels first) and is checked here: its type, that the bytes really are
that kind of picture, and its size.
"""

import base64
import binascii
import re

ICONS = (
    "house",
    "cabin",
    "apartment",
    "office",
    "beach",
    "mountain",
    "farm",
    "boat",
)
MAX_BYTES = 96 * 1024
_DATA_URL = re.compile(r"^data:image/(png|jpeg|webp);base64,([A-Za-z0-9+/]+={0,2})$")
_MAGIC = {
    "png": (b"\x89PNG\r\n\x1a\n",),
    "jpeg": (b"\xff\xd8\xff",),
    "webp": (b"RIFF",),
}


class IconError(ValueError):
    """Not a picture this app takes."""


def check_picture(data_url: str) -> str:
    """The data URL as given if it is a small PNG, JPEG or WebP picture."""
    match = _DATA_URL.match(data_url)
    if match is None:
        raise IconError("choose a PNG, JPEG or WebP picture")
    kind, encoded = match.groups()
    try:
        raw = base64.b64decode(encoded, validate=True)
    except (binascii.Error, ValueError):
        raise IconError("that picture could not be read") from None
    if len(raw) > MAX_BYTES:
        raise IconError("that picture is too big (at most 96 KB)")
    if not raw.startswith(_MAGIC[kind]) or (kind == "webp" and raw[8:12] != b"WEBP"):
        raise IconError("that file is not the picture it says it is")
    return data_url
