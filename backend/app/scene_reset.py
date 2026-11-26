"""A scene's Reset: put back what the scene changed.

When a scene runs (its Run button, or a guest's), each device it touches is
noted first: what the device was like, for just what the scene's steps
change (a brightness step: the brightness; a color step: the color and
whether it was on). Reset then sends what puts each device back, only
where it still differs (a light already back as it was gets nothing), and
forgets it. A device that could not be put back is kept for another try.

Only what the scene did is put back: what each device was left like is
noted too (after the run), and a part someone changed since (the lamp they
dimmed by hand) is left as it is.

A Hue scene: the lights it sets (asked of the bridge), their power and
brightness (what the app follows of Hue lights), with what the scene sets
them to as "after".

Running the scene again within KEEP_FOR keeps what was noted first, so
Reset still goes back to before the first run; later, a run notes afresh.
Schedules run their steps without this (no Reset for them).
"""

import json
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy.orm import Session

from app.audit import record_event
from app.groups import members
from app.models import Device, DeviceGroup, Scene, utcnow

KEEP_FOR = timedelta(hours=12)

# command -> what it changes, by device type
ASPECTS: dict[str, dict[str, tuple[str, ...]]] = {
    "light": {
        "turn_on": ("power",),
        "turn_off": ("power",),
        "set_brightness": ("brightness",),
        "set_color": ("color", "power"),
        "set_color_temp": ("color", "power"),
    },
    "plug": {"turn_on": ("power",), "turn_off": ("power",)},
    "tv": {"turn_on": ("power",), "turn_off": ("power",)},
    "garage_door": {
        "open": ("door",),
        "close": ("door",),
        "light_on": ("light",),
        "light_off": ("light",),
        "laser_on": ("laser",),
        "laser_off": ("laser",),
        "lock": ("locked",),
        "unlock": ("locked",),
    },
    "thermostat": {
        "set_mode": ("mode",),
        "set_temperature": ("setpoints",),
        "set_cool_temperature": ("setpoints",),
        "set_fan": ("fan",),
        "set_hold": ("hold",),
    },
    "water_heater": {
        "set_temperature": ("target",),
        "turn_on": ("mode",),
        "turn_off": ("mode",),
        "set_mode": ("mode",),
        "set_away": ("away",),
    },
}
KEYS = (
    "on",
    "brightness",
    "color_mode",
    "color",
    "color_temp",
    "door",
    "light",
    "laser",
    "locked",
    "mode",
    "heat_setpoint",
    "cool_setpoint",
    "target_temperature",
    "fan",
    "hold",
    "enabled",
    "away",
)
HEAT_MODES = ("heat", "auto", "emergency")


def _state(device: Device) -> dict[str, Any]:
    """Its state, with what lights, plugs and TVs take when not reported."""
    from app import lights, tv

    defaults = {
        "light": lights.LIGHT_DEFAULTS,
        "plug": lights.PLUG_DEFAULTS,
        "tv": tv.DEFAULTS,
    }.get(device.type, {})
    return {**defaults, **json.loads(device.state or "{}")}


# what each aspect is, in a device's state
ASPECT_KEYS = {
    "power": ("on",),
    "brightness": ("brightness",),
    "color": ("color_mode", "color", "color_temp"),
    "door": ("door",),
    "light": ("light",),
    "laser": ("laser",),
    "locked": ("locked",),
    "mode": ("mode", "enabled"),
    "setpoints": ("heat_setpoint", "cool_setpoint", "target_temperature"),
    "fan": ("fan",),
    "hold": ("hold",),
    "target": ("target_temperature",),
    "away": ("away",),
}
DOOR_WAY = {"opening": "open", "closing": "closed"}


def _part(aspect: str, state: dict[str, Any]) -> tuple[Any, ...]:
    values = tuple(state.get(key) for key in ASPECT_KEYS[aspect])
    if aspect == "door":
        return tuple(DOOR_WAY.get(str(v), v) for v in values)
    if aspect == "color":  # only what its mode uses
        mode = state.get("color_mode")
        return (mode, state.get("color") if mode == "rgb" else state.get("color_temp"))
    return values


def _untouched(entry: dict[str, Any], now: dict[str, Any]) -> set[str]:
    """The aspects still as the scene left them (all, for a note with no
    "after", or a part the scene's "after" does not cover)."""
    after = entry.get("after")
    if after is None:
        return set(entry["aspects"])
    return {
        aspect
        for aspect in entry["aspects"]
        if not any(key in after for key in ASPECT_KEYS[aspect])
        or _part(aspect, after) == _part(aspect, now)
    }


