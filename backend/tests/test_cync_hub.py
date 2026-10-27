"""Light and plug commands probe for a Wi-Fi device ("hub") first when the
connection has none, instead of waiting until they time out."""

import asyncio
import concurrent.futures
from types import SimpleNamespace

import pytest
from pycync.devices.capabilities import CyncCapability

from app.integrations import cync

PROXY = {CyncCapability.CAN_ACT_AS_WIFI_PROXY}


class FakeClient:
    def __init__(self, devices, answers):
        self.devices, self.answers = devices, answers
        self.probes = 0
        self._device_statuses_updated = False

    async def probe_devices(self):
        self.probes += 1
        if self.answers:
            asyncio.get_running_loop().call_later(
                0.3, lambda: setattr(self.devices[0], "wifi_connected", True)
            )


def run(coro):
    """In its own thread: the browser tests keep an event loop running in
    this one."""
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(asyncio.run, coro).result()


def fake_api(wifi, answers=True):
    devices = [SimpleNamespace(wifi_connected=wifi, capabilities=PROXY)]
    client = FakeClient(devices, answers)
    return SimpleNamespace(_command_client=client, get_devices=lambda: devices)


def test_known_hub_needs_no_probe():
    api = fake_api(wifi=True)
    run(cync.ensure_hub(api))
    assert api._command_client.probes == 0
    assert api._command_client._device_statuses_updated is True


def test_lost_hub_is_probed_again():
    api = fake_api(wifi=False)
    run(cync.ensure_hub(api, wait=3))
    assert api._command_client.probes == 1
    assert api._command_client._device_statuses_updated is True


def test_no_hub_says_so_quickly():
    api = fake_api(wifi=False, answers=False)
    with pytest.raises(cync.CyncError, match="answered over Wi-Fi"):
        run(cync.ensure_hub(api, wait=0.5))
    assert api._command_client._device_statuses_updated is False


def test_a_device_without_wifi_proxy_is_not_a_hub():
    devices = [SimpleNamespace(wifi_connected=True, capabilities=set())]
    assert cync.has_hub(SimpleNamespace(get_devices=lambda: devices)) is False
