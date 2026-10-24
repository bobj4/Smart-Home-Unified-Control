"""Devices of one home, and device commands.

SEC-11: every route checks the caller's membership of the home in the path.
SEC-40 to SEC-42: commands are validated in the backend; thermostat and
water-heater commands are refused until safety limits are configured;
refused commands change nothing and are audited.
"""

import json
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import credentials
from app.audit import record_event
from app.authorization import require_role
from app.db_config import get_db
from app.dependencies import client_ip, current_user, require_csrf
from app.device_io import DeviceUnavailable, send_to_device
from app.features import BY_ID, integration_enabled
from app.lights import LightError, light_state
from app.models import Device, DeviceSafetyLimits, Role, User, utcnow
from app.safety import LIMITED_TYPES, initial_state
from app.thermostat import (
    THERMOSTAT_COMMANDS,
    ThermostatError,
    set_point_state,
    thermostat_state,
)
from app.tv import RemoteError, tv_state
from app.water_heater import WATER_HEATER_COMMANDS, WaterHeaterError, water_heater_state

router = APIRouter(prefix="/api/v1/homes/{home_id}/devices", tags=["devices"])

DeviceType = Literal[
    "light", "plug", "thermostat", "tv", "water_heater", "camera", "sensor"
]


class DeviceCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=100)
    type: DeviceType
    integration: Literal["simulated"]
    room: str | None = Field(default=None, max_length=50)


class DeviceUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=100)
    room: str | None = Field(default=None, max_length=50)


class DeviceCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")

    command: str = Field(min_length=1, max_length=50, pattern=r"^[a-z_]+$")
    payload: dict[str, Any] = Field(default_factory=dict)


class CommandRejected(Exception):
    def __init__(self, status_code: int, reason: str) -> None:
        self.status_code = status_code
        self.reason = reason


def _network(device: Device) -> dict[str, str | None]:
    """The device's address on the home network, when its brand reports it."""
    caps = json.loads(device.capabilities or "{}")
    ip = caps.get("ip")
    if device.integration == "samsung_tv":
        ip = device.external_id  # TVs are added by their IP address
    return {"ip": ip, "mac": caps.get("mac")}


def _device_out(device: Device) -> dict[str, Any]:
    caps = json.loads(device.capabilities or "{}")
    return {
        "id": device.id,
        "name": device.name,
        "type": device.type,
        "integration": device.integration,
        "room": device.room,
        "online": device.online,
        "state": json.loads(device.state or "{}"),
        "network": _network(device),
        "limits": {
            "min_temperature": device.min_temperature,
            "max_temperature": device.max_temperature,
        }
        if device.type in LIMITED_TYPES
        else None,
        # TVs: which remote features this TV has (2016+ "tizen" launches apps).
        "protocol": caps.get("protocol")
        if device.integration == "samsung_tv"
        else None,
    }


def _get_device(db: Session, home_id: str, device_id: str) -> Device:
    device = db.scalars(
        select(Device).where(Device.id == device_id, Device.home_id == home_id)
    ).first()
    if device is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found")
    return device


def _expect_keys(payload: dict[str, Any], keys: set[str]) -> None:
    if set(payload) != keys:
        raise CommandRejected(422, f"payload must contain exactly: {sorted(keys)}")


def _number(payload: dict[str, Any], key: str) -> float:
    value = payload[key]
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise CommandRejected(422, f"{key} must be a number")
    return float(value)


def _limits(db: Session, device: Device) -> DeviceSafetyLimits:
    limits = db.scalars(
        select(DeviceSafetyLimits).where(
            DeviceSafetyLimits.home_id == device.home_id,
            DeviceSafetyLimits.device_type == device.type,
            DeviceSafetyLimits.enabled.is_(True),
        )
    ).first()
    if (
        limits is None
        or limits.min_temperature is None
        or limits.max_temperature is None
    ):
        raise CommandRejected(409, "safety limits are not configured for this device")
    return limits


def _device_bounds(
    device: Device, limits: DeviceSafetyLimits
) -> tuple[float | None, float | None]:
    """The home's limits for the type, narrowed by the device's own."""
    low, high = limits.min_temperature, limits.max_temperature
    if device.min_temperature is not None and low is not None:
        low = max(low, device.min_temperature)
    if device.max_temperature is not None and high is not None:
        high = min(high, device.max_temperature)
    return low, high


