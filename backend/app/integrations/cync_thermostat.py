"""The Cync thermostat over Cync's cloud connection (pycync does not support it).

Protocol from docs/CYNC-THERMOSTAT.md, confirmed for reading by the owner's
probe (2026-10-23): the thermostat answers a "probe" (packet type 10) with
all its data points. Writing uses a "set" packet (type 3) with the same
entries; that part is unconfirmed, so every write is followed by a probe and
the caller checks that the thermostat now reports the new value.

Packets go over pycync's open connection (Cync allows one per account):
`attach` hooks the replies, `ThermostatLink` sends probes and writes.
"""

import asyncio
import contextlib
import json
import struct
from collections.abc import Callable
from typing import Any

PROBE, SET, SYNC = 10, 3, 4
REPLY_SECONDS = 10
SETTING_SECONDS = 5  # for each ReadSetting answer
READ_SETTING = 84

# Data points (index): what the thermostat reports, and what the app writes.
FIRMWARE, WIFI, TEMPERATURE, HUMIDITY, MODE, FAN = 0, 2, 4, 5, 6, 8
HEAT_SETPOINT, HVAC_TYPE, RUN_MODE, SENSORS = 10, 12, 16, 87
COOL_SETPOINT, WORK_STATUS, FILTER = 91, 96, 106
MODE_SET, FAN_SET, HEAT_SET, COOL_SET, HOLD_SET = 7, 9, 11, 92, 17
# A write and the point that reports it back.
REPORTED_BY = {
    MODE_SET: MODE,
    FAN_SET: FAN,
    HEAT_SET: HEAT_SETPOINT,
    COOL_SET: COOL_SETPOINT,
    HOLD_SET: RUN_MODE,
}

MODES = {0: "off", 1: "cool", 2: "heat", 3: "auto", 4: "eco", 5: "emergency"}
MODE_CODES = {name: code for code, name in MODES.items()}
FANS = {0: "auto", 1: "on"}
FAN_CODES = {name: code for code, name in FANS.items()}
HOLDS = {0: "schedule", 1: "permanent", 2: "temporary"}
HOLD_CODES = {name: code for code, name in HOLDS.items()}
WORK = {0: "idle", 1: "cooling", 2: "heating"}
SYSTEMS = {
    1: "Cool only (1 stage)",
    2: "Heat only (1 stage)",
    3: "Heat and cool (1 stage)",
    4: "Heat pump (1 stage)",
    5: "Heat pump (2 stages)",
    6: "Heat pump with aux heat",
    7: "Cool only (2 stages)",
    8: "Heat only (2 stages)",
    9: "Heat and cool (2 stages)",
    10: "None",
}
HEATS, COOLS, HEAT_PUMPS = {2, 3, 4, 5, 6, 8, 9}, {1, 3, 4, 5, 6, 7, 9}, {4, 5, 6}


def packet(kind: int, body: bytes) -> bytes:
    return bytes([(kind << 4) | 3]) + struct.pack(">I", len(body)) + body


def probe_packet(device_id: int, msg_id: int) -> bytes:
    return packet(PROBE, struct.pack(">IH", device_id, msg_id) + b"\x00")


Value = int | str | bytes


def entry(index: int, value: Value) -> bytes:
    """One write entry: ints as 4 bytes (header 0x4004), text as UTF-8
    (0x9000 | length), bytes as they are (0xA000 | length)."""
    if isinstance(value, bytes):
        return bytes([index]) + struct.pack(">H", 0xA000 | len(value)) + value
    if isinstance(value, str):
        raw = value.encode()
        return bytes([index]) + struct.pack(">H", 0x9000 | len(raw)) + raw
    return bytes([index]) + struct.pack(">Hi", 0x4004, value)


def set_packet(device_id: int, msg_id: int, entries: list[tuple[int, Value]]) -> bytes:
    body = struct.pack(">IH", device_id, msg_id) + b"\x06"
    return packet(SET, body + b"".join(entry(i, v) for i, v in entries))


