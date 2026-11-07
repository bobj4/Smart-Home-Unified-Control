"""Turning a Samsung TV on and off without toggling it the wrong way.

The TV has one power key: KEY_POWER turns it off when it is on, and a 2018+
TV in network standby (its screen off, still answering on :8001) turns on
with the same key. So the power key is only sent when the TV's answer says
it will do the right thing:

- on: "on" (or a TV that does not say) gets the key; standby needs nothing.
- off: a TV in standby gets the key (it wakes at once); one that does not
  answer at all gets the Wake-on-LAN packet when its MAC address is known.

The Wake-on-LAN packet goes to the whole network (255.255.255.255), to the
TV's own subnet (a.b.c.255) and to the TV itself: from inside Docker the
first one stays inside the container's network, the other two reach the TV.
"""

import ipaddress
import socket

import requests

from app.integrations import samsung

STATE_SECONDS = 1.5


def power_state(host: str, protocol: str) -> str | None:
    """'on', 'standby', or None when the TV does not answer (it is off, or
    is a 2014-2017 TV, which only answers while on)."""
    if protocol != "tizen":
        return None
    try:
        info = requests.get(f"http://{host}:8001/api/v2/", timeout=STATE_SECONDS).json()
    except (requests.RequestException, ValueError):
        return None
    device = info.get("device") if isinstance(info, dict) else None
    power = device.get("PowerState") if isinstance(device, dict) else None
    return "standby" if power not in (None, "on") else "on"


def _targets(host: str) -> list[str]:
    try:
        address = ipaddress.IPv4Address(host)
    except ValueError:
        return []
    subnet = ipaddress.IPv4Network(f"{address}/24", strict=False)
    return [str(subnet.broadcast_address), str(address)]


def wake(mac: str, host: str) -> None:
    """The Wake-on-LAN packet to everywhere the TV may hear it."""
    samsung.wake(mac)  # checks the MAC address; the network-wide broadcast
    packet = b"\xff" * 6 + bytes.fromhex(mac.replace(":", "").replace("-", "")) * 16
    for target in _targets(host):
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
                sock.sendto(packet, (target, 9))
        except OSError:
            continue  # the broadcast above was sent; this is extra


def plan(command: str, state: str | None, mac: str | None) -> str:
    """What turning the TV on or off needs: 'key', 'wake' or 'nothing'."""
    if command == "turn_off":
        return "nothing" if state == "standby" else "key"
    if state == "on":
        return "nothing"
    if state == "standby" or not mac:
        return "key"
    return "wake"
