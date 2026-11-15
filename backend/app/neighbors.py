"""A device's IP address from its MAC address, for brands whose cloud gives
only the MAC (Cync). Read from this server's neighbour (ARP) table, which
holds the home network's devices only when the server is on that network
(installed directly, or Docker with network_mode: host); inside Docker's
own network it finds nothing and the address shows as not reported.

Devices only appear in the table after the server has exchanged packets
with them, so a miss starts (at most every SWEEP_SECONDS, and only once
the server has started its background work: `enable`; never in tests) a sweep: one empty UDP
packet to each address of the server's /24, which makes the operating
system look each one up. Nothing is read from the devices.
"""

import ipaddress
import socket
import sys
import threading
import time
from pathlib import Path

ARP = Path("/proc/net/arp")  # Linux; elsewhere the table is empty
CACHE_SECONDS = 60
SWEEP_SECONDS = 600
SWEEP_PORT = 9  # discard
_lock = threading.Lock()
_cache: dict[str, str] = {}
_read_at = -CACHE_SECONDS * 2.0
_swept_at = -SWEEP_SECONDS * 2.0
_enabled = False


def enable() -> None:
    """Allow sweeps (main.py, with the background work). Not under pytest,
    whose app also starts its background work: tests send nothing."""
    global _enabled
    _enabled = "pytest" not in sys.modules


def normalize(mac: str) -> str:
    return mac.strip().upper().replace("-", ":")


def read_table(text: str) -> dict[str, str]:
    """MAC -> IP from /proc/net/arp's text (complete entries only)."""
    found = {}
    for line in text.splitlines()[1:]:
        parts = line.split()
        if len(parts) < 4 or parts[2] == "0x0" or parts[3] == "00:00:00:00:00:00":
            continue
        found[normalize(parts[3])] = parts[0]
    return found


def _table(now: float) -> dict[str, str]:
    global _cache, _read_at
    if now - _read_at >= CACHE_SECONDS:
        try:
            _cache = read_table(ARP.read_text())
        except OSError:
            _cache = {}
        _read_at = now
    return _cache


def own_network() -> ipaddress.IPv4Network | None:
    """The /24 of the address this server uses to reach the network (no
    packet is sent to find it)."""
    probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        probe.connect(("192.0.2.1", 9))  # documentation address; just routes
        here = ipaddress.ip_address(probe.getsockname()[0])
    except OSError:
        return None
    finally:
        probe.close()
    if not here.is_private or here.is_loopback:
        return None
    return ipaddress.ip_network(f"{here}/24", strict=False)  # type: ignore[return-value]


def sweep(network: ipaddress.IPv4Network) -> None:
    sender = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        for host in network.hosts():
            try:
                sender.sendto(b"", (str(host), SWEEP_PORT))
            except OSError:
                continue
    finally:
        sender.close()


def _sweep_soon(now: float) -> None:
    global _swept_at
    if not _enabled or now - _swept_at < SWEEP_SECONDS:
        return
    _swept_at = now
    network = own_network()
    if network is None:
        return

    def run() -> None:
        sweep(network)
        time.sleep(3)  # the lookups' answers
        with _lock:
            global _read_at
            _read_at = -CACHE_SECONDS * 2.0  # read the table afresh

    threading.Thread(target=run, name="arp-sweep", daemon=True).start()


def ip_for(mac: str | None) -> str | None:
    if not mac:
        return None
    now = time.monotonic()
    with _lock:
        found = _table(now).get(normalize(mac))
        if found is None and ARP.exists():
            _sweep_soon(now)
    return found
