"""A home's SmartThings link, for Samsung TV inputs by name. Optional: without
it the remote keeps its fixed inputs (TV, HDMI 1-4, USB) sent as keys."""

import json
from typing import Any

from sqlalchemy.orm import Session

from app import credentials
from app.integrations import smartthings
from app.models import Device
from app.vault import VaultError

CREDENTIAL = "samsung_tv:smartthings"


class SourcesUnavailable(Exception):
    def __init__(self, status_code: int, reason: str) -> None:
        self.status_code = status_code
        self.reason = reason


def _guard(action: Any) -> Any:
    try:
        return action()
    except smartthings.SmartThingsDenied:
        raise SourcesUnavailable(
            409,
            "SmartThings refused the token: add a new one in Settings > Integrations",
        ) from None
    except smartthings.SmartThingsError as error:
        raise SourcesUnavailable(502, str(error)) from None


def _token(db: Session, home_id: str) -> str:
    try:
        saved = credentials.load(db, home_id, CREDENTIAL)
    except VaultError as error:
        raise SourcesUnavailable(409, str(error)) from None
    if not saved or not saved.get("token"):
        raise SourcesUnavailable(
            409, "connect SmartThings first (Settings > Integrations)"
        )
    return str(saved["token"])


def connected(db: Session, home_id: str) -> bool:
    return credentials.label(db, home_id, CREDENTIAL) is not None


def connect(db: Session, home_id: str, token: str) -> list[dict[str, str]]:
    """Check the token by listing the TVs, then save it. Returns the TVs."""
    found = _guard(lambda: smartthings.tvs(token))
    try:
        credentials.save(db, home_id, CREDENTIAL, "SmartThings", {"token": token})
    except VaultError as error:
        raise SourcesUnavailable(409, str(error)) from None
    return list(found)


def disconnect(db: Session, home_id: str) -> None:
    credentials.remove(db, home_id, CREDENTIAL)


def smartthings_tvs(db: Session, home_id: str) -> list[dict[str, str]]:
    token = _token(db, home_id)
    return list(_guard(lambda: smartthings.tvs(token)))


def linked_id(device: Device) -> str | None:
    value = json.loads(device.capabilities or "{}").get("smartthings_id")
    return str(value) if value else None


def link(db: Session, device: Device, smartthings_id: str | None) -> None:
    """Which SmartThings device this TV is (None = not linked)."""
    data = json.loads(device.capabilities or "{}")
    data["smartthings_id"] = smartthings_id
    device.capabilities = json.dumps(data)
    db.commit()


def tv_sources(db: Session, device: Device) -> dict[str, Any]:
    st_id = linked_id(device)
    if not st_id:
        raise SourcesUnavailable(409, "link this TV to SmartThings first")
    token = _token(db, device.home_id)
    return dict(_guard(lambda: smartthings.sources(token, st_id)))


def set_tv_source(db: Session, device: Device, source: str) -> None:
    st_id = linked_id(device)
    if not st_id:
        raise SourcesUnavailable(409, "link this TV to SmartThings first")
    token = _token(db, device.home_id)
    _guard(lambda: smartthings.set_source(token, st_id, source))
