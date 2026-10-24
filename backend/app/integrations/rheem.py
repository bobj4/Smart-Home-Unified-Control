"""Rheem EcoNet water heaters through the pyeconet library.

`connect(email, password)` is the only way the app talks to Rheem's cloud;
tests replace it with a fake. A login is reused for SESSION_SECONDS (kept in
memory only, keyed by a hash of the email and password) because Rheem
refuses logins with HTTP 429 when they come too often.
"""

import asyncio
import concurrent.futures
import hashlib
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from typing import Any, Protocol

from pyeconet import EcoNetApiInterface
from pyeconet.equipment import EquipmentType
from pyeconet.equipment.water_heater import WaterHeater, WaterHeaterOperationMode
from pyeconet.errors import (
    GenericHTTPError,
    InvalidCredentialsError,
    InvalidResponseFormat,
    PyeconetError,
)

TIMEOUT_SECONDS = 30
SESSION_SECONDS = 6 * 3600
RATE_LIMITED = "Rheem is refusing logins for now (too many attempts). Wait 15 minutes, then try once."
# hash of (email, password) -> (user token, account id, time of login)
_sessions: dict[str, tuple[str, str, float]] = {}


class RheemError(Exception):
    """EcoNet could not be reached or did not do what was asked."""


class RheemLoginError(RheemError):
    """EcoNet refused the email or password."""


@dataclass(frozen=True)
class RheemHeater:
    serial: str
    name: str
    set_point: int
    min_set_point: int
    max_set_point: int
    mode: str | None
    enabled: bool | None
    running: bool
    connected: bool
    # The rest as the EcoNet app shows it; None when the heater has no such
    # feature (or Rheem did not report it).
    modes: tuple[str, ...] = ()
    away: bool | None = None
    schedule: str | None = None  # "Following Schedule" or "Schedule overridden"
    hot_water: int | None = None  # percent of the tank
    energy_today: float | None = None
    energy_unit: str | None = None  # KWH or KBTU
    water_today: float | None = None  # gallons
    wifi: int | None = None
    alerts: int = 0
    activity: str | None = None  # what Rheem reports the heater is doing

    @property
    def status(self) -> str:
        """off, heating or idle."""
        if self.enabled is False:
            return "off"
        return "heating" if self.running else "idle"

    def state(self) -> dict[str, Any]:
        """The device state stored for this heater (temperatures in F)."""
        data = asdict(self)
        return {
            "target_temperature": data.pop("set_point"),
            "unit": "F",
            **{
                k: v
                for k, v in data.items()
                if k not in ("serial", "name", "connected")
            },
            "modes": list(self.modes),
            "status": self.status,
        }


def heater_from_equipment(heater: WaterHeater) -> RheemHeater:
    low, high = heater.set_point_limits
    mode = heater.mode
    return RheemHeater(
        serial=str(heater.serial_number),
        name=str(heater.device_name),
        set_point=int(heater.set_point),
        min_set_point=int(low),
        max_set_point=int(high),
        mode=mode.name.lower() if mode is not None else None,
        enabled=heater.enabled,
        running=is_running(_safe(lambda: heater.running_state, None)),
        connected=bool(heater.connected),
        modes=tuple(m.name.lower() for m in _safe(lambda: heater.modes, [])),
        away=_safe(lambda: bool(heater.away), None)
        if _safe(lambda: heater.supports_away, False)
        else None,
        schedule=_safe(lambda: heater.schedule_status, None),
        hot_water=_safe(lambda: heater.tank_hot_water_availability, None),
        energy_today=_safe(lambda: heater.todays_energy_usage, None),
        energy_unit=_safe(lambda: heater.energy_type, None) or None,
        water_today=_safe(lambda: heater.todays_water_usage, None),
        wifi=_safe(lambda: heater.wifi_signal, None),
        alerts=int(_safe(lambda: heater.alert_count, 0) or 0),
        activity=_activity(_safe(lambda: heater.running_state, None)),
    )


IDLE_WORDS = ("idle", "off", "standby", "not running", "waiting", "none", "false")


def _activity(raw: Any) -> str | None:
    """Rheem's running value as text (a string, or a dict on some models)."""
    if isinstance(raw, dict):
        raw = raw.get("title") or raw.get("value")
    if raw is None:
        return None
    text = str(raw).strip()
    return text or None


