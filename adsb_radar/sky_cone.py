"""Which aircraft you could actually see from the ground: the visibility cone.

The LED flight board's flat radius treats the sky as a cylinder: a plane
skimming the treetops 2.5 nm away counts as overhead, and a jet at 35,000 ft
5 nm away (about 49 degrees up) does not. The cone counts a plane as visible
when it is at least a cutoff angle above the horizon (the tree line, which can
differ by compass direction) and within eyesight (straight-line distance).
Earth curvature is ignored; it is negligible at these distances.

Pure Python with no imports from the rest of the project, so the settings
catalog can validate a horizon without loading the renderer.
"""

from __future__ import annotations

import math
import threading
from dataclasses import dataclass
from typing import Any, Mapping, Optional

SECTORS = ("N", "NE", "E", "SE", "S", "SW", "W", "NW")
FEET_PER_UNIT = {"nm": 1852 / 0.3048, "mi": 5280.0, "km": 1000 / 0.3048}
# Eyesight limit when no maximum range is set, in nautical miles.
DEFAULT_MAX_RANGE_NM = 10.0
# A plane already showing stays until it sinks this far below its cutoff, so
# one sitting right at the tree line does not flicker between polls.
HYSTERESIS_DEGREES = 3.0
MAX_ELEVATION = 89.0


def parse_horizon(text: Optional[str]) -> tuple[tuple[str, float], ...]:
    """``"N45,NE40,W50"`` as ``(("N", 45.0), ("NE", 40.0), ("W", 50.0))``.

    Empty means no per-direction cutoffs. Raises :class:`ValueError` naming
    the bad entry.
    """

    cutoffs: dict[str, float] = {}
    for entry in (text or "").split(","):
        entry = entry.strip().upper()
        if not entry:
            continue
        split = len(entry) - len(entry.lstrip("NESW"))
        name, number = entry[:split], entry[split:].strip()
        if name not in SECTORS:
            raise ValueError(f"{entry!r}: start each entry with a compass point ({', '.join(SECTORS)})")
        if name in cutoffs:
            raise ValueError(f"{name} is listed twice")
        try:
            degrees = float(number)
        except ValueError:
            raise ValueError(f"{entry!r}: expected degrees after {name}, like {name}40") from None
        if not 0 <= degrees <= MAX_ELEVATION:
            raise ValueError(f"{entry!r}: degrees must be from 0 to {MAX_ELEVATION:g}")
        cutoffs[name] = degrees
    return tuple((name, cutoffs[name]) for name in SECTORS if name in cutoffs)


def format_horizon(horizon: Mapping[str, float] | tuple[tuple[str, float], ...]) -> str:
    """The compact form parse_horizon() reads."""

    pairs = horizon.items() if isinstance(horizon, Mapping) else horizon
    return ",".join(f"{name}{degrees:g}" for name, degrees in pairs)


def sector(bearing: float) -> str:
    """The compass sector (45 degrees wide, centred on the point) *bearing* falls in."""

    return SECTORS[int(((bearing % 360) + 22.5) // 45) % 8]


def default_max_range(unit: str) -> float:
    return DEFAULT_MAX_RANGE_NM * FEET_PER_UNIT["nm"] / FEET_PER_UNIT.get(unit, FEET_PER_UNIT["nm"])


@dataclass(frozen=True)
class Cone:
    """Where in the sky a plane can be seen from one spot.

    Distances (``max_range`` and the aircraft's own) are in the unit the
    caller passes; ``None`` max_range is DEFAULT_MAX_RANGE_NM in that unit.
    """

    min_elevation: float = 0.0
    horizon: tuple[tuple[str, float], ...] = ()
    home_elevation_ft: float = 0.0
    max_range: Optional[float] = None
    # The hex of the plane showing now; it keeps showing down to
    # HYSTERESIS_DEGREES below its cutoff.
    keep: Optional[str] = None

    def reach(self, unit: str) -> float:
        return default_max_range(unit) if self.max_range is None else self.max_range

    def cutoff(self, bearing: Optional[float]) -> float:
        if bearing is not None:
            for name, degrees in self.horizon:
                if name == sector(bearing):
                    return degrees
        return self.min_elevation

    def _legs(self, aircraft: Any, unit: str) -> Optional[tuple[float, float]]:
        """(height above the ground, ground distance), both in feet; None without an altitude."""

        if aircraft.altitude_ft is None or aircraft.distance is None:
            return None
        ground = aircraft.distance * FEET_PER_UNIT.get(unit, FEET_PER_UNIT["nm"])
        return aircraft.altitude_ft - self.home_elevation_ft, ground

    def elevation(self, aircraft: Any, unit: str) -> Optional[float]:
        """Degrees above the horizon, or None when the altitude is unknown."""

        legs = self._legs(aircraft, unit)
        return None if legs is None else math.degrees(math.atan2(*legs))

    def slant(self, aircraft: Any, unit: str) -> Optional[float]:
        """Straight-line distance in *unit*, or None when the altitude is unknown."""

        legs = self._legs(aircraft, unit)
        return None if legs is None else math.hypot(*legs) / FEET_PER_UNIT.get(unit, FEET_PER_UNIT["nm"])

    def sees(self, aircraft: Any, *, radius: float, unit: str) -> bool:
        """Whether *aircraft* is in view; one with no altitude gets the old radius test."""

        elevation = self.elevation(aircraft, unit)
        if elevation is None:
            return aircraft.distance is not None and aircraft.distance <= radius
        if self.slant(aircraft, unit) > self.reach(unit):
            return False
        slack = HYSTERESIS_DEGREES if self.keep is not None and aircraft.hex == self.keep else 0.0
        return elevation >= self.cutoff(aircraft.bearing) - slack

    def rank(self, aircraft: Any, unit: str) -> tuple:
        """Sort key: highest in the sky first; planes with no altitude last, nearest first."""

        elevation = self.elevation(aircraft, unit)
        return (elevation is None, -(elevation or 0.0), aircraft.distance or 0.0)


class ShownPlanes:
    """The plane each spot's board shows, for the cone's hysteresis.

    Keyed by location; an entry expires after *ttl* seconds without a frame,
    and only the *limit* most recent spots are kept.
    """

    def __init__(self, ttl: float = 60.0, limit: int = 64) -> None:
        self._ttl, self._limit = ttl, limit
        self._shown: dict[Any, tuple[str, float]] = {}
        self._lock = threading.Lock()

    def get(self, key: Any, now: float) -> Optional[str]:
        with self._lock:
            entry = self._shown.get(key)
            if entry is None or now - entry[1] > self._ttl:
                self._shown.pop(key, None)
                return None
            return entry[0]

    def put(self, key: Any, hex_id: Optional[str], now: float) -> None:
        with self._lock:
            self._shown.pop(key, None)
            if hex_id is None:
                return
            self._shown[key] = (hex_id, now)
            for stale in [k for k, (_h, seen) in self._shown.items() if now - seen > self._ttl]:
                del self._shown[stale]
            while len(self._shown) > self._limit:
                del self._shown[next(iter(self._shown))]

    def clear(self) -> None:
        with self._lock:
            self._shown.clear()


__all__ = [
    "DEFAULT_MAX_RANGE_NM",
    "FEET_PER_UNIT",
    "HYSTERESIS_DEGREES",
    "SECTORS",
    "Cone",
    "ShownPlanes",
    "default_max_range",
    "format_horizon",
    "parse_horizon",
    "sector",
]
