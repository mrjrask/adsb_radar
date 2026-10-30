import time
from dataclasses import replace

import pytest
from PIL import Image

from adsb_radar import aircraft_art, flight_layout, flight_routes
from adsb_radar.display import viewport
from adsb_radar.forms import RADAR_COLOR_DEFAULTS, RADAR_COLOR_NIGHT
from adsb_radar.metadata import Metadata
from adsb_radar.models import advance
from adsb_radar.scene import Scene, select_flight
from adsb_radar.sky_cone import Cone


@pytest.mark.parametrize("size", [(3840, 2160), (1920, 1080), (848, 480)])
def test_high_resolution_flight_and_radar_without_uploaded_assets(config, plane, distant, size):
    scene = Scene(size)
    image = scene.render((plane, distant), config)
    assert image.size == size and image.mode == "RGB"
    assert image.getbbox() is not None
    first = scene.render((distant,), config, now=time.time())
    second = scene.render((distant,), config, now=time.time() + 0.5)
    assert first.size == size and first.tobytes() != second.tobytes()


def test_idle_modes_and_offline_stale_positions(config, plane):
    scene = Scene((800, 480))
    for mode in ("clock", "radar", "message", "blank", "clock,radar"):
        image = scene.render((), {**config, "IDLE": mode}, now=1000)
        assert image.size == (800, 480)
        if mode == "blank":
            assert image.getbbox() is None
    # Receiver data must expire even if polling gets stuck.
    image = scene.render((replace(plane, seen_at=1),), config, now=1000)
    assert scene.keep is None
    assert image.getbbox() is not None
    assert scene.render((plane,), config, online=False).getbbox() is not None
    assert scene.keep is None


def test_cone_selects_highest_visible_with_hysteresis(config, plane):
    high = replace(plane, hex="b12345", altitude_ft=18000, distance=3)
    settings = {**config, "RADIUS": 5, "MIN_ELEVATION": 30}
    flight = select_flight((plane, high), settings, None)
    assert flight.aircraft.hex == high.hex
    cone = Cone(min_elevation=60, keep=high.hex)
    assert cone.sees(high, radius=5, unit="nm") == (cone.elevation(high, "nm") >= 57)


def test_theme_and_controls_change_radar(config, distant):
    scene = Scene((800, 480))
    stamp = time.time()
    normal = scene.render((distant,), {**config, **RADAR_COLOR_DEFAULTS}, now=stamp)
    night = scene.render((distant,), {**config, **RADAR_COLOR_NIGHT}, now=stamp)
    assert normal.tobytes() != night.tobytes()
    no_beam = scene.render((distant,), {**config, "RADAR_SWEEP": False, "RADAR_LIGHTS": False,
                                           "RADAR_MOTION": False}, now=stamp)
    assert no_beam.tobytes() != normal.tobytes()


def test_uploaded_asset_lookup_and_generic_fallback(tmp_path, monkeypatch):
    (tmp_path / "DAL").mkdir()
    (tmp_path / "_generic").mkdir()
    asset = tmp_path / "DAL/B738.png"
    # Synthetic test artwork only, never copied from desk_display.
    Image.new("RGBA", (200, 50), "red").save(asset)
    monkeypatch.setattr(aircraft_art, "ASSET_DIR", str(tmp_path))
    art = aircraft_art.aircraft_image(400, designator="B738", airline_icao="DAL", brand=None)
    assert art.size == (400, 100) and art.getpixel((100, 50)) == (255, 0, 0, 255)
    asset.rename(tmp_path / "_generic/B738.png")
    assert aircraft_art.asset_path("B738", "UAL", str(tmp_path)).endswith("_generic/B738.png")
    assert aircraft_art.aircraft_image(400, designator="B738", airline_icao="UAL", brand=None) is not None


def test_cache_types_routes_and_flight_layout(config, plane, tmp_path):
    metadata = Metadata(tmp_path)
    origin = flight_routes.Airport("SEA", "KSEA", "Seattle International Airport", "Seattle", 47.45, -122.31)
    destination = flight_routes.Airport("ORD", "KORD", "Chicago O'Hare International Airport", "Chicago", 41.97, -87.90)
    route = flight_routes.FlightRoute("DAL123", "Delta Air Lines", "DAL", "DL", origin, destination)
    with metadata.connect() as connection:
        connection.execute("INSERT INTO types VALUES (?,?)", (plane.hex, "B738"))
        connection.execute("INSERT INTO routes VALUES (?,?,?)", (plane.callsign, route.to_json(), time.time()))
        connection.commit()
    assert metadata.enrich((replace(plane, aircraft_type=None),))[0].aircraft_type == "B738"
    assert metadata.route(plane).destination.code == "ORD"
    flight = select_flight((plane,), config, metadata)
    assert flight.route is not None
    image = flight_layout.compose_overhead_image(flight, width=1920, height=1080,
                                                  home=(config["LATITUDE"], config["LONGITUDE"]))
    assert image.size == (1920, 1080)
    assert flight_routes.flight_phase(route, (41.88, -87.63))[0] == "Arriving from"


def test_motion_and_aspect_preserving_scaling(plane):
    moved = advance(plane, plane.seen_at + 5)
    assert moved.distance != plane.distance
    assert advance(plane, plane.seen_at + 100).distance == advance(plane, plane.seen_at + 15).distance
    assert viewport((1920, 1080), (1920, 1200)) == (0, 60, 1920, 1080)
    assert viewport((1080, 1920), (1920, 1080)) == (656, 0, 608, 1080)