def _value(nibble: int, raw: bytes) -> Any:
    if nibble == 0:
        return raw[0] if len(raw) == 1 else raw.hex()
    if nibble in (1, 2) and len(raw) == 2:
        return struct.unpack(">h", raw)[0]
    if 3 <= nibble <= 6 and len(raw) == 4:
        return struct.unpack(">i", raw)[0]
    if nibble in (7, 8) and len(raw) == 4:
        return round(struct.unpack(">f", raw)[0], 3)
    if nibble == 9:
        return raw.decode("utf-8", "replace")
    return raw.hex()


def parse_entries(data: bytes) -> dict[int, Any]:
    """index(1) header(2) value, header = type nibble << 12 | length."""
    points: dict[int, Any] = {}
    i = 0
    while i + 3 <= len(data):
        index = data[i]
        header = struct.unpack(">H", data[i + 1 : i + 3])[0]
        length = header & 0x0FFF
        raw = data[i + 3 : i + 3 + length]
        if len(raw) != length:
            break
        points[index] = _value(header >> 12, raw)
        i += 3 + length
    return points


def parse_probe_reply(data: bytes) -> dict[int, Any] | None:
    """A probe reply after the device id: msgId(2) code(1) flags(1), then
    (flag bit 0) a 2-byte name length and name, then the data points."""
    if len(data) < 4 or data[2] != 0:
        return None
    flags, rest = data[3], bytes(data[4:])
    if flags & 1:
        if len(rest) < 2:
            return None
        rest = rest[2 + int.from_bytes(rest[:2], "big") :]
    points = parse_entries(rest)
    return points or None


def temperature_f(text: Any) -> float | None:
    """'67.5F' -> 67.5; '20.0C' -> 68.0; anything else -> None."""
    if not isinstance(text, str) or len(text) < 2:
        return None
    try:
        number = float(text[:-1])
    except ValueError:
        return None
    unit = text[-1].upper()
    if unit == "C":
        return round(number * 9 / 5 + 32, 1)
    return number if unit == "F" else None


def format_temperature(value_f: float, unit: str) -> str:
    """The text the thermostat takes: one decimal and its own unit."""
    if unit == "C":
        return f"{(value_f - 32) * 5 / 9:.1f}C"
    return f"{value_f:.1f}F"


def _pin(value: Any) -> str | None:
    """A remote sensor's PIN code as the 6 digits schedules refer to it by."""
    if isinstance(value, int) and not isinstance(value, bool) and 0 <= value < 10**6:
        return f"{value:06d}"
    return None


def _sensors(text: Any) -> list[dict[str, Any]]:
    if not isinstance(text, str) or ":" not in text:
        return []
    try:
        found = json.loads(text.split(":", 1)[1])
    except ValueError:
        return []
    sensors = []
    for raw in found if isinstance(found, list) else []:
        if not isinstance(raw, dict) or raw.get("Type") in (None, "None"):
            continue
        sensors.append(
            {
                "name": "Thermostat"
                if raw.get("Type") == "internal"
                else "Remote sensor",
                "temperature": temperature_f(raw.get("Temperature")),
                "humidity": raw.get("Humidity"),
                "battery": raw.get("Batt"),
                "active": bool(raw.get("Active")),
                "pin": _pin(raw.get("PinCode")),
            }
        )
    return sensors


def modes_for(system: int | None) -> list[str]:
    if system == 10:
        return ["off"]
    heat = system is None or system in HEATS
    cool = system is None or system in COOLS
    modes = ["off"] + (["heat"] if heat else []) + (["cool"] if cool else [])
    modes += (["auto"] if heat and cool else []) + ["eco"]
    return modes + (["emergency"] if system in HEAT_PUMPS else [])


