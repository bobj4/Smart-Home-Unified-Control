"""A person's own picture behind the dashboard (My account > Appearance):
upload one (JPEG, PNG or WebP, up to 3 MB), switch it on or off, remove it."""

import base64
import binascii
import hashlib
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from app.db_config import get_db
from app.dependencies import current_user, require_csrf
from app.models import User

router = APIRouter(prefix="/api/v1/account/background", tags=["account"])

MAX_BYTES = 3 * 1024 * 1024
# The file's first bytes decide its type, never the name or what the browser says.
SIGNATURES = {
    b"\xff\xd8\xff": "image/jpeg",
    b"\x89PNG\r\n\x1a\n": "image/png",
}


class BackgroundIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    image: str = Field(min_length=1, max_length=MAX_BYTES * 4 // 3 + 100)  # base64


class BackgroundSwitch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    on: bool


def image_type(data: bytes) -> str | None:
    for signature, kind in SIGNATURES.items():
        if data.startswith(signature):
            return kind
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return None


def background_out(db: Session, user: User) -> dict[str, Any]:
    """For the account: on/off, and a version that changes with the picture."""
    has = user.background_type is not None
    version = None
    if has:
        data = user.background_image or b""  # deferred: loaded here only
        version = hashlib.sha256(data).hexdigest()[:12]
    return {"on": bool(user.background_on) and has, "image": has, "version": version}


@router.get("")
def get_background(
    user: User = Depends(current_user), db: Session = Depends(get_db)
) -> Response:
    if user.background_type is None:
        raise HTTPException(404, "No background picture")
    return Response(
        user.background_image or b"",
        media_type=user.background_type,
        headers={
            "Cache-Control": "private, max-age=31536000",
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.put("", dependencies=[Depends(require_csrf)])
def put_background(
    body: BackgroundIn,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """A new picture (base64), switched on."""
    text = body.image.split(",", 1)[1] if body.image.startswith("data:") else body.image
    try:
        data = base64.b64decode(text, validate=True)
    except (binascii.Error, ValueError):
        raise HTTPException(422, "The picture could not be read") from None
    if len(data) > MAX_BYTES:
        raise HTTPException(413, "The picture is larger than 3 MB")
    kind = image_type(data)
    if kind is None:
        raise HTTPException(422, "Use a JPEG, PNG or WebP picture")
    user.background_image, user.background_type, user.background_on = data, kind, True
    db.commit()
    return background_out(db, user)


@router.put("/on", dependencies=[Depends(require_csrf)])
def switch_background(
    body: BackgroundSwitch,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    if body.on and user.background_type is None:
        raise HTTPException(409, "Choose a picture first")
    user.background_on = body.on
    db.commit()
    return background_out(db, user)


@router.delete("", dependencies=[Depends(require_csrf)])
def delete_background(
    user: User = Depends(current_user), db: Session = Depends(get_db)
) -> dict[str, Any]:
    user.background_image, user.background_type, user.background_on = None, None, False
    db.commit()
    return background_out(db, user)
