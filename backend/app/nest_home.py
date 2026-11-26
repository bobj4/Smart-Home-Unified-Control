"""A home's Google Nest (Device Access): signing in, finding the devices,
their state, thermostat commands, and camera and doorbell events.

Saved (credential "google_nest", encrypted): {"project_id" (the Device
Access project), "client_id", "client_secret" (the Google Cloud OAuth
client), "subscription" (optional: "projects/<cloud project>/subscriptions/
<name>", for camera and doorbell events), "refresh_token", "access_token",
"expires_at" (epoch seconds), "problem" (None, or why to sign in again)}.

Devices: thermostats (type "thermostat", the same state as a Cync one:
mode, heat and cool set points, fan, humidity; whole degrees F, Google
works in Celsius), and cameras, doorbells and displays (type "camera"; the
last thing seen, from events). Each keeps Google's traits in its
capabilities ("traits"), so an event that changes one trait updates it.

Read every POLL_SECONDS (EVENTS_POLL_SECONDS when events come through
Pub/Sub, which also carries trait changes), and events are pulled each
pass of the background refresh.
"""

import json
import logging
import secrets
import time
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import credentials, integration_status
from app.features import integration_enabled
from app.integrations import nest
from app.models import Device, Home, utcnow
from app.vault import VaultError

log = logging.getLogger(__name__)
INTEGRATION = "google_nest"
POLL_SECONDS = 120
EVENTS_POLL_SECONDS = 600  # trait changes come with the events too
START_SECONDS = 1800  # a sign-in must come back within this
EVENT_MAX_AGE = 600  # older events (the server was off, say) alert no one
RECONNECT = "Google Nest needs signing in again (Settings > Integrations)"
TYPES = {
    "sdm.devices.types.THERMOSTAT": ("thermostat", "thermostat"),
    "sdm.devices.types.CAMERA": ("camera", "camera"),
    "sdm.devices.types.DOORBELL": ("camera", "doorbell"),
    "sdm.devices.types.DISPLAY": ("camera", "display"),
}
MODES = {"HEAT": "heat", "COOL": "cool", "HEATCOOL": "auto", "OFF": "off"}
GOOGLE_MODES = {ours: theirs for theirs, ours in MODES.items()}
HVAC = {"HEATING": "heating", "COOLING": "cooling", "OFF": "idle"}
EVENTS = {
    "CameraPerson.Person": "person",
    "CameraMotion.Motion": "motion",
    "CameraSound.Sound": "sound",
    "DoorbellChime.Chime": "doorbell",
}
FAN_ON_SECONDS = 43200  # Google's longest fan timer: 12 hours

_read_at: dict[str, float] = {}
# state -> (home id, started)
_started: dict[str, tuple[str, float]] = {}
# (device id, event kind, session) already alerted
_seen_events: dict[tuple[str, str, str], float] = {}


class NestUnavailable(Exception):
    def __init__(self, status_code: int, reason: str) -> None:
        self.status_code = status_code
        self.reason = reason


# ------------------------------------------------------------ the sign-in


def saved(db: Session, home_id: str) -> dict[str, Any] | None:
    try:
        return credentials.load(db, home_id, INTEGRATION)
    except VaultError as error:
        raise NestUnavailable(409, str(error)) from None


def _keep(db: Session, home_id: str, data: dict[str, Any]) -> None:
    try:
        credentials.save(db, home_id, INTEGRATION, data["project_id"], data)
    except VaultError as error:
        raise NestUnavailable(409, str(error)) from None


def start(db: Session, home_id: str, app: dict[str, str]) -> str:
    """Keep the project and OAuth client (the secret kept when left out),
    and return Google's sign-in page."""
    old = saved(db, home_id) or {}
    secret = app.get("client_secret") or ""
    if not secret and old.get("client_id") == app["client_id"]:
        secret = str(old.get("client_secret") or "")
    if not secret:
        raise NestUnavailable(422, "enter the OAuth client secret")
    same = (old.get("project_id"), old.get("client_id")) == (
        app["project_id"],
        app["client_id"],
    )
    data = {
        **(old if same else {}),
        "project_id": app["project_id"],
        "client_id": app["client_id"],
        "client_secret": secret,
        "subscription": app.get("subscription") or None,
    }
    _keep(db, home_id, data)
    now = time.monotonic()
    for state, (_, began) in list(_started.items()):
        if now - began > START_SECONDS:
            _started.pop(state, None)
    state = secrets.token_urlsafe(24)
    _started[state] = (home_id, now)
    return nest.authorize_url(app["project_id"], app["client_id"], state)


