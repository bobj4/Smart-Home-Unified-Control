"""Cync wall switches and dimmers: pycync gives them no class of their own;
a dimmer shows as a light with brightness, an on/off switch like a plug."""

from types import SimpleNamespace

from pycync.devices.capabilities import CyncCapability
from pycync.devices.device_types import DeviceType

from app.integrations import cync


def device(kind, caps, name="Hall switch"):
    return SimpleNamespace(
        unique_id="1-2",
        name=name,
        is_online=True,
        mac="AABBCCDDEEFF",
        device_type=kind,
        capabilities=set(caps),
        device_id=7,
    )


def test_dimmer_switch_is_a_dimmable_light():
    info = cync._info(
        device(DeviceType.SWITCH, {CyncCapability.ON_OFF, CyncCapability.DIMMING})
    )
    assert info.kind == "light" and info.dimming is True
    assert info.white is False and info.color is False


def test_on_off_switch_is_like_a_plug():
    info = cync._info(device(DeviceType.SWITCH, {CyncCapability.ON_OFF}))
    assert info.kind == "plug" and info.dimming is False


def test_switches_are_listed(monkeypatch):
    switch = device(DeviceType.SWITCH, {CyncCapability.ON_OFF})
    remote = device(DeviceType.WIRE_FREE_REMOTE, set(), name="Remote")
    assert cync.is_switch(switch) and not cync.is_switch(remote)
    # A switch's state is unknown until it reports; nothing breaks meanwhile.
    assert cync._state(switch) is None
