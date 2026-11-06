"""Find TVs on the home network: try each address of a small private
network on the ports Samsung (8001), Roku (8060) and LG (3001, 3000) TVs
answer on, then ask the ones that answer what they are. A search, nothing
more: nothing is added or changed.
"""

import concurrent.futures
import ipaddress
import re
import socket
from typing import Any

import requests

from app.integrations import roku

PORTS = (8001, 8060, 3001, 3000)
CONNECT_SECONDS = 0.4
ASK_SECONDS = 2
WORKERS = 128
SMALLEST_PREFIX = 22  # at most 1,024 addresses


class ScanError(Exception):
    """The network given cannot be searched."""


def network_for(text: str | None, client: str | None) -> ipaddress.IPv4Network:
    """The network to search: the one given, else the /24 of the browser's
    address when it is on the home network."""
    try:
        if text:
            net = ipaddress.ip_network(text.strip(), strict=False)
        elif client:
            net = ipaddress.ip_network(f"{client}/24", strict=False)
        else:
            raise ScanError("give the network to search, for example 192.168.1.0/24")
    except ValueError:
        raise ScanError("not a network: use the form 192.168.1.0/24") from None
    if (
        not isinstance(net, ipaddress.IPv4Network)
        or not net.is_private
        or net.is_loopback
    ):
        raise ScanError(
            "only your home network can be searched (for example 192.168.1.0/24)"
        )
    if net.prefixlen < SMALLEST_PREFIX:
        raise ScanError(
            f"that network is too large: search a /{SMALLEST_PREFIX} or smaller"
        )
    return net


def _open_ports(host: str) -> list[int]:
    found = []
    for port in PORTS:
        try:
            with socket.create_connection((host, port), timeout=CONNECT_SECONDS):
                found.append(port)
        except OSError:
            continue
    return found


def _samsung(host: str) -> dict[str, Any] | None:
    try:
        info = requests.get(f"http://{host}:8001/api/v2/", timeout=ASK_SECONDS).json()
    except (requests.RequestException, ValueError):
        return None
    device = info.get("device") if isinstance(info, dict) else None
    if not isinstance(device, dict):
        return None
    name = str(info.get("name") or device.get("name") or "Samsung TV")
    mac = str(device.get("wifiMac") or "") or None
    if mac and not re.fullmatch(r"([0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}", mac):
        mac = None
    return {
        "brand": "samsung",
        "name": name,
        "model": device.get("modelName"),
        "mac": mac,
    }


def _roku(host: str) -> dict[str, Any] | None:
    try:
        info = roku.info(host)
    except roku.RokuError:
        return None
    return {
        "brand": "roku",
        "name": info["name"] or "Roku",
        "model": info["model"],
        "mac": None,
    }


def _identify(host: str) -> dict[str, Any] | None:
    ports = _open_ports(host)
    found = None
    if 8001 in ports:
        found = _samsung(host)
    if found is None and 8060 in ports:
        found = _roku(host)
    if found is None and 3001 in ports:
        found = {"brand": "lg", "name": "LG TV", "model": None, "mac": None}
    if found is None and 3000 in ports and 8001 not in ports:
        found = {"brand": "lg", "name": "LG TV (probably)", "model": None, "mac": None}
    return {"host": host, **found} if found else None


def scan(net: ipaddress.IPv4Network) -> list[dict[str, Any]]:
    hosts = [str(h) for h in net.hosts()]
    with concurrent.futures.ThreadPoolExecutor(max_workers=WORKERS) as pool:
        results = list(pool.map(_identify, hosts))
    return [r for r in results if r]
