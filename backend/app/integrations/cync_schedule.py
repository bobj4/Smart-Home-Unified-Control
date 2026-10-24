"""Cync thermostat schedules: the data point format, from the Cync app 6.24
(com.gelighting.cbygekit ThermostatScheduleSetDataPoint and
TemperatureReadMethodScheduleDataPoint). See docs/CYNC-THERMOSTAT.md.

Weekly set point schedules: one data point per mode and day.
  Heat 63-69, Cool 70-76, Auto 77-83; Monday is +0 ... Sunday is +6.
  Setting names Sched_Heat_Mon ... Sched_Auto_Sun.
  Value: bytes, a list of periods; a day with no periods is the single byte 0xFF.
  Heat/Cool period: hour(1) minute(1) unit(1: 0 F, 1 C) temperature(2, x100)
  Auto period:      hour(1) minute(1) unit(1) heat(2, x100) cool(2, x100)

Which sensors the thermostat reads, by time of day: one data point per day.
  37-43, Monday +0 ... Sunday +6. Setting names Temp_Read_Schd_Mon ... Sun.
  Value: bytes, 0xFF for none, else periods of
  hour(1) minute(1) method(1: 0 thermostat, 1 remote sensor, 2 all, 0xFF none)
  sensor(7: which remote sensor, for method 1; zeros otherwise).

These are "settings": the thermostat does not include them in a probe reply.
The app asks for each by writing its name to ReadSetting (point 84).
Pure functions only: no network here.
"""

import struct
from typing import Any

DAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")  # offset 0..6
DAY_NAMES = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")
KINDS = {"heat": 63, "cool": 70, "auto": 77}
SENSOR_BASE = 37
READ_SETTING = 84
EMPTY = b"\xff"
METHODS = {0: "thermostat", 1: "sensor", 2: "all"}
METHOD_CODES = {name: code for code, name in METHODS.items()}


class ScheduleError(ValueError):
    """A schedule the thermostat would not accept, or bytes that do not parse."""


def schedule_index(kind: str, day: str) -> int:
    return KINDS[kind] + DAYS.index(day)


def schedule_name(kind: str, day: str) -> str:
    return f"Sched_{kind.capitalize()}_{DAY_NAMES[DAYS.index(day)]}"


def sensor_index(day: str) -> int:
    return SENSOR_BASE + DAYS.index(day)


def sensor_name(day: str) -> str:
    return f"Temp_Read_Schd_{DAY_NAMES[DAYS.index(day)]}"


def _temperature_f(raw: int, unit: int) -> float:
    value = raw / 100
    return round(value * 9 / 5 + 32, 1) if unit == 1 else round(value, 1)


def parse_schedule(kind: str, data: bytes) -> list[dict[str, Any]]:
    """Periods of one day, temperatures in F. Like the app, a trailing
    incomplete period (or the lone 0xFF of an empty day) is ignored."""
    size = 7 if kind == "auto" else 5
    periods = []
    for start in range(0, len(data) - size + 1, size):
        chunk = data[start : start + size]
        hour, minute, unit = chunk[0], chunk[1], chunk[2]
        if hour > 23 or minute > 59 or unit > 1:
            raise ScheduleError(f"not a schedule period: {chunk.hex()}")
        period: dict[str, Any] = {"time": f"{hour:02d}:{minute:02d}"}
        first = struct.unpack(">H", chunk[3:5])[0]
        if kind == "auto":
            second = struct.unpack(">H", chunk[5:7])[0]
            period["heat"] = _temperature_f(first, unit)
            period["cool"] = _temperature_f(second, unit)
        else:
            period[kind] = _temperature_f(first, unit)
        periods.append(period)
    return periods


def _time(text: str) -> tuple[int, int]:
    try:
        hour, minute = (int(part) for part in text.split(":"))
    except ValueError:
        raise ScheduleError(f"time must be HH:MM, not {text!r}") from None
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        raise ScheduleError(f"time out of range: {text}")
    return hour, minute


def _hundredths(value: Any, unit: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise ScheduleError("temperatures must be numbers")
    degrees = (value - 32) * 5 / 9 if unit == "C" else value
    return int(round(degrees * 100))


def encode_schedule(kind: str, periods: list[dict[str, Any]], unit: str = "F") -> bytes:
    """The bytes the app writes for one day (temperatures given in F, written
    in the thermostat's own unit). Periods must be in time order."""
    if not periods:
        return EMPTY
    out = bytearray()
    last = -1
    for period in periods:
        hour, minute = _time(str(period.get("time", "")))
        if hour * 60 + minute <= last:
            raise ScheduleError("periods must be in time order, one per time")
        last = hour * 60 + minute
        out += bytes([hour, minute, 1 if unit == "C" else 0])
        if kind == "auto":
            heat, cool = period.get("heat"), period.get("cool")
            out += struct.pack(">HH", _hundredths(heat, unit), _hundredths(cool, unit))
        else:
            out += struct.pack(">H", _hundredths(period.get(kind), unit))
    return bytes(out)


def parse_sensor_schedule(data: bytes) -> list[dict[str, Any]]:
    """Which sensors are read from each time of the day."""
    periods = []
    for start in range(0, len(data) - 9, 10):
        chunk = data[start : start + 10]
        if chunk[2] == 0xFF:
            continue
        method = METHODS.get(chunk[2])
        if method is None or chunk[0] > 23 or chunk[1] > 59:
            raise ScheduleError(f"not a sensor period: {chunk.hex()}")
        periods.append(
            {
                "time": f"{chunk[0]:02d}:{chunk[1]:02d}",
                "read": method,
                "sensor": chunk[3:10].hex() if method == "sensor" else None,
            }
        )
    return periods