def _tokens(data: dict[str, Any], answer: dict[str, Any]) -> dict[str, Any]:
    return {
        **data,
        "access_token": str(answer["access_token"]),
        "refresh_token": str(
            answer.get("refresh_token") or data.get("refresh_token") or ""
        ),
        "expires_at": time.time() + float(answer.get("expires_in") or 3600),
        "problem": None,
    }


def finish(db: Session, home_id: str, pasted: str) -> dict[str, Any]:
    """The address Google sent the person to (or its code): swap the code
    for tokens, then find the devices."""
    data = saved(db, home_id)
    if not data or not data.get("client_id"):
        raise NestUnavailable(409, "enter the project and OAuth client first")
    try:
        code, state = nest.code_from(pasted)
    except nest.NestError as error:
        raise NestUnavailable(422, str(error)) from None
    if state is not None:
        began = _started.pop(state, None)
        if began is None or began[0] != home_id:
            raise NestUnavailable(
                409, "that sign-in is old or for another home: press Sign in again"
            )
    answer = call(lambda: nest.exchange(data["client_id"], data["client_secret"], code))
    if not answer.get("refresh_token"):
        raise NestUnavailable(
            502, "Google sent no lasting sign-in: press Sign in again"
        )
    _keep(db, home_id, _tokens(data, answer))
    integration_status.worked(home_id, INTEGRATION)
    return sync(db, home_id)


def call(action: Any) -> Any:
    """One Google call, its errors as NestUnavailable."""
    try:
        return action()
    except nest.NestDenied as error:
        raise NestUnavailable(401, str(error)) from None
    except nest.NestError as error:
        raise NestUnavailable(502, str(error)) from None


def _connected(db: Session, home_id: str) -> dict[str, Any]:
    if not integration_enabled(db, home_id, INTEGRATION):
        raise NestUnavailable(409, "the Google Nest integration is turned off")
    data = saved(db, home_id)
    if not data or not data.get("refresh_token"):
        raise NestUnavailable(409, "Google Nest is not signed in yet")
    if data.get("problem"):
        raise NestUnavailable(409, str(data["problem"]))
    return data


def access_token(db: Session, home_id: str) -> tuple[str, dict[str, Any]]:
    """A working access token (renewed when it ends within 5 minutes)."""
    data = _connected(db, home_id)
    if (
        data.get("access_token")
        and float(data.get("expires_at") or 0) > time.time() + 300
    ):
        return str(data["access_token"]), data
    try:
        answer = nest.refresh(
            data["client_id"], data["client_secret"], data["refresh_token"]
        )
    except nest.NestDenied as error:
        _keep(db, home_id, {**data, "problem": RECONNECT})
        raise NestUnavailable(401, f"{RECONNECT} ({error})") from None
    except nest.NestError as error:
        raise NestUnavailable(502, str(error)) from None
    data = _tokens(data, answer)
    _keep(db, home_id, data)
    return str(data["access_token"]), data


def _authorized(db: Session, home_id: str, action: Any) -> Any:
    """Run action(token, data); a token Google stopped taking is renewed once."""
    token, data = access_token(db, home_id)
    try:
        return action(token, data)
    except nest.NestDenied:
        _keep(db, home_id, {**data, "expires_at": 0})
        token, data = access_token(db, home_id)
        return call(lambda: action(token, data))
    except nest.NestError as error:
        raise NestUnavailable(502, str(error)) from None


def status(db: Session, home_id: str) -> dict[str, Any]:
    data = saved(db, home_id) or {}
    return {
        "configured": bool(data.get("client_id")),
        "connected": bool(data.get("refresh_token")) and not data.get("problem"),
        "project_id": data.get("project_id"),
        "client_id": data.get("client_id"),
        "subscription": data.get("subscription"),
        "problem": data.get("problem"),
    }


