from dataclasses import replace

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