def is_running(raw: Any) -> bool:
    """Heating only when Rheem names an activity; an empty, missing or idle
    value means idle (pyeconet's own `running` counts a missing value as
    running)."""
    text = _activity(raw)
    if text is None or text == "0":
        return False
    lowered = text.lower()
    return not any(word in lowered for word in IDLE_WORDS)


def _safe(read: Any, default: Any) -> Any:
    """Read an optional EcoNet value: models differ in what they report."""
    try:
        value = read()
    except (AttributeError, KeyError, TypeError, ValueError, IndexError):
        return default
    return default if value is None else value


def _run_async(coro: Any) -> Any:
    """asyncio.run, or the same in a separate thread when this thread already
    runs an event loop (asyncio.run refuses to start a second one)."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(asyncio.run, coro).result()


class RheemClient(Protocol):
    def list_water_heaters(self) -> list[RheemHeater]: ...

    def set_set_point(self, serial: str, set_point: int) -> None: ...

    def set_mode(self, serial: str, mode: str) -> None: ...

    def set_away(self, serial: str, away: bool) -> None: ...

    def resume_schedule(self, serial: str) -> None: ...

    def usage(self, serial: str, days: int) -> dict[str, Any]: ...


class PyeconetClient:
    def __init__(self, email: str, password: str) -> None:
        self._email = email
        self._password = password

    def list_water_heaters(self) -> list[RheemHeater]:
        return self._run(self._list())

    def set_set_point(self, serial: str, set_point: int) -> None:
        self._run(self._command(serial, lambda h: h.set_set_point(set_point)))

    def set_mode(self, serial: str, mode: str) -> None:
        try:
            wanted = WaterHeaterOperationMode[mode.upper()]
        except KeyError:
            raise RheemError(f"unknown mode {mode}") from None
        self._run(self._command(serial, lambda h: h.set_mode(wanted)))

    def set_away(self, serial: str, away: bool) -> None:
        self._run(self._command(serial, lambda h: h.set_away_mode(away)))

    def resume_schedule(self, serial: str) -> None:
        self._run(self._command(serial, lambda h: h.resume_schedule()))

    def usage(self, serial: str, days: int) -> dict[str, Any]:
        """Energy and water use: by hour for today (days=1), else by day
        for the last `days` days, today included. A series the heater does
        not report is None."""
        return dict(self._run(self._usage(serial, days)))

    def _run(self, coro: Any) -> Any:
        try:
            return _run_async(asyncio.wait_for(coro, TIMEOUT_SECONDS))
        except InvalidCredentialsError:
            raise RheemLoginError("EcoNet refused the email or password") from None
        except GenericHTTPError as error:
            if "429" in str(error):
                raise RheemError(RATE_LIMITED) from None
            raise RheemError(f"EcoNet request failed: HTTP {error}") from None
        except (PyeconetError, OSError, TimeoutError) as error:
            raise RheemError(f"EcoNet request failed: {type(error).__name__}") from None

    def _key(self) -> str:
        return hashlib.sha256(f"{self._email}\0{self._password}".encode()).hexdigest()

    async def _login(self, reuse: bool = True) -> tuple[EcoNetApiInterface, bool]:
        """Return a logged-in API and whether it came from a saved login."""
        key = self._key()
        saved = _sessions.get(key)
        if reuse and saved and time.monotonic() - saved[2] < SESSION_SECONDS:
            api = EcoNetApiInterface(
                self._email, self._password, account_id=saved[1], user_token=saved[0]
            )
            return api, True
        api = await EcoNetApiInterface.login(self._email, self._password)
        _sessions[key] = (api.user_token, api.account_id, time.monotonic())
        return api, False

    async def _heaters(self) -> tuple[EcoNetApiInterface, list[WaterHeater]]:
        api, reused = await self._login()
        try:
            found = await api.get_equipment_by_type([EquipmentType.WATER_HEATER])
        except GenericHTTPError as error:
            # A saved login Rheem no longer accepts: log in again, once.
            if not reused or str(error) not in ("401", "403"):
                raise
            api, _ = await self._login(reuse=False)
            found = await api.get_equipment_by_type([EquipmentType.WATER_HEATER])
        return api, list(found[EquipmentType.WATER_HEATER])

    async def _list(self) -> list[RheemHeater]:
        _, heaters = await self._heaters()
        for heater in heaters:  # today's usage, where the model reports it
            for read in (heater.get_energy_usage, heater.get_water_usage):
                try:
                    await read()
                except (PyeconetError, KeyError, TypeError, ValueError):
                    pass
        return [heater_from_equipment(h) for h in heaters]

    async def _command(self, serial: str, action: Any) -> None:
        api, heaters = await self._heaters()
        heater = next((h for h in heaters if h.serial_number == serial), None)
        if heater is None:
            raise RheemError("that water heater is no longer on the EcoNet account")
        api.subscribe()  # commands go over MQTT
        try:
            deadline = time.monotonic() + 10
            client = api._mqtt_client  # noqa: SLF001 - pyeconet exposes no is_connected
            while client is None or not client.is_connected():
                if time.monotonic() > deadline:
                    raise RheemError("could not connect to EcoNet for commands")
                await asyncio.sleep(0.2)
                client = api._mqtt_client  # noqa: SLF001
            action(heater)
            await asyncio.sleep(1)  # let the publish leave before disconnecting
        finally:
            api.unsubscribe()

    async def _usage(self, serial: str, days: int) -> dict[str, Any]:
        api, heaters = await self._heaters()
        heater = next((h for h in heaters if h.serial_number == serial), None)
        if heater is None:
            raise RheemError("that water heater is no longer on the EcoNet account")
        today = datetime.now().astimezone().replace(hour=0, minute=0, second=0)
        first = today - timedelta(days=days - 1)
        day_starts = [first + timedelta(days=n) for n in range(days)]
        limit = asyncio.Semaphore(4)  # a few requests at a time

        async def report(kind: str, start: datetime) -> Any:
            async with limit:
                try:
                    return await api.get_dynamic_action(
                        _usage_request(heater, kind, start)
                    )
                except InvalidResponseFormat:
                    return None  # this heater does not report it

        unit: str | None = None
        result: dict[str, Any] = {"days": days}
        for kind, key in (("energyUsage", "energy"), ("waterUsage", "water")):
            replies = await asyncio.gather(*(report(kind, d) for d in day_starts))
            found = [_usage_values(reply, key) for reply in replies]
            if all(values is None for values in found):
                result[key] = None  # this heater does not report it
                continue
            if key == "energy":
                unit = next((u for u in map(_energy_unit, replies) if u), None)
            points: list[dict[str, Any]] = []
            for start, values in zip(day_starts, found, strict=True):
                if days == 1:
                    points = [{"label": str(h), "value": v} for h, v in values or []]
                else:  # a day Rheem has nothing for counts as none used
                    total = sum(v for _, v in values or [])
                    points.append({"label": start.date().isoformat(), "value": total})
            result[key] = points
        result["energy_unit"] = unit or "KWH"
        return result


def _usage_request(heater: WaterHeater, kind: str, start: datetime) -> dict[str, str]:
    """The request the EcoNet app (and pyeconet) sends for one day."""
    if kind == "energyUsage":
        begin = start.replace(microsecond=999000).isoformat(timespec="milliseconds")
        end = start.replace(hour=23, minute=59, second=59, microsecond=999000)
        finish = end.isoformat(timespec="milliseconds")
    else:
        begin = start.strftime("%Y-%m-%dT00:00:00.999")
        finish = start.strftime("%Y-%m-%dT23:59:59.999")
    return {
        "ACTION": "waterheaterUsageReportView",
        "device_name": f"{heater.device_id}",
        "serial_number": f"{heater.serial_number}",
        "start_date": begin,
        "end_date": finish,
        "usage_type": kind,
    }


def _usage_values(reply: Any, key: str) -> list[tuple[int, float]] | None:
    """[(hour, amount)] from a usage reply, or None if there is none."""
    try:
        data = reply["results"][f"{key}_usage"]["data"]
        return sorted((int(item["name"]), float(item["value"] or 0)) for item in data)
    except (KeyError, TypeError, ValueError):
        return None


def _energy_unit(reply: Any) -> str | None:
    try:
        return str(reply["results"]["energy_usage"]["message"].split(" ")[3]).upper()
    except (KeyError, TypeError, IndexError, AttributeError):
        return None


def connect(email: str, password: str) -> RheemClient:
    return PyeconetClient(email, password)
