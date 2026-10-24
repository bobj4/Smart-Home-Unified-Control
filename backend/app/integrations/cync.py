"""GE Cync lights and plugs, through the pycync library (Cync's cloud).

Cync has no published API; pycync follows what the Cync app does. The
functions here are the only way the app talks to Cync; tests replace them.

Login: email and password. Cync usually emails a 6-digit code first
(CyncCodeSent); logging in again with the code returns tokens, which the
caller keeps encrypted. The password itself is not kept.
Commands go through Cync's server to a Cync device that is on Wi-Fi, which
passes them on over Bluetooth to the others.
The thermostat is not supported by pycync: it is listed here, and read and
set through app.integrations.cync_thermostat over the same connection.
"""

import asyncio
import concurrent.futures
import contextlib
from collections.abc import Callable, Coroutine
from dataclasses import dataclass
from typing import Any

import aiohttp
from pycync import Auth, Cync, CyncLight, CyncPlug, User
from pycync.devices.capabilities import CyncCapability
from pycync.devices.device_types import DeviceType
from pycync.exceptions import (
    AuthFailedError,
    NoHubConnectedError,
    TwoFactorRequiredError,
    UnsupportedCapabilityError,
)
from pycync.exceptions import CyncError as PycyncError

from app.integrations import cync_thermostat

TIMEOUT_SECONDS = 40
STATE_WAIT_SECONDS = 20  # for the first status report
STATE_SETTLE_SECONDS = 2  # for the remaining status pages


class CyncError(Exception):
    """Cync could not be reached or did not carry out the request."""


class CyncCodeSent(CyncError):
    """Cync emailed a code: log in again with it."""


class CyncLoginError(CyncError):
    """Cync refused the login, or the saved login has expired."""


class CyncUnsupported(CyncError):
    """This device cannot do that (for example colour on a white-only bulb)."""


@dataclass(frozen=True)
class CyncDeviceInfo:
    id: str  # "<cync home id>-<mesh id>", stable for the device
    name: str
    kind: str  # "light", "plug" or "thermostat"
    online: bool
    dimming: bool
    white: bool  # colour temperature
    color: bool
    mac: str | None = None
    cloud_id: int | None = None  # the thermostat's id in Cync's cloud


def _tokens(user: Any) -> dict[str, Any]:
    return {
        "access_token": user.access_token,
        "refresh_token": user.refresh_token,
        "authorize": user.authorize,
        "user_id": user.user_id,
        "expires_at": user.expires_at,
    }


def _user(tokens: dict[str, Any]) -> Any:
    return User(
        tokens["access_token"],
        tokens["refresh_token"],
        tokens["authorize"],
        tokens["user_id"],
        expires_at=tokens["expires_at"],
    )


def is_thermostat(device: Any) -> bool:
    return getattr(device, "device_type", None) == DeviceType.THERMOSTAT


def _info(device: Any) -> CyncDeviceInfo:
    if is_thermostat(device):
        return CyncDeviceInfo(
            id=str(device.unique_id),
            name=str(device.name or "Thermostat")[:100],
            kind="thermostat",
            online=bool(device.is_online),
            dimming=False,
            white=False,
            color=False,
            mac=_mac(getattr(device, "mac", None)),
            cloud_id=int(device.device_id),
        )
    caps = device.capabilities
    is_light = isinstance(device, CyncLight)
    return CyncDeviceInfo(
        id=str(device.unique_id),
        name=str(device.name or "Cync device")[:100],
        kind="light" if is_light else "plug",
        online=bool(device.is_online),
        dimming=is_light and CyncCapability.DIMMING in caps,
        white=is_light and CyncCapability.CCT_COLOR in caps,
        color=is_light and CyncCapability.RGB_COLOR in caps,
        mac=_mac(getattr(device, "mac", None)),
    )


@dataclass(frozen=True)
class CyncGroupInfo:
    id: str  # "room:<home>-<room id>" or "group:<home>-<group id>"
    name: str
    room: str | None  # the Cync room's name (for a room: its own name)
    device_ids: tuple[str, ...]


