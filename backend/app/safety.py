"""Safety limits for thermostats and water heaters (SEC-40 to SEC-42).

An owner may set limits only inside hard bounds, so a typo cannot allow a
dangerous setting. Every change is audited.
"""

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.audit import record_event
from app.models import DeviceSafetyLimits, utcnow

LIMITED_TYPES = ("thermostat", "water_heater")

# device type -> (lowest allowed minimum, highest allowed maximum), Fahrenheit.
HARD_BOUNDS_F: dict[str, tuple[float, float]] = {
    "thermostat": (40.0, 90.0),
    # Above 140 F water scalds in seconds; below 50 F risks freezing pipes.
    "water_heater": (50.0, 140.0),
}


# Owner-approved defaults (2026-10-20): unit, min, max, default target.
# Thermostat 68 F is the US DOE heating recommendation; 120 F is the CPSC
# scald-safety maximum for water heaters; below about 110 F Legionella
# grows more readily.
RECOMMENDED: dict[str, tuple[str, float, float, float]] = {
    "thermostat": ("F", 60.0, 80.0, 68.0),
    "water_heater": ("F", 110.0, 120.0, 120.0),
}


class LimitsError(ValueError):
    pass


def hard_bounds(device_type: str, unit: str) -> tuple[float, float]:
    low, high = HARD_BOUNDS_F[device_type]
    if unit == "F":
        return low, high
    return round((low - 32) * 5 / 9, 1), round((high - 32) * 5 / 9, 1)


def limits_out(limits: DeviceSafetyLimits) -> dict[str, Any]:
    return {
        "device_type": limits.device_type,
        "unit": limits.unit,
        "min_temperature": limits.min_temperature,
        "max_temperature": limits.max_temperature,
        "default_target": limits.default_target,
        "enabled": limits.enabled,
    }


def set_limits(
    db: Session,
    *,
    home_id: str,
    device_type: str,
    unit: str,
    min_temperature: float,
    max_temperature: float,
    enabled: bool,
    default_target: float | None = None,
    user_id: str | None = None,
    ip_address: str | None = None,
) -> DeviceSafetyLimits:
    """Create or replace one home's limits for a device type, and audit it.

    Raises LimitsError if the values are inconsistent or outside hard bounds.
    """
    if device_type not in LIMITED_TYPES:
        raise LimitsError(f"device type must be one of {list(LIMITED_TYPES)}")
    if unit not in ("F", "C"):
        raise LimitsError("unit must be F or C")
    if min_temperature >= max_temperature:
        raise LimitsError("min_temperature must be below max_temperature")
    if default_target is not None and not (
        min_temperature <= default_target <= max_temperature
    ):
        raise LimitsError("default_target must be within the limits")
    low, high = hard_bounds(device_type, unit)
    if min_temperature < low or max_temperature > high:
        raise LimitsError(f"{device_type} limits must stay within {low}-{high} {unit}")

    limits = db.scalars(
        select(DeviceSafetyLimits).where(
            DeviceSafetyLimits.home_id == home_id,
            DeviceSafetyLimits.device_type == device_type,
        )
    ).first()
    old = limits_out(limits) if limits else None
    if limits is None:
        limits = DeviceSafetyLimits(home_id=home_id, device_type=device_type)
        db.add(limits)
    limits.unit = unit
    limits.min_temperature = min_temperature
    limits.max_temperature = max_temperature
    limits.enabled = enabled
    limits.default_target = default_target
    limits.updated_at = utcnow()
    db.commit()
    record_event(
        db,
        "safety_limits_changed",
        user_id=user_id,
        home_id=home_id,
        ip_address=ip_address,
        details={"old": old, "new": limits_out(limits)},
    )
    return limits


def apply_recommended(
    db: Session, home_id: str, user_id: str | None, ip_address: str | None
) -> None:
    """Set the recommended limits and default targets for every limited type."""
    for device_type, (unit, low, high, target) in RECOMMENDED.items():
        set_limits(
            db,
            home_id=home_id,
            device_type=device_type,
            unit=unit,
            min_temperature=low,
            max_temperature=high,
            default_target=target,
            enabled=True,
            user_id=user_id,
            ip_address=ip_address,
        )


def initial_state(db: Session, home_id: str, device_type: str) -> dict[str, Any]:
    """State for a new device: limited types start at their default target."""
    if device_type not in LIMITED_TYPES:
        return {}
    limits = db.scalars(
        select(DeviceSafetyLimits).where(
            DeviceSafetyLimits.home_id == home_id,
            DeviceSafetyLimits.device_type == device_type,
        )
    ).first()
    if limits is None or limits.default_target is None:
        return {}
    return {"target_temperature": limits.default_target, "unit": limits.unit}