def _targets(
    db: Session, scene: Scene
) -> dict[str, tuple[Device, set[str], dict[str, Any] | None]]:
    """device id -> (device, what the scene changes on it, what a Hue scene
    sets it to)."""
    found: dict[str, tuple[Device, set[str], dict[str, Any] | None]] = {}

    def note(
        device: Device | None, command: str, sets: dict[str, Any] | None = None
    ) -> None:
        if device is None or device.home_id != scene.home_id:
            return
        aspects = ASPECTS.get(device.type, {}).get(command)
        if aspects:
            entry = found.setdefault(device.id, (device, set(), sets))
            entry[1].update(aspects)

    for step in json.loads(scene.steps or "[]"):
        if step["kind"] == "device":
            note(db.get(Device, step["id"]), step["command"])
        elif step["kind"] == "group":
            group = db.get(DeviceGroup, step["id"])
            if group is not None and group.home_id == scene.home_id:
                for device in members(db, group):
                    note(device, step["command"])
        elif step["kind"] == "hue_scene":
            from app import hue_home

            try:
                sets = hue_home.scene_states(db, scene.home_id, step["id"])
            except hue_home.HueUnavailable:
                continue  # its run fails the same way: nothing to put back
            for device_id, values in sets.items():
                commands = ["turn_on"] + (
                    ["set_brightness"] if "brightness" in values else []
                )
                for command in commands:
                    note(db.get(Device, device_id), command, values)
    return found


def note_before(db: Session, scene: Scene) -> None:
    """Before a run: what each device it touches is like now."""
    kept: dict[str, Any] = {}
    if scene.before and scene.ran_at and utcnow() - _aware(scene.ran_at) < KEEP_FOR:
        kept = json.loads(scene.before)
    for device_id, (device, aspects, sets) in _targets(db, scene).items():
        state = _state(device)
        entry = kept.setdefault(
            device_id,
            {"aspects": [], "state": {k: state[k] for k in KEYS if k in state}},
        )
        entry["aspects"] = sorted(set(entry["aspects"]) | aspects)
        for key in KEYS:  # something it lacked at the first run
            if key in state:
                entry["state"].setdefault(key, state[key])
        # A Hue scene's lights: what it sets them to. Others: after the run.
        entry["after"] = dict(sets) if sets is not None else None
    scene.before = json.dumps(kept) if kept else None
    scene.ran_at = utcnow()
    db.commit()


def note_after(db: Session, scene: Scene) -> None:
    """After a run: what it left each device like (a Hue scene's lights
    already have theirs), so Reset leaves alone what someone changes later."""
    kept: dict[str, Any] = json.loads(scene.before or "{}")
    for device_id, entry in kept.items():
        if entry.get("after") is not None:
            continue
        device = db.get(Device, device_id)
        if device is not None:
            state = _state(device)
            entry["after"] = {k: state[k] for k in KEYS if k in state}
    scene.before = json.dumps(kept) if kept else None
    db.commit()


def _aware(when: datetime) -> datetime:
    return when if when.tzinfo else when.replace(tzinfo=UTC)


Commands = list[tuple[str, dict[str, Any]]]


def _light(before: dict[str, Any], now: dict[str, Any], aspects: set[str]) -> Commands:
    commands: Commands = []
    was_on, is_on = before.get("on"), now.get("on")
    if was_on is False and is_on is False:
        return commands  # off then and now: its color does not show
    if is_on is False and "power" not in aspects:
        return commands  # turned off since, by someone: a color would turn it on
    if "color" in aspects:
        mode = before.get("color_mode")
        if (
            mode == "rgb"
            and before.get("color")
            and (now.get("color_mode") != "rgb" or now.get("color") != before["color"])
        ):
            commands.append(("set_color", {"color": before["color"]}))
        elif (
            mode == "temp"
            and before.get("color_temp")
            and (
                now.get("color_mode") != "temp"
                or now.get("color_temp") != before["color_temp"]
            )
        ):
            commands.append(("set_color_temp", {"kelvin": before["color_temp"]}))
        if commands:
            is_on = True  # a color turns it on
    if (
        "brightness" in aspects
        and isinstance(before.get("brightness"), int)
        and before["brightness"] != now.get("brightness")
    ):
        commands.append(("set_brightness", {"brightness": before["brightness"]}))
    if (
        ("power" in aspects or commands)
        and isinstance(was_on, bool)
        and was_on != is_on
    ):
        commands.append(("turn_on" if was_on else "turn_off", {}))
    return commands