def _groups(api: Any) -> list[CyncGroupInfo]:
    found = []
    for home in api.get_homes():
        for room in home.rooms:
            subgroups = list(getattr(room, "groups", []) or [])
            members = list(room.devices) + [d for g in subgroups for d in g.devices]
            found.append(
                CyncGroupInfo(
                    id=f"room:{home.home_id}-{room.room_id}",
                    name=str(room.name)[:100],
                    room=str(room.name)[:50],
                    device_ids=tuple(str(d.unique_id) for d in members),
                )
            )
            for group in subgroups:
                found.append(
                    CyncGroupInfo(
                        id=f"group:{home.home_id}-{group.group_id}",
                        name=str(group.name)[:100],
                        room=str(room.name)[:50],
                        device_ids=tuple(str(d.unique_id) for d in group.devices),
                    )
                )
    return found


def _mac(raw: Any) -> str | None:
    text = str(raw or "").replace(":", "").replace("-", "").upper()
    if len(text) != 12:
        return None
    return ":".join(text[i : i + 2] for i in range(0, 12, 2))


def _state(device: Any) -> dict[str, Any] | None:
    """What the device reported, in pycync's terms (1-100 colour temperature),
    or None if it has not reported yet."""
    try:
        state: dict[str, Any] = {"on": bool(device.is_on)}
        if not isinstance(device, CyncLight):
            return state
        caps = device.capabilities
        if CyncCapability.DIMMING in caps and device.brightness is not None:
            state["brightness"] = int(device.brightness)
        if CyncCapability.CCT_COLOR in caps and 1 <= (device.color_temp or 0) <= 100:
            state["color_temp"] = int(device.color_temp)
        elif CyncCapability.RGB_COLOR in caps and any(device.rgb or ()):
            state["rgb"] = tuple(int(v) for v in device.rgb)
        return state
    except (UnsupportedCapabilityError, AttributeError, TypeError, ValueError):
        return None


def _run(coro: Any) -> Any:
    """Run with a time limit, in a separate thread if this one runs a loop."""

    async def limited() -> Any:
        return await asyncio.wait_for(coro, TIMEOUT_SECONDS)

    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return _mapped(lambda: asyncio.run(limited()))
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        return _mapped(lambda: pool.submit(asyncio.run, limited()).result())


def _mapped(call: Any) -> Any:
    try:
        return call()
    except CyncError:
        raise
    except TwoFactorRequiredError:
        raise CyncCodeSent("Cync emailed you a code: enter it to finish") from None
    except AuthFailedError:
        raise CyncLoginError("Cync refused the login: log in again") from None
    except NoHubConnectedError:
        raise CyncError("no Cync device is on Wi-Fi to pass commands on") from None
    except UnsupportedCapabilityError:
        raise CyncUnsupported("this Cync device cannot do that") from None
    except TimeoutError:
        raise CyncError("Cync did not answer in time") from None
    except (PycyncError, aiohttp.ClientError, OSError) as error:
        raise CyncError(f"could not reach Cync: {type(error).__name__}") from None


async def _login(email: str, password: str, code: str | None) -> dict[str, Any]:
    async with aiohttp.ClientSession() as web:
        auth = Auth(web, username=email, password=password)
        return _tokens(await auth.login(code))


async def _devices(tokens: dict[str, Any]) -> tuple[list[CyncDeviceInfo], dict]:
    async with aiohttp.ClientSession() as web:
        auth = Auth(web, user=_user(tokens))
        api = Cync(auth)  # the REST part only: no command connection
        await api.refresh_home_info()
        found = [
            _info(d)
            for d in api.get_devices()
            if isinstance(d, CyncLight | CyncPlug) or is_thermostat(d)
        ]
        return found, _tokens(auth.user)


