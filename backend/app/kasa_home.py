"""A home's TP-Link Kasa devices: adding by address (a power strip adds one
device per outlet), the optional TP-Link login for newer firmware, commands
and the state refresh. Network calls go through app.integrations.kasa."""

import json
from functools import partial
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import credentials, probes
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
                    "smart": bool(info.get("smart")),
                    "ct_range": info.get("ct_range"),
                    "energy": bool(info.get("energy")),
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
    for key in ("power_w", "today_kwh"):  # a metered plug's readings
        if key in info:
            new[key] = info[key]
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
    who = login(db, device.home_id)
    host, child, ct = str(caps["host"]), caps.get("child"), caps.get("ct_range")
    if caps.get("smart"):  # a newer model: the SMART API
        params = _guard(lambda: kasa.smart_params(command, state, ct))
        _guard(lambda: kasa.send_smart(host, params, child, who))
        return
    if ct is None and caps.get("bulb"):
        ct = kasa.ct_range(str(caps.get("model") or ""))
    body = _guard(
        lambda: kasa.body_for(command, state, bool(caps.get("bulb")), child, ct)
    )
    _guard(lambda: kasa.send(host, body, who))


def _read_host(
    host: str, who: tuple[str, str] | None, metered: dict[str, dict[str, Any]]
) -> list[dict[str, Any]]:
    """Everything at the address, with readings from its metered plugs
    (metered: device id -> its capabilities)."""
    found = kasa.devices(host, who)
    for info in found:
        caps = metered.get(str(info["id"]))
        if not (info.get("energy") or (caps and caps.get("energy"))):
            continue
        try:
            info.update(
                kasa.energy(
                    host,
                    who,
                    info.get("child") if not info.get("smart") else None,
                    bool(info.get("smart")),
                )
            )
        except kasa.KasaError:
            pass  # the switch state still counts
    return found


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
    hosts = [h for h in by_host if probes.due(f"kasa:{h}")]
    caps = {
        str(d.external_id): json.loads(d.capabilities or "{}")
        for group in by_host.values()
        for d in group
    }
    answers = probes.gather(
        {str(h): partial(_read_host, str(h), who, caps) for h in hosts}
    )
    changed = 0
    for host in hosts:
        group = by_host[host]
        answer = answers[str(host)]
        if isinstance(answer, Exception) and not isinstance(answer, kasa.KasaError):
            raise answer
        ok = not isinstance(answer, Exception)
        probes.answered(f"kasa:{host}", ok)
        found = {i["id"]: i for i in answer} if ok else {}
        for device in group:
            info = found.get(str(device.external_id))
            online = info is not None
            known = json.loads(device.capabilities or "{}")
            if info is not None and info.get("energy") and not known.get("energy"):
                device.capabilities = json.dumps({**known, "energy": True})
            if device.online != online:
                device.online = online
                device.last_updated = utcnow()
                changed += 1
            if info is not None and _apply(device, info):
                changed += 1
    db.commit()
    return changed