def thermostat_state(points: dict[int, Any]) -> dict[str, Any]:
    """The device state from a full report (temperatures in F)."""
    mode = MODES.get(points.get(MODE))  # type: ignore[arg-type]
    heat = temperature_f(points.get(HEAT_SETPOINT))
    cool = temperature_f(points.get(COOL_SETPOINT))
    cool = cool if cool else None  # 0.0 means "not used"
    system = points.get(HVAC_TYPE)
    filter_info: dict[str, Any] = {}
    with contextlib.suppress(ValueError, TypeError):
        filter_info = json.loads(points.get(FILTER) or "{}")
    raw_temperature = points.get(TEMPERATURE)
    status = WORK.get(points.get(WORK_STATUS))  # type: ignore[arg-type]
    return {
        "current_temperature": temperature_f(raw_temperature),
        "humidity": points.get(HUMIDITY),
        "mode": mode,
        "modes": modes_for(system if isinstance(system, int) else None),
        "fan": FANS.get(points.get(FAN)),  # type: ignore[arg-type]
        "heat_setpoint": heat,
        "cool_setpoint": cool,
        "target_temperature": cool if mode == "cool" else heat,
        "unit": "F",
        "device_unit": "C" if str(raw_temperature or "").endswith("C") else "F",
        "status": "off" if mode == "off" else status,
        "system": SYSTEMS.get(system) if isinstance(system, int) else None,
        "hold": HOLDS.get(points.get(RUN_MODE)),  # type: ignore[arg-type]
        "filter_hours": filter_info.get("Runtime"),
        "filter_reset": str(
            filter_info.get("ResetData") or filter_info.get("ResetDate") or ""
        )[:10]
        or None,
        "sensors": _sensors(points.get(SENSORS)),
        "firmware": points.get(FIRMWARE),
        "wifi": points.get(WIFI),
    }


def parse_push(body: bytes) -> tuple[int, dict[int, Any]] | None:
    """A device push (SYNC, no response bit): deviceId(4) msgId(2) flags(1),
    an optional name (flag bit 0: 2-byte length, name), then data points."""
    if len(body) < 7:
        return None
    device_id = struct.unpack(">I", body[:4])[0]
    flags, rest = body[6], bytes(body[7:])
    if flags & 1:
        if len(rest) < 2:
            return None
        rest = rest[2 + int.from_bytes(rest[:2], "big") :]
    return device_id, parse_entries(rest)


# Links whose thermostats' raw packets are watched (see _watch_raw_packets).
_raw_links: list["ThermostatLink"] = []


def _watch_raw_packets() -> None:
    """pycync drops the thermostat's pushes (it cannot parse them), so look
    at every packet before pycync parses it. Installed once per process."""
    from pycync.tcp import packet_parser

    original = packet_parser.parse_packet
    if getattr(original, "thermostat_watch", False):
        return

    def parse_packet(packet: Any, user_id: int) -> Any:
        for link in list(_raw_links):
            with contextlib.suppress(Exception):  # never break pycync
                link.raw(bytes(packet))
        return original(packet, user_id)

    parse_packet.thermostat_watch = True  # type: ignore[attr-defined]
    packet_parser.parse_packet = parse_packet


