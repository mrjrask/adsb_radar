from dataclasses import replace

import pytest

from adsb_radar import flight_routes
from adsb_radar.metadata import Metadata
from adsb_radar.scene import select_flight

ORD = flight_routes.Airport("ORD", "KORD", "Chicago O'Hare International Airport", "Chicago", 41.98, -87.90)
LNK = flight_routes.Airport("LNK", "KLNK", "Lincoln Airport", "Lincoln", 40.85, -96.76)
IAH = flight_routes.Airport("IAH", "KIAH", "George Bush Intercontinental", "Houston", 29.98, -95.34)
EWR = flight_routes.Airport("EWR", "KEWR", "Newark Liberty International Airport", "Newark", 40.69, -74.17)


def _route(callsign, origin, destination, name="United Airlines", iata="UA"):
    return flight_routes.FlightRoute(callsign, name, callsign[:3], iata, origin, destination)


def test_regional_flights_do_not_guess_marketing_numbers(plane, tmp_path, monkeypatch):
    from adsb_radar import metadata as module

    asked = []
    monkeypatch.setattr(module, "fetch_routeset", lambda *a, **k: (True, {"SKW5432": None}))
    monkeypatch.setattr(module, "fetch_route", lambda c, **k: asked.append(c) or (True, None))
    cache = Metadata(tmp_path)
    cache.update_route(replace(plane, callsign="SKW5432"))
    assert asked == ["SKW5432"]
    assert cache.route(replace(plane, callsign="SKW5432")) is None


def _skywest_flight(config, plane, tmp_path, monkeypatch):
    skywest = replace(plane, callsign="SKW5432", aircraft_type="CRJ9")
    metadata = Metadata(tmp_path)
    route = replace(_route("SKW5432", LNK, ORD, "", ""), airline_icao="SKW", codeshares=("DAL5432",))
    monkeypatch.setattr(metadata, "route", lambda aircraft: route)
    return skywest, metadata


@pytest.mark.parametrize("size", [(3840, 2160), (1920, 1080), (848, 480), (1080, 1080)])
def test_codeshare_header_is_pixel_identical_to_the_board(config, plane, size):
    from adsb_radar import airline_directory, flight_layout

    flight = flight_layout.OverheadFlight(replace(plane, callsign="SKW5432"), None,
                                          airline_directory.airline_for("SKW"), 1, (plane,),
                                          ((airline_directory.airline_for("DAL"), "DAL5432"),))
    board = flight_layout.compose_overhead_image(flight, width=size[0], height=size[1], traffic=False)
    box = flight_layout.header_box(*size)
    assert flight_layout.compose_header(flight, *size, 0).tobytes() == board.crop(box).tobytes()
    assert flight_layout.compose_header(flight, *size, 1).tobytes() != board.crop(box).tobytes()


def test_flight_board_fades_between_codeshare_logos_and_numbers(config, plane, tmp_path, monkeypatch):
    from adsb_radar import flight_layout
    from adsb_radar.scene import Scene

    skywest, metadata = _skywest_flight(config, plane, tmp_path, monkeypatch)
    scene = Scene((1920, 1080))
    period = flight_layout.CODESHARE_HOLD + flight_layout.CODESHARE_FADE
    box = flight_layout.header_box(1920, 1080)

    def header(at):
        return scene.render((skywest,), config, metadata, now=at).crop(box).tobytes()

    start = 1000 * period
    flight = select_flight((skywest,), config, metadata)
    operator = flight_layout.compose_header(flight, 1920, 1080, 0).tobytes()
    delta = flight_layout.compose_header(flight, 1920, 1080, 1).tobytes()
    blank = flight_layout.compose_header(flight, 1920, 1080, None).tobytes()
    assert header(start) == operator == header(start + 1)  # holding
    assert header(start + flight_layout.CODESHARE_HOLD + flight_layout.CODESHARE_FADE / 2) == blank
    assert header(start + flight_layout.CODESHARE_HOLD + flight_layout.CODESHARE_FADE * 0.25) not in (
        operator, blank, delta)
    assert header(start + period + 1) == delta
    assert header(start + 2 * period + 1) == operator


def test_radar_list_fades_codeshare_rows_in_place(config, plane, tmp_path, monkeypatch):
    from adsb_radar import flight_layout
    from adsb_radar.scene import Scene

    skywest, metadata = _skywest_flight(config, plane, tmp_path, monkeypatch)
    far = replace(skywest, distance=7)  # outside RADIUS: the idle radar with its list
    scene = Scene((1920, 1080))
    period = flight_layout.CODESHARE_HOLD + flight_layout.CODESHARE_FADE
    start = 1000 * period
    frames = [scene.render((far,), {**config, "RADAR_SWEEP": False}, metadata, now=start + t).crop((1200, 250, 1900, 360))
              for t in (0, 1, period + 1, flight_layout.CODESHARE_HOLD + flight_layout.CODESHARE_FADE / 2)]
    assert frames[0].tobytes() == frames[1].tobytes()
    assert frames[0].tobytes() != frames[2].tobytes()
    assert frames[3].tobytes() not in (frames[0].tobytes(), frames[2].tobytes())
