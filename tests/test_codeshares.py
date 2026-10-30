from dataclasses import replace

import pytest

from adsb_radar import flight_routes
from adsb_radar.codeshares import codeshare_callsigns
from adsb_radar.metadata import Metadata
from adsb_radar.scene import select_flight

ORD = flight_routes.Airport("ORD", "KORD", "Chicago O'Hare International Airport", "Chicago", 41.98, -87.90)
LNK = flight_routes.Airport("LNK", "KLNK", "Lincoln Airport", "Lincoln", 40.85, -96.76)
IAH = flight_routes.Airport("IAH", "KIAH", "George Bush Intercontinental", "Houston", 29.98, -95.34)
EWR = flight_routes.Airport("EWR", "KEWR", "Newark Liberty International Airport", "Newark", 40.69, -74.17)


def _route(callsign, origin, destination, name="United Airlines", iata="UA"):
    return flight_routes.FlightRoute(callsign, name, callsign[:3], iata, origin, destination)


def _metadata(tmp_path, monkeypatch, routes):
    metadata = Metadata(tmp_path)
    asked = []

    def fake_fetch(callsign):
        asked.append(callsign)
        return True, routes.get(callsign)

    monkeypatch.setattr(metadata, "_fetch_route", fake_fetch)
    return metadata, asked


def test_codeshare_callsigns_use_the_marketing_airlines_flight_number():
    assert codeshare_callsigns("skw5432") == ("UAL5432", "DAL5432", "AAL5432", "ASA5432")
    assert codeshare_callsigns("ENY3456") == ("AAL3456",)
    assert codeshare_callsigns("UAL123") == ()
    assert codeshare_callsigns("SKWABC") == ()
    assert codeshare_callsigns(None) == ()


def test_unknown_regional_flight_takes_its_codeshare_route(config, plane, tmp_path, monkeypatch):
    skywest = replace(plane, callsign="SKW5432", latitude=41.95, longitude=-88.3, altitude_ft=5000)
    # UAL5432 is another day's flight (IAH-EWR); DAL5432 is the one this plane can be flying.
    metadata, asked = _metadata(tmp_path, monkeypatch, {
        "UAL5432": _route("UAL5432", IAH, EWR), "DAL5432": _route("DAL5432", LNK, ORD, "Delta Air Lines", "DL")})
    metadata.update_route(skywest)
    assert asked == ["SKW5432", "UAL5432", "DAL5432"]  # stops at the first that fits
    route = metadata.route(skywest)
    assert (route.origin.code, route.destination.code, route.codeshares) == ("LNK", "ORD", ("DAL5432",))
    assert (route.callsign, route.airline_icao, route.airline_name) == ("SKW5432", "SKW", "")
    flight = select_flight((skywest,), {**config, "RADIUS": 50}, metadata)
    assert flight.airline.icao == "SKW" and flight.route.codeshares == ("DAL5432",)


def test_known_regional_flight_records_the_codeshare_that_agrees(plane, tmp_path, monkeypatch):
    envoy = replace(plane, callsign="ENY3456", latitude=41.95, longitude=-88.3, altitude_ft=5000)
    own = _route("ENY3456", LNK, ORD, "Envoy Air", "MQ")
    metadata, asked = _metadata(tmp_path, monkeypatch, {"ENY3456": own, "AAL3456": _route("AAL3456", LNK, ORD)})
    metadata.update_route(envoy)
    route = metadata.route(envoy)
    assert route == replace(own, codeshares=("AAL3456",)) and asked == ["ENY3456", "AAL3456"]
    assert flight_routes.FlightRoute.from_json(route.to_json()) == route

    # A codeshare on a different route is not this flight.
    other = replace(envoy, callsign="ENY3457")
    metadata, _ = _metadata(tmp_path / "b", monkeypatch, {"ENY3457": replace(own, callsign="ENY3457"),
                                                         "AAL3457": _route("AAL3457", ORD, LNK)})
    metadata.update_route(other)
    assert metadata.route(other).codeshares == ()


def test_mainline_flights_ask_only_once(plane, tmp_path, monkeypatch):
    metadata, asked = _metadata(tmp_path, monkeypatch, {})
    metadata.update_route(plane)
    assert asked == ["DAL123"] and metadata.route(plane) is None


def _skywest_flight(config, plane, tmp_path, monkeypatch):
    skywest = replace(plane, callsign="SKW5432", aircraft_type="CRJ9")
    metadata, _ = _metadata(tmp_path, monkeypatch, {})
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


def test_a_failed_codeshare_lookup_keeps_the_operating_route(plane, tmp_path, monkeypatch):
    import requests

    envoy = replace(plane, callsign="ENY3456", latitude=41.95, longitude=-88.3, altitude_ft=5000)
    own = _route("ENY3456", LNK, ORD, "Envoy Air", "MQ")
    metadata = Metadata(tmp_path)

    def fake_fetch(callsign):
        if callsign == "AAL3456":
            raise requests.ConnectionError("down")
        return True, own

    monkeypatch.setattr(metadata, "_fetch_route", fake_fetch)
    metadata.update_route(envoy)
    assert metadata.route(envoy) == own
