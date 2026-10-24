"""A home's GE Cync account: logging in (with the emailed code), finding its
lights and plugs, and sending commands. Network calls go through
app.integrations.cync (replaced by fakes in tests)."""

import json
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import credentials, cync_live
from app.features import integration_enabled
from app.groups import import_cync
from app.integrations import cync, cync_thermostat
from app.lights import MAX_KELVIN, MIN_KELVIN
from app.models import Device, utcnow
from app.vault import VaultError

INTEGRATION = "cync"


class CyncUnavailable(Exception):
    def __init__(self, status_code: int, reason: str) -> None:
        self.status_code = status_code
        self.reason = reason


def _call(action: Any) -> Any:
    try:
        return action()
    except cync.CyncLoginError as error:
        raise CyncUnavailable(409, str(error)) from None
    except cync.CyncUnsupported as error:
        raise CyncUnavailable(422, str(error)) from None
    except cync.CyncError as error:
        raise CyncUnavailable(502, str(error)) from None


def _save(db: Session, home_id: str, email: str, tokens: dict[str, Any]) -> None:
    try:
        credentials.save(
            db, home_id, INTEGRATION, email, {"email": email, "tokens": tokens}
        )
    except VaultError as error:
        raise CyncUnavailable(409, str(error)) from None


def _login_for_home(db: Session, home_id: str) -> dict[str, Any]:
    if not integration_enabled(db, home_id, INTEGRATION):
        raise CyncUnavailable(409, "the GE Cync integration is turned off")
    try:
        saved = credentials.load(db, home_id, INTEGRATION)
    except VaultError as error:
        raise CyncUnavailable(409, str(error)) from None
    if saved is None:
        raise CyncUnavailable(409, "no Cync account is saved for this home")
    return saved


def log_in(
    db: Session, home_id: str, email: str, password: str, code: str | None
) -> bool:
    """Returns False when Cync emailed a code (log in again with it), True
    when the login is saved. Only the tokens are kept, not the password."""
    try:
        tokens = cync.login(email, password, code)
    except cync.CyncCodeSent:
        return False
    except cync.CyncLoginError:
        raise CyncUnavailable(400, "Cync refused the email, password or code") from None
    except cync.CyncError as error:
        raise CyncUnavailable(502, str(error)) from None
    _save(db, home_id, email, tokens)
    db.commit()
    return True


def sync(db: Session, home_id: str) -> dict[str, int]:
    """Create or update a device for every Cync light and plug; delete ones no
    longer on the account (removed in the Cync app)."""
    saved = _login_for_home(db, home_id)
    found, tokens = _call(lambda: cync.list_devices(saved["tokens"]))
    _save(db, home_id, saved["email"], tokens)
    existing = {
        d.external_id: d
        for d in db.scalars(
            select(Device).where(
                Device.home_id == home_id, Device.integration == INTEGRATION
            )
        )
    }
    created = updated = 0
    for info in found:
        device = existing.pop(info.id, None)
        if device is None:
            device = Device(
                home_id=home_id,
                integration=INTEGRATION,
                external_id=info.id,
                type=info.kind,
                name=info.name or "Cync device",
                state="{}",
            )
            db.add(device)
            created += 1
        else:
            updated += 1
        device.capabilities = json.dumps(
            {
                "dimming": info.dimming,
                "white": info.white,
                "color": info.color,
                "mac": info.mac,
                **({"cloud_id": info.cloud_id} if info.cloud_id is not None else {}),
            }
        )
        device.online = info.online
        device.last_updated = utcnow()
    for device in existing.values():
        db.delete(device)
    db.commit()
    if cync_live.connection(home_id) is None:  # the live connection reports states
        _read_states(db, home_id, saved["tokens"])
    _import_groups(db, home_id, saved["tokens"])
    return {"created": created, "updated": updated}


def _import_groups(db: Session, home_id: str, tokens: dict[str, Any]) -> None:
    """Best effort: rooms and groups as the Cync app shows them."""
    try:
        groups, _fresh = cync.list_groups(tokens)
    except cync.CyncError:
        return
    import_cync(db, home_id, groups)


def cync_to_kelvin(value: int) -> int:
    share = (value - 1) / 99
    return int(round((MAX_KELVIN - share * (MAX_KELVIN - MIN_KELVIN)) / 100) * 100)


def _read_states(db: Session, home_id: str, tokens: dict[str, Any]) -> None:
    """Store what the devices report. Best effort: if Cync cannot report
    (no device on Wi-Fi, slow answer) the stored state stays as it was."""
    try:
        states = cync.read_states(tokens)
    except cync.CyncError:
        return
    store_states(db, home_id, states)


