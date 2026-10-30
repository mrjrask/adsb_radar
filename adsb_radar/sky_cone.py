"""Which aircraft you could actually see from the ground: the visibility cone.

A flat flight radius treats the sky as a cylinder: a plane
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
from dataclasses import dataclass
from typing import Any, Optional

SECTORS = ("N", "NE", "E", "SE", "S", "SW", "W", "NW")
FEET_PER_UNIT = {"nm": 1852 / 0.3048, "mi": 5280.0, "km": 1000 / 0.3048}
# Eyesight limit when no maximum range is set, in nautical miles.
DEFAULT_MAX_RANGE_NM = 10.0
# A plane already showing stays until it sinks this far below its cutoff, so
# one sitting right at the tree line does not flicker between polls.
HYSTERESIS_DEGREES = 3.0


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


__all__ = [
    "DEFAULT_MAX_RANGE_NM",
    "FEET_PER_UNIT",
    "HYSTERESIS_DEGREES",
    "SECTORS",
    "Cone",
    "default_max_range",
    "sector",
]