async def _group_list(tokens: dict[str, Any]) -> tuple[list[CyncGroupInfo], dict]:
    async with aiohttp.ClientSession() as web:
        auth = Auth(web, user=_user(tokens))
        api = Cync(auth)
        await api.refresh_home_info()
        return _groups(api), _tokens(auth.user)


async def _states(tokens: dict[str, Any]) -> dict[str, dict[str, Any]]:
    async with aiohttp.ClientSession() as web:
        auth = Auth(web, user=_user(tokens))
        api = await Cync.create(auth)
        # Only devices Cync actually reported on count: the others keep their
        # stored state. Status arrives in pages; wait a moment for the rest.
        reported: dict[str, Any] = {}
        first = asyncio.Event()

        def on_update(data: Any) -> None:
            if isinstance(data, dict):
                for key, device in data.items():
                    reported[str(getattr(device, "unique_id", key))] = device
            first.set()

        api.set_update_callback(on_update)
        try:
            await api._command_client.update_mesh_devices()
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(first.wait(), STATE_WAIT_SECONDS)
                await asyncio.sleep(STATE_SETTLE_SECONDS)
            by_id = {str(d.unique_id): d for d in api.get_devices()}
            found = {}
            for device_id in reported:
                device = by_id.get(device_id)
                state = _state(device) if device is not None else None
                if state is not None:
                    found[device_id] = state
            return found
        finally:
            with contextlib.suppress(Exception):
                await asyncio.wait_for(api.shut_down(), 5)


async def act(api: Any, device_id: str, action: str, value: Any) -> None:
    """Carry out one action over an open connection (see `send`)."""
    device = next((d for d in api.get_devices() if str(d.unique_id) == device_id), None)
    if device is None:
        raise CyncError("this device is no longer on the Cync account")
    if action == "power":
        await (device.turn_on() if value else device.turn_off())
    elif action == "brightness":
        await device.set_brightness(value)
    elif action == "color_temp":
        await device.set_color_temp(value)
    elif action == "rgb":
        await device.set_rgb(value)
    else:
        raise CyncUnsupported(f"unknown Cync action {action}")


def act_on_open(api: Any, loop: Any, device_id: str, action: str, value: Any) -> None:
    """Run `act` on a connection open in another thread's event loop (the
    live connection), waiting for it. Cync allows one connection per
    account: a second login drops the first."""

    async def limited() -> None:
        await asyncio.wait_for(act(api, device_id, action, value), TIMEOUT_SECONDS)

    _mapped(lambda: asyncio.run_coroutine_threadsafe(limited(), loop).result())


async def _send(
    tokens: dict[str, Any], device_id: str, action: str, value: Any
) -> dict[str, Any]:
    async with aiohttp.ClientSession() as web:
        auth = Auth(web, user=_user(tokens))
        api = await Cync.create(auth)
        try:
            await act(api, device_id, action, value)
        finally:
            with contextlib.suppress(Exception):
                await asyncio.wait_for(api.shut_down(), 5)
        return _tokens(auth.user)


def thermostat_write_on_open(
    api: Any, loop: Any, cloud_id: int, entries: list[tuple[int, int | str]]
) -> dict[int, Any]:
    """Write thermostat data points over the live connection; returns the
    thermostat's report afterwards (see cync_thermostat)."""
    link = getattr(api, "thermostat_link", None)
    if link is None:
        raise CyncError("the Cync connection is still starting; try again shortly")

    async def limited() -> dict[int, Any]:
        return await asyncio.wait_for(link.write(cloud_id, entries), TIMEOUT_SECONDS)

    return dict(
        _mapped(lambda: asyncio.run_coroutine_threadsafe(limited(), loop).result())
    )


def thermostat_settings_on_open(
    api: Any, loop: Any, cloud_id: int, names: list[str]
) -> dict[str, Any]:
    """Read thermostat settings (schedules) by name over the live connection."""
    link = getattr(api, "thermostat_link", None)
    if link is None:
        raise CyncError("the Cync connection is still starting; try again shortly")

    async def limited() -> dict[str, Any]:
        seconds = cync_thermostat.SETTING_SECONDS * len(names) + 10
        return dict(
            await asyncio.wait_for(link.read_settings(cloud_id, names), seconds)
        )

    return dict(
        _mapped(lambda: asyncio.run_coroutine_threadsafe(limited(), loop).result())
    )