def store_states(db: Session, home_id: str, states: dict[str, dict[str, Any]]) -> int:
    """Save reported states (by Cync device id); returns how many devices."""
    changed = 0
    devices = db.scalars(
        select(Device).where(
            Device.home_id == home_id, Device.integration == INTEGRATION
        )
    )
    for device in devices:
        reported = states.get(str(device.external_id))
        if reported is None:
            continue
        if "thermostat" in reported:  # a full report from the thermostat
            state = {**json.loads(device.state or "{}"), **reported["thermostat"]}
            device.state = json.dumps(state)
            device.online = True
            device.last_updated = utcnow()
            changed += 1
            continue
        state = {**json.loads(device.state or "{}"), "on": reported["on"]}
        if "brightness" in reported:
            state["brightness"] = reported["brightness"]
        if "color_temp" in reported:
            state["color_mode"] = "temp"
            state["color_temp"] = cync_to_kelvin(reported["color_temp"])
        if "rgb" in reported:
            state["color_mode"] = "rgb"
            state["color"] = "#" + "".join(f"{v:02x}" for v in reported["rgb"])
        device.state = json.dumps(state)
        device.last_updated = utcnow()
        changed += 1
    db.commit()
    return changed


def kelvin_to_cync(kelvin: int) -> int:
    """Cync's 1-100 scale: 1 is the coolest white, 100 the warmest."""
    share = (MAX_KELVIN - kelvin) / (MAX_KELVIN - MIN_KELVIN)
    return max(1, min(100, round(1 + share * 99)))


def _action(device: Device, command: str, state: dict[str, Any]) -> tuple[str, Any]:
    caps = json.loads(device.capabilities or "{}")
    if command in ("turn_on", "turn_off"):
        return "power", command == "turn_on"
    if command == "set_brightness" and caps.get("dimming"):
        return "brightness", state["brightness"]
    if command == "set_color_temp" and caps.get("white"):
        return "color_temp", kelvin_to_cync(state["color_temp"])
    if command == "set_color" and caps.get("color"):
        hex_color = state["color"].lstrip("#")
        return "rgb", tuple(int(hex_color[i : i + 2], 16) for i in (0, 2, 4))
    raise CyncUnavailable(422, "this Cync device cannot do that")


def _thermostat_entries(
    command: str, state: dict[str, Any]
) -> list[tuple[int, int | str]]:
    t = cync_thermostat
    unit = "C" if state.get("device_unit") == "C" else "F"
    if command == "set_mode":
        return [(t.MODE_SET, t.MODE_CODES[state["mode"]])]
    if command == "set_fan":
        return [(t.FAN_SET, t.FAN_CODES[state["fan"]])]
    if command == "set_hold":
        return [(t.HOLD_SET, t.HOLD_CODES[state["hold"]])]
    if command == "set_temperature" and state.get("mode") == "cool":
        return [(t.COOL_SET, t.format_temperature(state["cool_setpoint"], unit))]
    if command == "set_temperature":
        return [(t.HEAT_SET, t.format_temperature(state["heat_setpoint"], unit))]
    if command == "set_cool_temperature":
        return [(t.COOL_SET, t.format_temperature(state["cool_setpoint"], unit))]
    raise CyncUnavailable(422, "the thermostat cannot do that")


def send_thermostat(
    db: Session, device: Device, command: str, state: dict[str, Any]
) -> None:
    """Write to the thermostat over the live connection and check that it
    reports the new value (writing is not yet confirmed on real hardware)."""
    entries = _thermostat_entries(command, state)
    cloud_id = json.loads(device.capabilities or "{}").get("cloud_id")
    if cloud_id is None:
        raise CyncUnavailable(
            409, "sync Cync again to finish setting up the thermostat"
        )
    _login_for_home(db, device.home_id)
    live = cync_live.connection(device.home_id)
    if live is None:
        raise CyncUnavailable(503, "Cync is still connecting; try again in a minute")
    points = _call(
        lambda: cync.thermostat_write_on_open(live[0], live[1], int(cloud_id), entries)
    )
    if not cync_thermostat.confirmed(entries, points):
        raise CyncUnavailable(
            502, "the thermostat did not take the change; check it in the Cync app"
        )


def send_command(
    db: Session, device: Device, command: str, state: dict[str, Any]
) -> None:
    """Carry out an already validated light or plug command."""
    if device.type == "thermostat":
        send_thermostat(db, device, command, state)
        return
    action, value = _action(device, command, state)
    saved = _login_for_home(db, device.home_id)
    live = cync_live.connection(device.home_id)
    if live is not None:
        # Cync allows one connection per account: use the open one.
        _call(
            lambda: cync.act_on_open(
                live[0], live[1], str(device.external_id), action, value
            )
        )
        return
    tokens = _call(
        lambda: cync.send(saved["tokens"], str(device.external_id), action, value)
    )
    _save(db, device.home_id, saved["email"], tokens)