def health(db: Session, home_id: str) -> str | None:
    """Why it must be signed in again, if it must (for the alert)."""
    try:
        data = saved(db, home_id)
    except NestUnavailable:
        return None
    return str(data["problem"]) if data and data.get("problem") else None


# ------------------------------------------------------------ devices


def _f(celsius: Any) -> int | None:
    if not isinstance(celsius, int | float) or isinstance(celsius, bool):
        return None
    return round(celsius * 9 / 5 + 32)


def celsius(fahrenheit: float) -> float:
    return round((fahrenheit - 32) * 5 / 9, 2)


def _trait(traits: dict[str, Any], name: str) -> dict[str, Any]:
    return dict(traits.get(f"{nest.TRAIT}{name}") or {})


def thermostat_state(traits: dict[str, Any]) -> dict[str, Any]:
    """The app's thermostat state from Google's traits."""
    mode_trait, eco = _trait(traits, "ThermostatMode"), _trait(traits, "ThermostatEco")
    eco_on = eco.get("mode") == "MANUAL_ECO"
    mode = "eco" if eco_on else MODES.get(str(mode_trait.get("mode")), None)
    modes = [MODES[m] for m in mode_trait.get("availableModes") or [] if m in MODES]
    if "MANUAL_ECO" in (eco.get("availableModes") or []):
        modes.append("eco")
    points = eco if eco_on else _trait(traits, "ThermostatTemperatureSetpoint")
    heat, cool = _f(points.get("heatCelsius")), _f(points.get("coolCelsius"))
    hvac = HVAC.get(str(_trait(traits, "ThermostatHvac").get("status")), "idle")
    state: dict[str, Any] = {
        "mode": mode,
        "modes": modes,
        "status": "off" if mode == "off" else hvac,
        "current_temperature": _f(
            _trait(traits, "Temperature").get("ambientTemperatureCelsius")
        ),
        "heat_setpoint": heat,
        "cool_setpoint": cool,
        "target_temperature": cool
        if mode == "cool"
        else heat
        if heat is not None
        else cool,
        "unit": "F",
        "system": "Google Nest",
    }
    humidity = _trait(traits, "Humidity").get("ambientHumidityPercent")
    if isinstance(humidity, int | float):
        state["humidity"] = round(humidity)
    fan = _trait(traits, "Fan")
    if fan.get("timerMode"):
        state["fan"] = "on" if fan["timerMode"] == "ON" else "auto"
    return state


def _online(traits: dict[str, Any]) -> bool:
    status = _trait(traits, "Connectivity").get("status")
    return status != "OFFLINE"


def _apply_traits(device: Device, traits: dict[str, Any]) -> None:
    """Merge Google's (possibly partial) traits into the device's, and its
    state from them."""
    caps = json.loads(device.capabilities or "{}")
    kept: dict[str, Any] = dict(caps.get("traits") or {})
    for name, fields in traits.items():
        kept[name] = {**(kept.get(name) or {}), **(fields or {})}
    caps["traits"] = kept
    device.capabilities = json.dumps(caps)
    state = json.loads(device.state or "{}")
    if device.type == "thermostat":
        state.update(thermostat_state(kept))
    device.state = json.dumps(state)
    device.online = _online(kept)
    device.last_updated = utcnow()


def _name(found: dict[str, Any], kind: str) -> str:
    custom = str(_trait(found.get("traits") or {}, "Info").get("customName") or "")
    where = next(
        (
            str(r.get("displayName"))
            for r in found.get("parentRelations") or []
            if r.get("displayName")
        ),
        "",
    )
    words = {"thermostat": "thermostat", "camera": "camera", "doorbell": "doorbell"}
    return (custom or f"{where} {words.get(kind, 'display')}".strip())[:100]


