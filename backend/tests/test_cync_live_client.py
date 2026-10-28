"""Light and plug commands go through the live connection's own command
client, even after a device-list read replaced the shared device objects
with ones tied to a client that never connects."""

import asyncio
import concurrent.futures
from types import SimpleNamespace

import pytest
from pycync.devices.capabilities import CyncCapability

from app.integrations import cync


def run(coro):
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(asyncio.run, coro).result()


class Client:
    def __init__(self):
        self.sent = []
        self._device_statuses_updated = True

    async def set_power_state(self, device, on):
        self.sent.append(("power", device.unique_id, on))

    async def set_brightness(self, device, value):
        self.sent.append(("brightness", device.unique_id, value))

    async def set_color_temp(self, device, value):
        self.sent.append(("color_temp", device.unique_id, value))

    async def set_rgb(self, device, value):
        self.sent.append(("rgb", device.unique_id, value))


class StaleClient:
    """What a REST-only read leaves on the devices: never connected."""

    async def set_power_state(self, *args):
        await asyncio.sleep(3600)


def fake(capabilities):
    stale = StaleClient()
    device = SimpleNamespace(
        unique_id="77-1",
        wifi_connected=True,
        capabilities={CyncCapability.CAN_ACT_AS_WIFI_PROXY, *capabilities},
        _command_client=stale,
        turn_on=lambda: stale.set_power_state(),
        supports_capability=lambda c: c in capabilities,
    )
    live = Client()
    api = SimpleNamespace(_command_client=live, get_devices=lambda: [device])
    return api, live


def test_commands_use_the_live_client():
    caps = {
        CyncCapability.ON_OFF,
        CyncCapability.DIMMING,
        CyncCapability.CCT_COLOR,
        CyncCapability.RGB_COLOR,
    }
    api, live = fake(caps)
    run(asyncio.wait_for(cync.act(api, "77-1", "power", True), 2))
    run(asyncio.wait_for(cync.act(api, "77-1", "brightness", 40), 2))
    run(asyncio.wait_for(cync.act(api, "77-1", "color_temp", 50), 2))
    run(asyncio.wait_for(cync.act(api, "77-1", "rgb", (1, 2, 3)), 2))
    assert live.sent == [
        ("power", "77-1", True),
        ("brightness", "77-1", 40),
        ("color_temp", "77-1", 50),
        ("rgb", "77-1", (1, 2, 3)),
    ]


def test_unsupported_action_is_refused():
    api, live = fake({CyncCapability.ON_OFF})  # a plug
    with pytest.raises(cync.CyncUnsupported):
        run(cync.act(api, "77-1", "brightness", 40))
    with pytest.raises(cync.CyncUnsupported):
        run(cync.act(api, "77-1", "dance", 1))
    assert live.sent == []