# ------------------------------------------------------------ the interface


def login(email: str, password: str, code: str | None = None) -> dict[str, Any]:
    """Return tokens, or raise CyncCodeSent (a code was emailed) or
    CyncLoginError."""
    return dict(_run(_login(email, password, code)))


def list_devices(
    tokens: dict[str, Any],
) -> tuple[list[CyncDeviceInfo], dict[str, Any]]:
    """The account's lights and plugs, and the (possibly refreshed) tokens."""
    devices, fresh = _run(_devices(tokens))
    return list(devices), dict(fresh)


def list_groups(
    tokens: dict[str, Any],
) -> tuple[list[CyncGroupInfo], dict[str, Any]]:
    """The account's rooms and groups as the Cync app shows them."""
    groups, fresh = _run(_group_list(tokens))
    return list(groups), dict(fresh)


def read_states(tokens: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Current state of each device that reported, by device id:
    {"on", "brightness"?, "color_temp"? (1-100), "rgb"? ((r, g, b))}."""
    return dict(_run(_states(tokens)))


def send(
    tokens: dict[str, Any], device_id: str, action: str, value: Any
) -> dict[str, Any]:
    """action: power (bool), brightness (0-100), color_temp (1-100, 1 is the
    coolest), rgb ((r, g, b)). Returns the (possibly refreshed) tokens."""
    return dict(_run(_send(tokens, device_id, action, value)))


async def listen(
    tokens: dict[str, Any],
    on_states: Callable[[dict[str, dict[str, Any]]], Coroutine[Any, Any, None]],
    poll_seconds: float = 30,
    on_open: Callable[[Any], None] | None = None,
) -> None:
    """Stay connected and pass on state reports as they come (Cync pushes a
    report when a device changes, also from the Cync app or a wall switch).
    Asks for a full report every `poll_seconds`. Runs until cancelled."""
    async with aiohttp.ClientSession() as web:
        auth = Auth(web, user=_user(tokens))
        api = await asyncio.wait_for(Cync.create(auth), TIMEOUT_SECONDS)
        loop = asyncio.get_running_loop()
        by_cloud_id: dict[int, str] = {}

        def on_points(cloud_id: int, points: dict[int, Any]) -> None:
            device_id = by_cloud_id.get(cloud_id)
            if device_id is not None:
                state = cync_thermostat.thermostat_state(points)
                loop.create_task(on_states({device_id: {"thermostat": state}}))

        link = cync_thermostat.attach(api, on_points)
        if on_open is not None:
            on_open(api)  # so commands can share this connection

        def on_update(data: Any) -> None:
            states = {}
            if isinstance(data, dict):
                for key, device in data.items():
                    state = _state(device)
                    if state is not None:
                        states[str(getattr(device, "unique_id", key))] = state
            if states:
                loop.create_task(on_states(states))

        try:
            while True:
                # Another connection (a sync) may have taken the callback.
                api.set_update_callback(on_update)
                with contextlib.suppress(Exception):
                    await asyncio.wait_for(
                        api._command_client.update_mesh_devices(), TIMEOUT_SECONDS
                    )
                for device in api.get_devices():
                    if is_thermostat(device):
                        by_cloud_id[int(device.device_id)] = str(device.unique_id)
                link.ids = set(by_cloud_id)
                with contextlib.suppress(Exception):  # thermostats report on a probe
                    await asyncio.wait_for(link.probe_all(), TIMEOUT_SECONDS)
                await asyncio.sleep(poll_seconds)
        finally:
            cync_thermostat.detach(api)
            with contextlib.suppress(Exception):
                await asyncio.wait_for(api.shut_down(), 5)
