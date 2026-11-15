"""A home's address as latitude and longitude, for sunrise and sunset
schedules. The address is sent to the US Census Bureau's geocoder (US
addresses) and, if it finds nothing, to OpenStreetMap's Nominatim; nothing
else about the home goes with it. Tests replace `get`.
"""

from typing import Any

import requests

TIMEOUT_SECONDS = 5  # each service; saving the address waits for it
CENSUS = "https://geocoding.geo.census.gov/geocoder/locations/onelineaddress"
NOMINATIM = "https://nominatim.openstreetmap.org/search"
AGENT = "SmartHomeUnifiedControl/1.0 (home schedules; sunrise and sunset)"


def get(url: str, params: dict[str, str]) -> Any:
    response = requests.get(
        url, params=params, headers={"User-Agent": AGENT}, timeout=TIMEOUT_SECONDS
    )
    response.raise_for_status()
    return response.json()


def _census(address: str) -> tuple[float, float] | None:
    data = get(
        CENSUS, {"address": address, "benchmark": "Public_AR_Current", "format": "json"}
    )
    matches = ((data or {}).get("result") or {}).get("addressMatches") or []
    if not matches:
        return None
    point = matches[0].get("coordinates") or {}
    return float(point["y"]), float(point["x"])


def _nominatim(address: str) -> tuple[float, float] | None:
    found = get(NOMINATIM, {"q": address, "format": "jsonv2", "limit": "1"})
    if not found:
        return None
    return float(found[0]["lat"]), float(found[0]["lon"])


def locate(address: str) -> tuple[float, float] | None:
    """(latitude, longitude), rounded to about 100 m, or None if neither
    service finds the address or can be reached."""
    for look_up in (_census, _nominatim):
        try:
            found = look_up(address)
        except (requests.RequestException, ValueError, KeyError, TypeError, IndexError):
            continue
        if found is not None:
            lat, lon = found
            if -90 <= lat <= 90 and -180 <= lon <= 180:
                return round(lat, 3), round(lon, 3)
    return None