def _new_state(db: Session, device: Device, cmd: DeviceCommand) -> dict[str, Any]:
    """Validate a command and return the device's new state. Raises
    CommandRejected without changing anything if the command is not allowed."""
    state: dict[str, Any] = json.loads(device.state or "{}")
    if not integration_enabled(db, device.home_id, device.integration):
        integration = BY_ID.get(device.integration)
        name = integration.name if integration else device.integration
        raise CommandRejected(409, f"the {name} integration is turned off")
    if device.type == "water_heater" and cmd.command in WATER_HEATER_COMMANDS:
        try:
            return water_heater_state(state, cmd.command, cmd.payload)
        except WaterHeaterError as error:
            raise CommandRejected(error.status_code, error.reason) from None
    if device.type in LIMITED_TYPES:
        limits = _limits(db, device)
        is_thermostat = device.type == "thermostat"
        try:
            if is_thermostat and cmd.command in THERMOSTAT_COMMANDS:
                return thermostat_state(state, cmd.command, cmd.payload)
            setting = ("set_temperature", "set_cool_temperature")
            if cmd.command not in (setting if is_thermostat else setting[:1]):
                raise CommandRejected(422, "unsupported command")
            _expect_keys(cmd.payload, {"temperature"})
            temperature = _number(cmd.payload, "temperature")
            low, high = _device_bounds(device, limits)
            if low is None or high is None or not low <= temperature <= high:
                raise CommandRejected(
                    422, f"temperature must be within {low}-{high} {limits.unit}"
                )
            new = {**state, "target_temperature": temperature, "unit": limits.unit}
            if is_thermostat:
                return set_point_state(state, new, cmd.command, temperature)
            return new
        except ThermostatError as error:
            raise CommandRejected(error.status_code, error.reason) from None
    if device.type == "tv":
        try:
            return tv_state(state, cmd.command, cmd.payload)
        except RemoteError as error:
            raise CommandRejected(error.status_code, error.reason) from None
    if device.type in ("light", "plug"):
        try:
            return light_state(device.type, state, cmd.command, cmd.payload)
        except LightError as error:
            raise CommandRejected(error.status_code, error.reason) from None
    raise CommandRejected(422, "unsupported command")


@router.get("")
def list_devices(
    home_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)
) -> list[dict[str, Any]]:
    require_role(db, user.id, home_id)
    devices = db.scalars(
        select(Device).where(Device.home_id == home_id).order_by(Device.name)
    )
    return [_device_out(d) for d in devices]


