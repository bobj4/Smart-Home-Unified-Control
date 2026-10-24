"""Guests: the role below member, with access an admin picks per guest.

A guest's membership role is "guest", which is not a Role, so every
existing home route (require_role) refuses them: deny by default. They use
only the guest routes (app/routes/guest.py), which check GuestAccess here
on every request. The server enforces it; the web page only follows it.

What each permission allows:
  light_power     turn lights and plugs on and off
  light_settings  brightness and colour of lights
  thermostat_ids  full control of those thermostats (mode, set points, fan,
                  hold), within the safety limits; not their schedule
  water_heater    control of the water heaters, within the safety limits
  cameras         the Cameras page (Frigate cameras and events)
  show_blocked    devices they may not use are shown greyed out (True) or
                  hidden (False); their state is never sent either way
"""

import json
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.authorization import require_role
from app.models import GUEST_ROLE, Device, GuestAccess, Home, HomeMembership, Role, User

LIGHT_POWER_TYPES = ("light", "plug")
LIGHT_POWER_COMMANDS = ("turn_on", "turn_off")
LIGHT_SETTING_COMMANDS = ("set_brightness", "set_color_temp", "set_color")
FLAGS = ("light_power", "light_settings", "cameras", "water_heater", "show_blocked")


def membership(db: Session, user_id: str, home_id: str) -> HomeMembership | None:
    return db.scalars(
        select(HomeMembership).where(
            HomeMembership.user_id == user_id, HomeMembership.home_id == home_id
        )
    ).first()


def access_for(db: Session, home_id: str, user_id: str) -> GuestAccess:
    """The guest's access row (nothing allowed until an admin picks)."""
    row = db.scalars(
        select(GuestAccess).where(
            GuestAccess.home_id == home_id, GuestAccess.user_id == user_id
        )
    ).first()
    return row or GuestAccess(home_id=home_id, user_id=user_id, thermostat_ids="[]")


def require_guest(db: Session, user: User, home_id: str) -> GuestAccess:
    """The caller's access as a guest of this home, or raise (404 if not in
    the home, 403 if not a guest or two-factor is required and off)."""
    member = membership(db, user.id, home_id)
    if member is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found")
    if member.role != GUEST_ROLE:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Forbidden")
    home = db.get(Home, home_id)
    if home is not None and home.require_two_factor and not user.is_totp_enabled:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "This home requires two-factor login. Turn it on in My account.",
        )
    return access_for(db, home_id, user.id)


def thermostats(access: GuestAccess) -> list[str]:
    try:
        ids = json.loads(access.thermostat_ids or "[]")
    except ValueError:
        return []
    return [str(i) for i in ids] if isinstance(ids, list) else []


def access_out(access: GuestAccess) -> dict[str, Any]:
    return {
        **{flag: bool(getattr(access, flag)) for flag in FLAGS},
        "thermostat_ids": thermostats(access),
    }


def can_see(access: GuestAccess, device: Device) -> bool:
    """Whether the guest may use the device at all."""
    if device.type in LIGHT_POWER_TYPES:
        return bool(
            access.light_power or (device.type == "light" and access.light_settings)
        )
    if device.type == "thermostat":
        return device.id in thermostats(access)
    if device.type == "water_heater":
        return bool(access.water_heater)
    return False  # TVs, sensors, cameras as devices: not for guests


def allowed(access: GuestAccess, device: Device, command: str) -> bool:
    """Whether the guest may send this command to this device."""
    if device.type in LIGHT_POWER_TYPES and command in LIGHT_POWER_COMMANDS:
        return bool(access.light_power)
    if device.type == "light" and command in LIGHT_SETTING_COMMANDS:
        return bool(access.light_settings)
    if device.type in ("thermostat", "water_heater"):
        return can_see(access, device)  # the command checks run after this
    return False


def require_camera_viewer(db: Session, user: User, home_id: str) -> None:
    """Cameras: operators and up, or a guest allowed to see them."""
    member = membership(db, user.id, home_id)
    if member is not None and member.role == GUEST_ROLE:
        if not require_guest(db, user, home_id).cameras:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Forbidden")
        return
    require_role(db, user.id, home_id, Role.OPERATOR)
