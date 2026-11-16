"""Sunrise and sunset for a place and a day (the sunrise equation NOAA and
most almanacs use: accurate to a minute or two, ample for schedules).
Returned in UTC; None when the sun does not rise or set that day (far
north or south)."""

import math
from datetime import UTC, date, datetime, timedelta

J2000 = 2451545.0
EPOCH = datetime(2000, 1, 1, 12, tzinfo=UTC)  # Julian day J2000


def _datetime(julian: float) -> datetime:
    return EPOCH + timedelta(days=julian - J2000)


def times(
    day: date, latitude: float, longitude: float
) -> tuple[datetime | None, datetime | None]:
    """(sunrise, sunset) in UTC for the local `day` at the place
    (longitude east positive)."""
    n = day.toordinal() + 1721425.0 - J2000  # days from J2000 to the day's noon
    mean_noon = n - longitude / 360
    anomaly = (357.5291 + 0.98560028 * mean_noon) % 360
    m = math.radians(anomaly)
    center = 1.9148 * math.sin(m) + 0.02 * math.sin(2 * m) + 0.0003 * math.sin(3 * m)
    ecliptic = math.radians((anomaly + center + 180 + 102.9372) % 360)
    transit = J2000 + mean_noon + 0.0053 * math.sin(m) - 0.0069 * math.sin(2 * ecliptic)
    sin_decl = math.sin(ecliptic) * math.sin(math.radians(23.4397))
    cos_decl = math.cos(math.asin(sin_decl))
    phi = math.radians(latitude)
    cos_hour = (math.sin(math.radians(-0.833)) - math.sin(phi) * sin_decl) / (
        math.cos(phi) * cos_decl
    )
    if not -1 <= cos_hour <= 1:
        return None, None  # polar night or midnight sun
    hour = math.degrees(math.acos(cos_hour)) / 360
    return _datetime(transit - hour), _datetime(transit + hour)
