"""Demo devices: added when a home turns the Demo devices integration on,
deleted when it turns it off."""

import json

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Device
from app.safety import initial_state

DEMO = [
    ("Living room lamp", "light", "Living room"),
    ("Coffee maker plug", "plug", "Kitchen"),
    ("Hall thermostat", "thermostat", "Hall"),
    ("Living room TV", "tv", "Living room"),
    ("Water heater", "water_heater", "Basement"),
]


def add_demo_devices(db: Session, home_id: str) -> int:
    """Add the demo devices the home does not have yet; returns how many."""
    have = set(
        db.scalars(
            select(Device.name).where(
                Device.home_id == home_id, Device.integration == "simulated"
            )
        )
    )
    added = 0
    for name, device_type, room in DEMO:
        if name in have:
            continue
        db.add(
            Device(
                home_id=home_id,
                integration="simulated",
                type=device_type,
                name=name,
                room=room,
                online=True,
                capabilities="{}",
                state=json.dumps(initial_state(db, home_id, device_type)),
            )
        )
        added += 1
    db.commit()
    return added


def remove_demo_devices(db: Session, home_id: str) -> int:
    """Delete every simulated device in the home; returns how many."""
    devices = list(
        db.scalars(
            select(Device).where(
                Device.home_id == home_id, Device.integration == "simulated"
            )
        )
    )
    for device in devices:
        db.delete(device)
    db.commit()
    return len(devices)