class ThermostatLink:
    """Probes, writes and setting reads over one open pycync connection."""

    def __init__(self, api: Any, on_points: Callable[[int, dict[int, Any]], None]):
        self.tcp = api._command_client._tcp_manager  # noqa: SLF001 - no public way in
        self.on_points = on_points
        self.ids: set[int] = set()
        self._msg = 1000
        self._waiting: dict[int, list[asyncio.Future[dict[int, Any]]]] = {}
        # (device id, setting name) -> futures waiting for its ReadSetting answer
        self._settings: dict[tuple[int, str], list[asyncio.Future[Any]]] = {}

    def raw(self, packet: bytes) -> None:
        """A whole packet as it arrived: answers to ReadSetting requests."""
        if len(packet) < 5 or packet[0] >> 4 != SYNC or packet[0] & 8:
            return
        found = parse_push(packet[5:])
        if found is None or found[0] not in self.ids:
            return
        device_id, points = found
        reply = points.get(READ_SETTING)
        if not isinstance(reply, str):
            return
        try:
            answer = json.loads(reply)
        except ValueError:
            return
        if not isinstance(answer, dict):
            return
        for name, value in answer.items():
            for future in self._settings.pop((device_id, str(name)), []):
                if not future.done():
                    future.set_result(value)

    async def read_settings(self, device_id: int, names: list[str]) -> dict[str, Any]:
        """Ask for each setting by name (a write of the name to ReadSetting,
        which changes nothing) and collect the answers. A setting that is not
        answered in time is left out."""
        loop = asyncio.get_running_loop()
        found: dict[str, Any] = {}
        for name in names:
            future: asyncio.Future[Any] = loop.create_future()
            self._settings.setdefault((device_id, name), []).append(future)
            request = set_packet(device_id, self._next(), [(READ_SETTING, name)])
            await self.tcp._send_request(request)  # noqa: SLF001
            try:
                found[name] = await asyncio.wait_for(future, SETTING_SECONDS)
            except TimeoutError:
                self._settings.pop((device_id, name), None)
        return found

    async def write_settings(
        self, device_id: int, entries: list[tuple[int, Value]], names: list[str]
    ) -> dict[str, Any]:
        """Write settings (schedules) in one set packet, then read them back
        by name: returns what the thermostat now holds."""
        await self.tcp._send_request(set_packet(device_id, self._next(), entries))  # noqa: SLF001
        await asyncio.sleep(2)
        return await self.read_settings(device_id, names)

    def _next(self) -> int:
        self._msg = self._msg % 65000 + 1
        return self._msg

    def handle(self, message: Any) -> None:
        if message.message_type != PROBE or not message.is_response:
            return
        if message.device_id not in self.ids:
            return
        points = parse_probe_reply(bytes(message.data or b""))
        if points is None:
            return
        self.on_points(message.device_id, points)
        for future in self._waiting.pop(message.device_id, []):
            if not future.done():
                future.set_result(points)

    async def probe_all(self) -> None:
        for device_id in sorted(self.ids):
            await self.tcp._send_request(probe_packet(device_id, self._next()))  # noqa: SLF001

    async def write(
        self, device_id: int, entries: list[tuple[int, Value]]
    ) -> dict[int, Any]:
        """Send the entries, then probe; returns what the thermostat reports."""
        await self.tcp._send_request(set_packet(device_id, self._next(), entries))  # noqa: SLF001
        await asyncio.sleep(2)
        future: asyncio.Future[dict[int, Any]] = (
            asyncio.get_running_loop().create_future()
        )
        self._waiting.setdefault(device_id, []).append(future)
        await self.tcp._send_request(probe_packet(device_id, self._next()))  # noqa: SLF001
        return await asyncio.wait_for(future, REPLY_SECONDS)


def attach(
    api: Any, on_points: Callable[[int, dict[int, Any]], None]
) -> ThermostatLink:
    """Hook thermostat replies on an open connection; pycync still gets every
    message. Re-attaching replaces the earlier hook."""
    link = ThermostatLink(api, on_points)
    tcp = link.tcp
    original = getattr(tcp._client_callback, "original", tcp._client_callback)  # noqa: SLF001

    async def hook(message: Any) -> None:
        with contextlib.suppress(Exception):  # never break pycync's handling
            link.handle(message)
        await original(message)

    hook.original = original  # type: ignore[attr-defined]
    tcp._client_callback = hook  # noqa: SLF001
    old = getattr(api, "thermostat_link", None)
    if old in _raw_links:
        _raw_links.remove(old)
    _raw_links.append(link)
    _watch_raw_packets()
    api.thermostat_link = link
    return link


def detach(api: Any) -> None:
    """Stop watching a closed connection's packets."""
    link = getattr(api, "thermostat_link", None)
    if link in _raw_links:
        _raw_links.remove(link)


def confirmed(entries: list[tuple[int, int | str]], points: dict[int, Any]) -> bool:
    """Whether the report shows every written value."""
    for index, value in entries:
        reported = points.get(REPORTED_BY.get(index, index))
        if isinstance(value, str):
            want, got = temperature_f(value), temperature_f(reported)
            if want is None or got is None or abs(want - got) > 0.05:
                return False
        elif reported != value:
            return False
    return True