def _thermostat(
    before: dict[str, Any], now: dict[str, Any], aspects: set[str]
) -> Commands:
    commands: Commands = []
    mode = before.get("mode")
    if "mode" in aspects and mode and mode != now.get("mode"):
        commands.append(("set_mode", {"mode": mode}))
    if "setpoints" in aspects:
        if mode is None:  # a demo thermostat: only its target
            target = before.get("target_temperature")
            if target is not None and target != now.get("target_temperature"):
                commands.append(("set_temperature", {"temperature": target}))
        else:
            mode = mode if "mode" in aspects else now.get("mode")
            heat, cool = before.get("heat_setpoint"), before.get("cool_setpoint")
            heat_step, cool_step = [], []
            if (
                mode in HEAT_MODES
                and heat is not None
                and heat != now.get("heat_setpoint")
            ):
                heat_step = [("set_temperature", {"temperature": heat})]
            if cool is not None and cool != now.get("cool_setpoint"):
                if mode == "cool":
                    cool_step = [("set_temperature", {"temperature": cool})]
                elif mode == "auto":
                    cool_step = [("set_cool_temperature", {"temperature": cool})]
            # In Auto heating stays below cooling: raise cooling first.
            now_cool = now.get("cool_setpoint")
            first_cool = (
                mode == "auto"
                and heat is not None
                and now_cool is not None
                and heat >= now_cool
            )
            commands += cool_step + heat_step if first_cool else heat_step + cool_step
    for key, command in (("fan", "set_fan"), ("hold", "set_hold")):
        if key in aspects and before.get(key) and before[key] != now.get(key):
            commands.append((command, {key: before[key]}))
    return commands


def _water_heater(
    before: dict[str, Any], now: dict[str, Any], aspects: set[str]
) -> Commands:
    commands: Commands = []
    if "mode" in aspects:
        if before.get("enabled") is False and now.get("enabled") is not False:
            commands.append(("turn_off", {}))
        elif (
            before.get("enabled")
            and before.get("mode")
            and (now.get("enabled") is False or before["mode"] != now.get("mode"))
        ):
            commands.append(("set_mode", {"mode": before["mode"]}))
    target = before.get("target_temperature")
    if (
        "target" in aspects
        and target is not None
        and target != now.get("target_temperature")
    ):
        commands.append(("set_temperature", {"temperature": target}))
    if (
        "away" in aspects
        and isinstance(before.get("away"), bool)
        and before["away"] != now.get("away")
    ):
        commands.append(("set_away", {"away": before["away"]}))
    return commands


def _garage(before: dict[str, Any], now: dict[str, Any], aspects: set[str]) -> Commands:
    commands: Commands = []
    door = before.get("door")
    if "door" in aspects and door in ("open", "closed") and door != now.get("door"):
        commands.append(("open" if door == "open" else "close", {}))
    for key in ("light", "laser", "locked"):
        value = before.get(key)
        if key in aspects and isinstance(value, bool) and value != now.get(key):
            if key == "locked":
                commands.append(("lock" if value else "unlock", {}))
            else:
                commands.append((f"{key}_{'on' if value else 'off'}", {}))
    return commands


def commands_back(
    device_type: str, before: dict[str, Any], now: dict[str, Any], aspects: set[str]
) -> Commands:
    """What puts a device back as it was, for what the scene changed."""
    if device_type == "light":
        return _light(before, now, aspects)
    if device_type in ("plug", "tv"):
        was = before.get("on")
        if "power" in aspects and isinstance(was, bool) and was != now.get("on"):
            return [("turn_on" if was else "turn_off", {})]
        return []
    if device_type == "thermostat":
        return _thermostat(before, now, aspects)
    if device_type == "water_heater":
        return _water_heater(before, now, aspects)
    if device_type == "garage_door":
        return _garage(before, now, aspects)
    return []


def can_reset(scene: Scene) -> bool:
    return bool(scene.before)


def reset(db: Session, scene: Scene, user_id: str | None) -> dict[str, Any]:
    """Put back what the scene changed: {"done": n, "failed": [{"name",
    "reason"}]}. Devices put back (or already back) are forgotten."""
    from app.automation import _device_command
    from app.routes.devices import CommandRejected, apply_command

    noted: dict[str, Any] = json.loads(scene.before or "{}")
    audit = {"user_id": user_id, "home_id": scene.home_id, "ip_address": None}
    done, failed, left = 0, [], {}
    for device_id, entry in noted.items():
        device = db.get(Device, device_id)
        if device is None or device.home_id != scene.home_id:
            continue  # removed since
        now = _state(device)
        commands = commands_back(
            device.type, entry["state"], now, _untouched(entry, now)
        )
        for command, payload in commands:
            try:
                apply_command(db, device, _device_command(command, payload), audit)
                done += 1
            except CommandRejected as rejected:
                db.rollback()
                failed.append({"name": device.name, "reason": rejected.reason})
                left[device_id] = entry
                break
    scene = db.get(Scene, scene.id) or scene
    scene.before = json.dumps(left) if left else None
    db.commit()
    record_event(
        db,
        "scene_reset",
        user_id=user_id,
        home_id=scene.home_id,
        details={"scene_id": scene.id, "done": done, "failed": len(failed)},
    )
    return {"done": done, "failed": failed}