def sync(db: Session, home_id: str) -> dict[str, int]:
    """Create or update a device for each shared Nest device; ones no longer
    shared (taken off in Google's sign-in page) are deleted."""
    found = _authorized(
        db, home_id, lambda token, data: nest.list_devices(token, data["project_id"])
    )
    existing = {
        d.external_id: d
        for d in db.scalars(
            select(Device).where(
                Device.home_id == home_id, Device.integration == INTEGRATION
            )
        )
    }
    if not found and existing:
        # Nothing at all: more likely a Google hiccup than every device
        # taken off. Kept, as offline (sign in again to change what is shared).
        for kept in existing.values():
            kept.online = False
        db.commit()
        return {"created": 0, "updated": 0, "kept": len(existing)}
    created = updated = 0
    for item in found:
        kinds = TYPES.get(str(item.get("type")))
        if kinds is None or not item.get("name"):
            continue
        device_type, kind = kinds
        external = str(item["name"]).rsplit("/", 1)[-1][:100]
        device: Device | None = existing.pop(external, None)
        if device is None:
            room = next(
                (
                    str(r.get("displayName"))
                    for r in item.get("parentRelations") or []
                    if r.get("displayName")
                ),
                None,
            )
            device = Device(
                home_id=home_id,
                integration=INTEGRATION,
                external_id=external,
                type=device_type,
                name=_name(item, kind),
                room=room,
                capabilities=json.dumps({"nest_type": kind}),
                state="{}",
            )
            db.add(device)
            created += 1
        else:
            updated += 1
        caps = json.loads(device.capabilities or "{}")
        caps["nest_type"] = kind
        caps.pop("traits", None)  # the full set, fresh
        device.capabilities = json.dumps(caps)
        _apply_traits(device, dict(item.get("traits") or {}))
    for device in existing.values():
        db.delete(device)
    db.commit()
    return {"created": created, "updated": updated}


def _google_name(db: Session, device: Device) -> str:
    data = saved(db, device.home_id) or {}
    return f"enterprises/{data.get('project_id')}/devices/{device.external_id}"


def send_command(
    db: Session,
    device: Device,
    command: str,
    payload: dict[str, Any],
    state: dict[str, Any],
) -> None:
    """Carry out an accepted thermostat command on the Nest thermostat."""
    if device.type != "thermostat":
        raise NestUnavailable(422, "Nest cameras take no commands here")
    before = json.loads(device.state or "{}")
    steps: list[tuple[str, dict[str, Any]]] = []
    if command == "set_mode":
        mode = state["mode"]
        if mode == "eco":
            steps.append(("ThermostatEco.SetMode", {"mode": "MANUAL_ECO"}))
        else:
            if before.get("mode") == "eco":
                steps.append(("ThermostatEco.SetMode", {"mode": "OFF"}))
            steps.append(("ThermostatMode.SetMode", {"mode": GOOGLE_MODES[mode]}))
    elif command in ("set_temperature", "set_cool_temperature"):
        mode = state.get("mode")
        heat, cool = state.get("heat_setpoint"), state.get("cool_setpoint")
        if mode == "auto" and heat is not None and cool is not None:
            steps.append(
                (
                    "ThermostatTemperatureSetpoint.SetRange",
                    {"heatCelsius": celsius(heat), "coolCelsius": celsius(cool)},
                )
            )
        elif mode == "cool" and cool is not None:
            steps.append(
                (
                    "ThermostatTemperatureSetpoint.SetCool",
                    {"coolCelsius": celsius(cool)},
                )
            )
        elif mode == "heat" and heat is not None:
            steps.append(
                (
                    "ThermostatTemperatureSetpoint.SetHeat",
                    {"heatCelsius": celsius(heat)},
                )
            )
        else:
            raise NestUnavailable(
                409, "set points can only change in Heat, Cool or Auto"
            )
    elif command == "set_fan":
        on = state.get("fan") == "on"
        params: dict[str, Any] = {"timerMode": "ON" if on else "OFF"}
        if on:
            params["duration"] = f"{FAN_ON_SECONDS}s"
        steps.append(("Fan.SetTimer", params))
    else:
        raise NestUnavailable(422, "Nest thermostats do not take that command")
    name = _google_name(db, device)
    for google_command, params in steps:
        _authorized(
            db,
            device.home_id,
            lambda token, data, c=google_command, p=params: nest.execute(
                token, name, c, p
            ),
        )


# ------------------------------------------------------------ events


def _where(db: Session, home_id: str) -> str:
    home = db.get(Home, home_id)
    return home.name if home else "home"


