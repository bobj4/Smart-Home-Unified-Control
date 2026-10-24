"""A home's Samsung TVs: adding, pairing and sending remote commands.
Network calls go through app.integrations.samsung (replaced by fakes in tests)."""

import json
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import credentials
from app.features import integration_enabled
from app.integrations import samsung
from app.models import Device
from app.vault import VaultError

INTEGRATION = "samsung_tv"


class SamsungUnavailable(Exception):
    def __init__(self, status_code: int, reason: str) -> None:
        self.status_code = status_code
        self.reason = reason


def _credential_key(device: Device) -> str:
    return f"{INTEGRATION}:{device.id}"


def config(device: Device) -> dict[str, Any]:
    data = json.loads(device.capabilities or "{}")
    return {
        "protocol": data.get("protocol", "tizen"),
        "mac": data.get("mac"),
        "paired": bool(data.get("paired")),
    }


def tv_out(device: Device) -> dict[str, Any]:
    return {
        "device_id": device.id,
        "name": device.name,
        "host": device.external_id,
        **config(device),
    }


def list_tvs(db: Session, home_id: str) -> list[Device]:
    return list(
        db.scalars(
            select(Device)
            .where(Device.home_id == home_id, Device.integration == INTEGRATION)
            .order_by(Device.name)
        )
    )


def add_tv(
    db: Session,
    home_id: str,
    name: str,
    host: str,
    protocol: str,
    mac: str | None,
    room: str | None,
) -> Device:
    if not integration_enabled(db, home_id, INTEGRATION):
        raise SamsungUnavailable(409, "the Samsung TV integration is turned off")
    if any(d.external_id == host for d in list_tvs(db, home_id)):
        raise SamsungUnavailable(409, "a TV with that address is already added")
    device = Device(
        home_id=home_id,
        integration=INTEGRATION,
        external_id=host,
        type="tv",
        name=name,
        room=room,
        capabilities=json.dumps({"protocol": protocol, "mac": mac, "paired": False}),
        state="{}",
        online=False,
    )
    db.add(device)
    db.commit()
    return device


def _save_token(db: Session, device: Device, token: str) -> None:
    try:
        credentials.save(
            db,
            device.home_id,
            _credential_key(device),
            str(device.external_id),
            {"token": token},
        )
    except VaultError as error:
        raise SamsungUnavailable(409, str(error)) from None


def pair_tv(db: Session, device: Device) -> bool:
    """Connect so the TV shows its Allow prompt; keep the token (encrypted).
    For 2014-2015 TVs this only shows the PIN on the TV and returns True:
    finish with finish_pin_pairing."""
    if not integration_enabled(db, device.home_id, INTEGRATION):
        raise SamsungUnavailable(409, "the Samsung TV integration is turned off")
    settings = config(device)
    if settings["protocol"] == "encrypted":
        try:
            samsung.start_pin_pairing(str(device.external_id))
        except samsung.TvError as error:
            raise SamsungUnavailable(502, str(error)) from None
        return True
    try:
        token = samsung.pair(str(device.external_id), settings["protocol"])
    except samsung.TvDenied:
        raise SamsungUnavailable(
            409, "the TV refused: press Allow on the TV and try again"
        ) from None
    except samsung.TvError as error:
        raise SamsungUnavailable(502, str(error)) from None
    if token is not None:
        _save_token(db, device, token)
    device.capabilities = json.dumps({**settings, "paired": True})
    device.online = True
    db.commit()
    return False


def finish_pin_pairing(db: Session, device: Device, pin: str) -> None:
    """2014-2015 TVs: pair with the PIN the TV shows."""
    if not integration_enabled(db, device.home_id, INTEGRATION):
        raise SamsungUnavailable(409, "the Samsung TV integration is turned off")
    settings = config(device)
    if settings["protocol"] != "encrypted":
        raise SamsungUnavailable(409, "only 2014-2015 TVs pair with a PIN")
    try:
        token = samsung.finish_pin_pairing(str(device.external_id), pin)
    except samsung.TvDenied as error:
        raise SamsungUnavailable(409, str(error)) from None
    except samsung.TvError as error:
        raise SamsungUnavailable(502, str(error)) from None
    _save_token(db, device, token)
    device.capabilities = json.dumps({**settings, "paired": True})
    device.online = True
    db.commit()


def remove_tv(db: Session, device: Device) -> None:
    credentials.remove(db, device.home_id, _credential_key(device))
    db.delete(device)
    db.commit()


def send_tv_command(
    db: Session, device: Device, command: str, payload: dict[str, Any]
) -> None:
    """Carry out an already validated TV command on the real TV."""
    settings = config(device)
    if not settings["paired"]:
        raise SamsungUnavailable(409, "pair the TV first (Settings > Integrations)")
    if command == "set_volume":
        raise SamsungUnavailable(
            422, "this TV cannot set an exact volume; use volume up and down"
        )
    if command == "launch_app" and settings["protocol"] != "tizen":
        raise SamsungUnavailable(422, "only 2016 and newer TVs can launch apps")
    host, protocol = str(device.external_id), settings["protocol"]
    try:
        saved = credentials.load(db, device.home_id, _credential_key(device))
    except VaultError as error:
        raise SamsungUnavailable(409, str(error)) from None
    token = saved.get("token") if saved else None
    if protocol in ("tizen", "encrypted") and not token:
        raise SamsungUnavailable(409, "pair the TV again: its saved pairing is missing")
    try:
        if command == "turn_on":
            if settings["mac"]:
                samsung.wake(settings["mac"])
            else:
                samsung.send_keys(host, protocol, token, ["KEY_POWER"])
        elif command == "launch_app":
            samsung.launch_app(host, protocol, token, payload["app"])
        else:
            samsung.send_keys(
                host, protocol, token, samsung.command_keys(command, payload)
            )
    except samsung.TvUnsupported as error:
        raise SamsungUnavailable(422, str(error)) from None
    except samsung.TvDenied:
        raise SamsungUnavailable(409, "the TV refused: pair it again") from None
    except samsung.TvError as error:
        raise SamsungUnavailable(502, str(error)) from None
