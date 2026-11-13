"""A home's Samsung TVs: adding, pairing and sending remote commands.
Network calls go through app.integrations.samsung (replaced by fakes in tests)."""

import json
import logging
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import credentials, tv_app_catalog, tv_power, tv_sources
from app.features import integration_enabled
from app.integrations import samsung
from app.models import Device
from app.vault import VaultError

log = logging.getLogger(__name__)
INTEGRATION = "samsung_tv"
MAX_QUICK_APPS = 6


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
    device.capabilities = json.dumps(
        {**json.loads(device.capabilities or "{}"), **settings, "paired": True}
    )
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
    device.capabilities = json.dumps(
        {**json.loads(device.capabilities or "{}"), **settings, "paired": True}
    )
    device.online = True
    db.commit()


def update_tv(
    db: Session,
    device: Device,
    name: str,
    host: str,
    protocol: str,
    mac: str | None,
    room: str | None,
) -> bool:
    """Change a TV's details. A new address or protocol needs pairing again:
    the saved pairing is removed. Returns whether pairing is needed now."""
    if host != device.external_id and any(
        d.external_id == host for d in list_tvs(db, device.home_id) if d.id != device.id
    ):
        raise SamsungUnavailable(409, "a TV with that address is already added")
    settings = config(device)
    repair = host != device.external_id or protocol != settings["protocol"]
    if repair:
        credentials.remove(db, device.home_id, _credential_key(device))
    device.name, device.room, device.external_id = name, room, host
    device.capabilities = json.dumps(
        {
            **json.loads(device.capabilities or "{}"),  # keeps the quick apps
            "protocol": protocol,
            "mac": mac,
            "paired": settings["paired"] and not repair,
        }
    )
    db.commit()
    return repair


def remove_tv(db: Session, device: Device) -> None:
    credentials.remove(db, device.home_id, _credential_key(device))
    db.delete(device)
    db.commit()


def send_tv_command(
    db: Session, device: Device, command: str, payload: dict[str, Any]
) -> None:
    """Carry out an already validated TV command on the real TV."""
    if command == "set_source":  # an input by name: through SmartThings
        try:
            tv_sources.set_tv_source(db, device, payload["source"])
        except tv_sources.SourcesUnavailable as error:
            raise SamsungUnavailable(error.status_code, error.reason) from None
        return
    settings = config(device)
    if not settings["paired"]:
        raise SamsungUnavailable(409, "pair the TV first (Settings > Integrations)")
    if command == "set_volume":
        raise SamsungUnavailable(
            422, "this TV cannot set an exact volume; use volume up and down"
        )
    if command in ("launch_app", "open_app") and settings["protocol"] != "tizen":
        raise SamsungUnavailable(422, "only 2016 and newer TVs can launch apps")
    host, protocol, token = _connection(db, device)
    try:
        if command in ("turn_on", "turn_off"):  # one key both ways: see tv_power
            state = tv_power.power_state(host, protocol)
            step = tv_power.plan(command, state, settings["mac"])
            # Not answering at all (off, not in network standby): Samsung's
            # cloud as well, as a wake-up packet often cannot reach the TV.
            # Never beside the power key, which would turn it straight off.
            cloud = command == "turn_on" and state is None
            if cloud and tv_sources.turn_on(db, device) and step == "key":
                step = "nothing"  # no wake-up packet to send (no MAC address)
            if step == "wake":
                tv_power.wake(str(settings["mac"]), host)
            elif step == "key":
                samsung.send_keys(host, protocol, token, ["KEY_POWER"])
        elif command == "launch_app":
            samsung.launch_app(host, protocol, token, payload["app"])
        elif command == "open_app":
            samsung._tizen_call(
                host, token, lambda tv: samsung._start_app(tv, payload["app_id"])
            )
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


def _connection(db: Session, device: Device) -> tuple[str, str, str | None]:
    """The TV's address, protocol and saved pairing token."""
    settings = config(device)
    if not settings["paired"]:
        raise SamsungUnavailable(409, "pair the TV first (Settings > Integrations)")
    host, protocol = str(device.external_id), settings["protocol"]
    try:
        saved = credentials.load(db, device.home_id, _credential_key(device))
    except VaultError as error:
        raise SamsungUnavailable(409, str(error)) from None
    token = saved.get("token") if saved else None
    if protocol in ("tizen", "encrypted") and not token:
        raise SamsungUnavailable(409, "pair the TV again: its saved pairing is missing")
    return host, protocol, token


def tv_apps(db: Session, device: Device) -> list[dict[str, Any]]:
    """The apps installed on the TV, by name, for choosing quick apps. A TV
    that is on but will not say which it has gets the common ones, marked
    "unconfirmed" (one it lacks just does not open)."""
    if config(device)["protocol"] != "tizen":
        raise SamsungUnavailable(422, "only 2016 and newer TVs can launch apps")
    host, protocol, token = _connection(db, device)
    problem: samsung.TvError | None = None
    apps: list[dict[str, Any]]
    try:
        apps = samsung.installed_apps(host, protocol, token)
    except samsung.TvDenied:
        raise SamsungUnavailable(409, "the TV refused: pair it again") from None
    except samsung.TvError as error:
        apps, problem = [], error
    if not apps:
        # Off, or one of the TVs that will not list its apps (tv_app_catalog).
        if tv_power.power_state(host, protocol) is None:
            raise SamsungUnavailable(
                409, "the TV is off or not answering: turn it on, then try again"
            )
        apps = tv_app_catalog.installed(host)
        if not apps:
            why = f" ({problem})" if problem else ""
            log.info("TV %s will not say which apps it has%s", host, why)
            apps = [{**a, "unconfirmed": True} for a in tv_app_catalog.common()]
    return sorted(apps, key=lambda app: str(app["name"]).lower())


def set_quick_apps(db: Session, device: Device, apps: list[dict[str, str]]) -> None:
    """Up to six apps for the remote's quick buttons ([] = the usual six)."""
    data = json.loads(device.capabilities or "{}")
    device.capabilities = json.dumps({**data, "quick_apps": apps[:MAX_QUICK_APPS]})
    db.commit()