def _age(event: dict[str, Any]) -> float:
    try:
        when = datetime.fromisoformat(
            str(event.get("timestamp")).replace("Z", "+00:00")
        )
    except ValueError:
        return 0.0
    if when.tzinfo is None:
        when = when.replace(tzinfo=UTC)
    return (datetime.now(UTC) - when).total_seconds()


def handle(db: Session, home_id: str, event: dict[str, Any]) -> int:
    """One Pub/Sub message: trait changes update the device; camera and
    doorbell events alert (per the device's bell). Returns alerts sent."""
    from app import alerts, device_alerts

    update = event.get("resourceUpdate") or {}
    external = str(update.get("name") or "").rsplit("/", 1)[-1]
    device = db.scalars(
        select(Device).where(
            Device.home_id == home_id,
            Device.integration == INTEGRATION,
            Device.external_id == external,
        )
    ).first()
    if device is None:
        return 0
    if update.get("traits"):
        _apply_traits(device, dict(update["traits"]))
        db.commit()
    sent = 0
    for name, details in (update.get("events") or {}).items():
        kind = EVENTS.get(name.removeprefix(nest.EVENT))
        if kind is None:
            continue
        session = str(
            (details or {}).get("eventSessionId") or event.get("eventId") or ""
        )
        key = (device.id, kind, session)
        if key in _seen_events or event.get("eventThreadState") in ("UPDATED", "ENDED"):
            continue
        _seen_events[key] = time.time()
        state = json.loads(device.state or "{}")
        state["last_event"] = {"kind": kind, "at": utcnow().isoformat()}
        device.state = json.dumps(state)
        db.commit()
        if _age(event) > EVENT_MAX_AGE:
            continue
        wanted = device_alerts.for_device(db, device)
        if not wanted["enabled"] or not wanted["settings"].get(kind, False):
            continue
        where = _where(db, home_id)
        if kind == "doorbell":
            title = f"Someone rang the {device.name}"
            body = f"Someone rang the {device.name} at {where}."
        else:
            seen = {"person": "a person", "motion": "motion", "sound": "a sound"}[kind]
            title = f"{kind.capitalize()} at {device.name}"
            body = f"The {device.name} at {where} picked up {seen}."
        sent += alerts.deliver(
            db,
            home_id,
            "doorbell" if kind == "doorbell" else "camera",
            title,
            body,
            f"nest-{device.id}-{kind}",
        )
    cutoff = time.time() - 3600
    for old in [k for k, at in _seen_events.items() if at < cutoff]:
        _seen_events.pop(old, None)
    return sent


def pull_events(db: Session, home_id: str) -> int:
    """Take what waits on the subscription; returns how many."""
    data = _connected(db, home_id)
    subscription = data.get("subscription")
    if not subscription:
        return 0
    got = _authorized(
        db, home_id, lambda token, _data: nest.pull(token, str(subscription))
    )
    for item in got:
        try:
            handle(db, home_id, item["event"])
        except Exception:  # one odd message must not stop the rest
            db.rollback()
            log.exception("a Nest event could not be handled")
    ack_ids = [str(i["ack_id"]) for i in got if i.get("ack_id")]
    if ack_ids:
        _authorized(
            db,
            home_id,
            lambda token, _data: nest.acknowledge(token, str(subscription), ack_ids),
        )
    return len(got)


def refresh(db: Session, home_id: str, now: float | None = None) -> bool | int:
    """The background refresh: events every pass, the devices now and then.
    Returns whether Google was asked (or how many events came)."""
    if not integration_enabled(db, home_id, INTEGRATION):
        return False
    try:
        data = saved(db, home_id)
    except NestUnavailable:
        return False
    if not data or not data.get("refresh_token") or data.get("problem"):
        return False
    now = time.monotonic() if now is None else now
    every = EVENTS_POLL_SECONDS if data.get("subscription") else POLL_SECONDS
    asked: bool | int = False
    try:
        if data.get("subscription"):
            asked = pull_events(db, home_id) or True
        last = _read_at.get(home_id)
        if last is None or now - last >= every:
            _read_at[home_id] = now
            sync(db, home_id)
            asked = True
    except NestUnavailable as error:
        db.rollback()
        integration_status.failed(home_id, INTEGRATION, error.reason)
        return False
    integration_status.worked(home_id, INTEGRATION)
    return asked