@router.get("/{device_id}")
def get_device(
    home_id: str,
    device_id: str,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    require_role(db, user.id, home_id)
    return _device_out(_get_device(db, home_id, device_id))


@router.post(
    "", status_code=status.HTTP_201_CREATED, dependencies=[Depends(require_csrf)]
)
def create_device(
    home_id: str,
    body: DeviceCreate,
    request: Request,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    require_role(db, user.id, home_id, Role.OPERATOR)
    if not integration_enabled(db, home_id, body.integration):
        raise HTTPException(status.HTTP_409_CONFLICT, "That integration is turned off")
    state = initial_state(db, home_id, body.type)
    device = Device(
        home_id=home_id, capabilities="{}", state=json.dumps(state), **body.model_dump()
    )
    db.add(device)
    db.commit()
    record_event(
        db,
        "device_created",
        user_id=user.id,
        home_id=home_id,
        ip_address=client_ip(request),
        details={"device_id": device.id, "type": device.type},
    )
    return _device_out(device)


@router.patch("/{device_id}", dependencies=[Depends(require_csrf)])
def update_device(
    home_id: str,
    device_id: str,
    body: DeviceUpdate,
    request: Request,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    require_role(db, user.id, home_id, Role.OPERATOR)
    device = _get_device(db, home_id, device_id)
    changes = body.model_dump(exclude_unset=True)
    if not changes:
        raise HTTPException(422, "nothing to change")
    for field, value in changes.items():
        setattr(device, field, value)
    db.commit()
    record_event(
        db,
        "device_updated",
        user_id=user.id,
        home_id=home_id,
        ip_address=client_ip(request),
        details={"device_id": device_id, **changes},
    )
    return _device_out(device)


@router.delete("/{device_id}", dependencies=[Depends(require_csrf)])
def delete_device(
    home_id: str,
    device_id: str,
    request: Request,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> dict[str, str]:
    require_role(db, user.id, home_id, Role.OPERATOR)
    device = _get_device(db, home_id, device_id)
    if device.integration == "samsung_tv":  # its pairing token goes too
        credentials.remove(db, home_id, f"samsung_tv:{device.id}")
    db.delete(device)
    db.commit()
    record_event(
        db,
        "device_deleted",
        user_id=user.id,
        home_id=home_id,
        ip_address=client_ip(request),
        details={"device_id": device_id},
    )
    return {"detail": "Deleted"}


@router.post("/{device_id}/command", dependencies=[Depends(require_csrf)])
def send_command(
    home_id: str,
    device_id: str,
    body: DeviceCommand,
    request: Request,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    require_role(db, user.id, home_id)
    device = _get_device(db, home_id, device_id)
    audit = {
        "user_id": user.id,
        "home_id": home_id,
        "ip_address": client_ip(request),
    }
    try:
        state = apply_command(db, device, body, audit)
    except CommandRejected as rejected:
        raise HTTPException(rejected.status_code, rejected.reason) from None
    return {"device_id": device.id, "state": state}


def apply_command(
    db: Session, device: Device, body: DeviceCommand, audit: dict[str, Any]
) -> dict[str, Any]:
    """Validate, send to the real device, store and audit one command.
    Raises CommandRejected (nothing changed). Used for groups too."""
    details = {"device_id": device.id, "command": body.command, "payload": body.payload}
    try:
        state = _new_state(db, device, body)
        try:
            send_to_device(db, device, body.command, body.payload, state)
        except DeviceUnavailable as error:
            raise CommandRejected(error.status_code, error.reason) from None
    except CommandRejected as rejected:
        record_event(
            db,
            "device_command_rejected",
            **audit,
            details={**details, "reason": rejected.reason},
        )
        raise
    device.state = json.dumps(state)
    device.last_updated = utcnow()
    db.commit()
    record_event(db, "device_command", **audit, details=details)
    return state


class DeviceLimits(BaseModel):
    model_config = ConfigDict(extra="forbid")
    min_temperature: float | None = None
    max_temperature: float | None = None


@router.put("/{device_id}/limits", dependencies=[Depends(require_csrf)])
def set_device_limits(
    home_id: str,
    device_id: str,
    body: DeviceLimits,
    request: Request,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """A thermostat's or water heater's own limits (admins). They must lie
    inside the home's limits for its type; None uses the type's limit."""
    require_role(db, user.id, home_id, Role.ADMIN)
    device = _get_device(db, home_id, device_id)
    if device.type not in LIMITED_TYPES:
        raise HTTPException(422, "only thermostats and water heaters have limits")
    home_limits = db.scalars(
        select(DeviceSafetyLimits).where(
            DeviceSafetyLimits.home_id == home_id,
            DeviceSafetyLimits.device_type == device.type,
        )
    ).first()
    if home_limits is None:
        raise HTTPException(409, "set the safety limits for this device type first")
    low, high = home_limits.min_temperature, home_limits.max_temperature
    if low is None or high is None:
        raise HTTPException(409, "set the safety limits for this device type first")
    for value in (body.min_temperature, body.max_temperature):
        if value is not None and not low <= value <= high:
            raise HTTPException(
                422, f"a device's limits must be within {low}-{high} {home_limits.unit}"
            )
    if (
        body.min_temperature is not None
        and body.max_temperature is not None
        and body.min_temperature > body.max_temperature
    ):
        raise HTTPException(422, "the lowest limit is above the highest")
    device.min_temperature = body.min_temperature
    device.max_temperature = body.max_temperature
    db.commit()
    record_event(
        db,
        "device_limits_changed",
        user_id=user.id,
        home_id=home_id,
        ip_address=client_ip(request),
        details={
            "device_id": device.id,
            "min_temperature": body.min_temperature,
            "max_temperature": body.max_temperature,
        },
    )
    return _device_out(device)
