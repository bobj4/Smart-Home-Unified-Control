"""Device groups: listing, editing, importing from Cync, and commands sent
to every device in a group."""

import json
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Device, DeviceGroup, Room

GROUP_COMMANDS = (
    "turn_on",
    "turn_off",
    "set_brightness",
    "set_color_temp",
    "set_color",
)


def members(db: Session, group: DeviceGroup) -> list[Device]:
    """The group's devices that still exist in its home, in stored order."""
    ids = [str(i) for i in json.loads(group.device_ids or "[]")]
    if not ids:
        return []
    found = {
        d.id: d
        for d in db.scalars(
            select(Device).where(Device.home_id == group.home_id, Device.id.in_(ids))
        )
    }
    return [found[i] for i in ids if i in found]


def group_out(db: Session, group: DeviceGroup) -> dict[str, Any]:
    devices = members(db, group)
    states = [json.loads(d.state or "{}") for d in devices]
    lights = [
        s
        for d, s in zip(devices, states, strict=True)
        if d.type == "light" and d.online
    ]
    on = any(bool(s.get("on")) for s in states)
    # The group's light settings show what its first connected light shows.
    first = lights[0] if lights else {}
    state = {
        "on": on,
        **{
            k: first[k]
            for k in ("brightness", "color_mode", "color_temp", "color")
            if k in first
        },
    }
    room = group.room or next((d.room for d in devices if d.room), None)
    return {
        "id": group.id,
        "name": group.name,
        "source": group.source,
        "room": room,
        "device_ids": [d.id for d in devices],
        "on": on,
        "online": any(d.online for d in devices),
        "brightness": max((int(s.get("brightness", 0)) for s in lights), default=None),
        "has_lights": any(d.type == "light" for d in devices),
        "state": state,
    }


def list_groups(db: Session, home_id: str) -> list[DeviceGroup]:
    return list(
        db.scalars(
            select(DeviceGroup)
            .where(DeviceGroup.home_id == home_id, DeviceGroup.deleted.is_(False))
            .order_by(DeviceGroup.name)
        )
    )


def check_devices(db: Session, home_id: str, device_ids: list[str]) -> list[str]:
    """Only devices of this home; duplicates removed, order kept."""
    unique = list(dict.fromkeys(device_ids))
    if not unique:
        return []
    found = set(
        db.scalars(
            select(Device.id).where(Device.home_id == home_id, Device.id.in_(unique))
        )
    )
    missing = [i for i in unique if i not in found]
    if missing:
        raise ValueError("a device in the list is not in this home")
    return unique


def import_cync(db: Session, home_id: str, groups: list[Any]) -> int:
    """Cync rooms become rooms here (devices without a room get theirs);
    Cync groups become groups, once: later edits here are kept and a deleted
    one does not come back. Returns how many groups were added."""
    known = set(
        db.scalars(
            select(DeviceGroup.external_id).where(
                DeviceGroup.home_id == home_id, DeviceGroup.source == "cync"
            )
        )
    )
    by_external = {
        d.external_id: d
        for d in db.scalars(
            select(Device).where(
                Device.home_id == home_id, Device.integration == "cync"
            )
        )
    }
    added = 0
    for info in groups:
        devices = [by_external[x] for x in info.device_ids if x in by_external]
        for device in devices:
            if not device.room and info.room:
                device.room = info.room
        if info.room:
            ensure_room(db, home_id, info.room)
        if info.id.startswith("room:") or info.id in known or not devices:
            continue  # a Cync room is a room here, not a group
        db.add(
            DeviceGroup(
                home_id=home_id,
                name=info.name or "Cync group",
                source="cync",
                external_id=info.id,
                room=info.room,
                device_ids=json.dumps([d.id for d in devices]),
            )
        )
        added += 1
    db.commit()
    return added


def ensure_room(db: Session, home_id: str, name: str) -> None:
    name = name.strip()[:50]
    if not name:
        return
    exists = db.scalars(
        select(Room.id).where(Room.home_id == home_id, Room.name == name)
    ).first()
    if exists is None:
        db.add(Room(home_id=home_id, name=name))
        db.flush()


def room_names(db: Session, home_id: str) -> list[str]:
    """Rooms made here, plus any room a device or group names."""
    names = set(db.scalars(select(Room.name).where(Room.home_id == home_id)))
    names |= {
        r for r in db.scalars(select(Device.room).where(Device.home_id == home_id)) if r
    }
    names |= {
        r
        for r in db.scalars(
            select(DeviceGroup.room).where(
                DeviceGroup.home_id == home_id, DeviceGroup.deleted.is_(False)
            )
        )
        if r
    }
    return sorted(names, key=str.lower)


def set_device_group(
    db: Session, home_id: str, device_id: str, group_id: str | None
) -> None:
    """Put the device in exactly that group (or in none)."""
    for group in list_groups(db, home_id):
        ids = [i for i in json.loads(group.device_ids or "[]") if i != device_id]
        if group.id == group_id:
            ids.append(device_id)
        group.device_ids = json.dumps(ids)
    db.commit()
