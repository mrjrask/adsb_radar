#!/usr/bin/env python3
"""Render synthetic flight and radar previews at all three native resolutions."""

import argparse
import sys
import time
from dataclasses import replace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from adsb_radar.config import DEFAULTS  # noqa: E402
from adsb_radar.flight_routes import Airport, FlightRoute  # noqa: E402
from adsb_radar.models import LiveAircraft  # noqa: E402
from adsb_radar.scene import Scene  # noqa: E402
from adsb_radar.video import PROFILES  # noqa: E402


class DemoRoutes:
    def route(self, _plane):
        return FlightRoute("DAL123", "Delta Air Lines", "DAL", "DL",
                           Airport("SEA", "KSEA", "Seattle International Airport", "Seattle", 47.45, -122.31),
                           Airport("ORD", "KORD", "Chicago O'Hare International Airport", "Chicago", 41.97, -87.90))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    now = time.time()
    config = {**DEFAULTS, "LATITUDE": 41.88, "LONGITUDE": -87.63}
    focus = LiveAircraft("a12345", "DAL123", "B738", 41.89, -87.61, 6500, 65, 230, -500,
                         now, "demo", 1.5, 45)
    traffic = tuple(replace(focus, hex=f"a{index:05x}", callsign=f"{code}{123 + index}",
                            altitude_ft=3000 + index * 3500, distance=4 + index * 0.7,
                            bearing=(index * 43) % 360, track=(index * 55) % 360)
                    for index, code in enumerate(("UAL", "SWA", "AAL", "JBU", "ASA", "FDX", "BAW", "KAL", "ACA", "NKS")))
    for profile, size in PROFILES.items():
        scene = Scene(size)
        for mode, planes in (("flight", (focus, *traffic)), ("radar", traffic)):
            image = scene.render(planes, config, DemoRoutes(), now=now, health="2/2 receivers online")
            image.save(args.output / f"{profile}-{mode}.png")
            print(f"{profile}-{mode}: {image.width}×{image.height}")


if __name__ == "__main__":
    main()
