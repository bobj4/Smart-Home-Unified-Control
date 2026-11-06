"""A home's TP-Link Kasa devices: adding by address (a power strip adds one
device per outlet), the optional TP-Link login for newer firmware, commands
and the state refresh. Network calls go through app.integrations.kasa."""

import json
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import credentials
from app.features import integration_enabled
from app.integrations import kasa
from app.models import Device, utcnow
from app.vault import VaultError

INTEGRATION = "kasa"


class KasaUnavailable(Exception):
    def __init__(self, status_code: int, reason: str) -> None:
        self.status_code = status_code
        self.reason = reason


def _guard(action: Any) -> Any:
    try:
        return action()
    except kasa.KasaLogin as error:
        raise KasaUnavailable(
            409, f"{error}: add it in Settings > Integrations > Kasa"
        ) from None
    except kasa.KasaError as error:
        raise KasaUnavailable(502, str(error)) from None


def login(db: Session, home_id: str) -> tuple[str, str] | None:
    try:
        saved = credentials.load(db, home_id, INTEGRATION)
    except VaultError as error:
        raise KasaUnavailable(409, str(error)) from None
    return (str(saved["email"]), str(saved["password"])) if saved else None


def save_login(db: Session, home_id: str, email: str, password: str) -> None:
    try:
        credentials.save(
            db, home_id, INTEGRATION, email, {"email": email, "password": password}
        )
    except VaultError as error:
        raise KasaUnavailable(409, str(error)) from None


def remove_login(db: Session, home_id: str) -> None:
    credentials.remove(db, home_id, INTEGRATION)


def login_label(db: Session, home_id: str) -> str | None:
    return credentials.label(db, home_id, INTEGRATION)


def list_devices(db: Session, home_id: str) -> list[Device]:
    return list(
        db.scalars(
            select(Device)
            .where(Device.home_id == home_id, Device.integration == INTEGRATION)
            .order_by(Device.name)
        )
    )


def device_out(device: Device) -> dict[str, Any]:
    caps = json.loads(device.capabilities or "{}")
    return {
        "device_id": device.id,
        "name": device.name,
        "host": caps.get("host"),
        "model": caps.get("model"),
        "kind": device.type,
    }


def add_host(db: Session, home_id: str, host: str, room: str | None) -> list[Device]:
    """Everything at that address: one device, or one per outlet."""
    if not integration_enabled(db, home_id, INTEGRATION):
        raise KasaUnavailable(409, "the Kasa integration is turned off")
    if any(
        json.loads(d.capabilities or "{}").get("host") == host
        for d in list_devices(db, home_id)
    ):
        raise KasaUnavailable(409, "that address is already added")
    who = login(db, home_id)
    found = _guard(lambda: kasa.devices(host, who))
    added = []
    for info in found:
        device = Device(
            home_id=home_id,
            integration=INTEGRATION,
            external_id=info["id"],
            type=info["kind"],
            name=str(info["name"])[:100],
            room=room,
            capabilities=json.dumps(
                {
                    "host": host,
                    "model": info["model"],
                    "bulb": bool(info.get("bulb")),
                    "child": info.get("child"),
                    "dimming": bool(info.get("dimming")),
                    "white": bool(info.get("white")),
                    "color": bool(info.get("color")),
                }
            ),
            state="{}",
            online=True,
        )
        _apply(device, info)
        db.add(device)
        added.append(device)
    db.commit()
    return added


def _apply(device: Device, info: dict[str, Any]) -> bool:
    state = json.loads(device.state or "{}")
    new = {**state, "on": bool(info["on"])}
    if device.type == "light" and info.get("brightness") is not None:
        new["brightness"] = int(info["brightness"])
    changed = new != state
    device.state = json.dumps(new)
    if changed:
        device.last_updated = utcnow()
    return changed


def remove_host(db: Session, device: Device) -> None:
    """Remove the device and, for a strip, its other outlets."""
    host = json.loads(device.capabilities or "{}").get("host")
    for other in list_devices(db, device.home_id):
        if json.loads(other.capabilities or "{}").get("host") == host:
            db.delete(other)
    db.commit()


def send_command(
    db: Session, device: Device, command: str, state: dict[str, Any]
) -> None:
    caps = json.loads(device.capabilities or "{}")
    body = _guard(
        lambda: kasa.body_for(command, state, bool(caps.get("bulb")), caps.get("child"))
    )
    who = login(db, device.home_id)
    _guard(lambda: kasa.send(str(caps["host"]), body, who))


def refresh(db: Session, home_id: str) -> int:
    """Read each address once; returns how many devices changed."""
    if not integration_enabled(db, home_id, INTEGRATION):
        return 0
    who = login(db, home_id)
    by_host: dict[str, list[Device]] = {}
    for device in list_devices(db, home_id):
        by_host.setdefault(
            json.loads(device.capabilities or "{}").get("host"), []
        ).append(device)
    changed = 0
    for host, group in by_host.items():
        try:
            found = {i["id"]: i for i in kasa.devices(str(host), who)}
        except kasa.KasaError:
            found = {}
        for device in group:
            info = found.get(str(device.external_id))
            online = info is not None
            if device.online != online:
                device.online = online
                device.last_updated = utcnow()
                changed += 1
            if info is not None and _apply(device, info):
                changed += 1
    db.commit()
    return changed
