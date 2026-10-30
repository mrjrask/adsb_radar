"""Aircraft positions and geometry shared by polling and rendering."""

import math
from dataclasses import dataclass, replace

EARTH_RADIUS_NM = 3440.065


@dataclass(frozen=True)
class LiveAircraft:
    hex: str
    callsign: str | None
    aircraft_type: str | None
    latitude: float
    longitude: float
    altitude_ft: int | None
    track: float | None
    ground_speed_kt: float | None
    vertical_rate_fpm: int | None
    seen_at: float
    device: str
    distance: float | None = None
    bearing: float | None = None


def haversine_distance(lat1, lon1, lat2, lon2, *, unit="nm"):
    radius = {"nm": EARTH_RADIUS_NM, "mi": 3958.8, "km": 6371.0088}[unit]
    p1, p2 = math.radians(lat1), math.radians(lat2)
    a = math.sin((p2 - p1) / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(math.radians(lon2 - lon1) / 2) ** 2
    return 2 * radius * math.asin(min(1, math.sqrt(a)))


def initial_bearing(lat1, lon1, lat2, lon2):
    p1, p2, dl = math.radians(lat1), math.radians(lat2), math.radians(lon2 - lon1)
    return math.degrees(math.atan2(math.sin(dl) * math.cos(p2),
                                  math.cos(p1) * math.sin(p2) - math.sin(p1) * math.cos(p2) * math.cos(dl))) % 360


def advance(aircraft, now, limit=15, unit="nm"):
    age = min(max(now - aircraft.seen_at, 0), limit)
    if not age or aircraft.track is None or aircraft.ground_speed_kt is None or aircraft.bearing is None:
        return aircraft
    moved = aircraft.ground_speed_kt * {"nm": 1, "mi": 1.150779, "km": 1.852}[unit] * age / 3600
    b, t = math.radians(aircraft.bearing), math.radians(aircraft.track)
    x = aircraft.distance * math.sin(b) + moved * math.sin(t)
    y = aircraft.distance * math.cos(b) + moved * math.cos(t)
    return replace(aircraft, distance=math.hypot(x, y), bearing=math.degrees(math.atan2(x, y)) % 360, seen_at=now)
