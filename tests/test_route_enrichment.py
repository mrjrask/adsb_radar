"""Contract tests run unchanged against both applications' route adapters."""

import json
from dataclasses import dataclass, replace
from types import SimpleNamespace

import pytest

try:
    from adsb_radar import flight_routes as routes
    from adsb_radar.route_enrichment import RouteEnricher, normalize_callsign
except ImportError:
    from services import flight_routes as routes
    from services.route_enrichment import RouteEnricher, normalize_callsign


@dataclass(frozen=True)
class Plane:
    callsign: str = "UAL1"
    latitude: float = 41.98
    longitude: float = -87.9
    altitude_ft: int = 5000
    distance: float = 1


ORD = routes.Airport("ORD", "KORD", "O'Hare", "Chicago", 41.98, -87.90)
SEA = routes.Airport("SEA", "KSEA", "Seattle", "Seattle", 47.45, -122.31)
IAH = routes.Airport("IAH", "KIAH", "Houston", "Houston", 29.98, -95.34)
EWR = routes.Airport("EWR", "KEWR", "Newark", "Newark", 40.69, -74.17)
ROUTE = routes.FlightRoute("UAL1", "United", "UAL", "UA", SEA, ORD)


class Store:
    def __init__(self):
        self.rows = {}

    def cached_route(self, callsign):
        return (True, *self.rows[callsign]) if callsign in self.rows else (False, None, None)

    def store_route(self, callsign, payload, *, now):
        self.rows[callsign] = (payload, now)


def resolver(*, batch=None, file=None, single=None):
    asked = []

    def fetch(name, result):
        def call(*args, **kwargs):
            asked.append((name, args[0]))
            if isinstance(result, Exception):
                raise result
            return result
        return call

    backend = SimpleNamespace(
        FlightRoute=routes.FlightRoute, fitting_route=routes.fitting_route,
        fetch_routeset=fetch("batch", batch), fetch_vrs_route=fetch("file", file),
        fetch_route=fetch("single", single),
    )
    store = Store()
    engine = RouteEnricher(store, backend, routeset_url="batch" if batch is not None else "",
                           vrs_url="file" if file is not None else "",
                           url_template="single" if single is not None else "")
    return engine, store, asked


@pytest.mark.parametrize("value,expected", [
    (" ual 0001 ", "UAL1"), ("eja75a", "EJA75A"), ("BAW01AB", "BAW01AB"),
    (None, ""), ("N12345", ""), ("C-GABC", ""), ("AA123", ""),
    ("UAL1/../../x", ""), ("UAL123456", ""),
])
def test_normalization(value, expected):
    assert normalize_callsign(value) == expected


def test_cache_dedupe_sources_and_coverage():
    engine, store, asked = resolver(batch=(True, {"UAL1": ROUTE}), single=(True, None))
    assert engine.refresh_aircraft([Plane(" ual0001 "), Plane()], now=1000) == 1
    assert len(asked) == 1 and len(asked[0][1]) == 1
    found = routes.FlightRoute.from_json(store.rows["UAL1"][0])
    assert found.source == "adsb.lol"
    engine.refresh_aircraft([Plane()], now=1001)
    assert len(asked) == 1
    assert engine.diagnostics["eligible"] == engine.diagnostics["matched"] == 1
    assert engine.diagnostics["coverage_percent"] == 100
    assert engine.last_outcome == {}  # no stale per-round outcomes


def test_static_fallback_for_omitted_batch_entry():
    engine, store, asked = resolver(batch=(True, {}), file=(True, ROUTE), single=(True, None))
    engine.refresh_aircraft([Plane()], now=1000)
    assert [a[0] for a in asked] == ["batch", "file"]
    assert json.loads(store.rows["UAL1"][0])["source"] == "adsb.lol file"


def test_invalid_position_route_falls_back_and_is_not_rendered():
    misfit = replace(ROUTE, origin=IAH, destination=EWR)
    engine, store, asked = resolver(batch=(True, {"UAL1": misfit}), single=(True, ROUTE))
    engine.refresh_aircraft([Plane()], now=1000)
    assert json.loads(store.rows["UAL1"][0])["source"] == "adsbdb"
    assert engine.diagnostics["matched"] == 1
    assert [a[0] for a in asked] == ["batch", "single"]


def test_miss_retried_after_five_minutes():
    engine, store, asked = resolver(single=(True, None))
    engine.refresh_aircraft([Plane()], now=1000)
    engine.refresh_aircraft([Plane()], now=1299)
    assert len(asked) == 1 and store.rows["UAL1"][0] is None
    engine.refresh_aircraft([Plane()], now=1300)
    assert len(asked) == 2


def test_outage_is_not_a_negative_cache_and_each_provider_backs_off():
    engine, store, asked = resolver(batch=(False, {}), file=TimeoutError(), single=(False, None))
    engine.refresh_aircraft([Plane()], now=1000)
    engine.refresh_aircraft([Plane("UAL2")], now=1001)
    assert not store.rows and len(asked) == 3
    engine.refresh_aircraft([Plane()], now=1120)
    assert len(asked) == 6
    assert engine.diagnostics["providers"]["vrs_failures"] == 2


def test_one_source_miss_and_another_failure_stays_pending():
    engine, store, _ = resolver(batch=(True, {"UAL1": None}), single=(False, None))
    engine.refresh_aircraft([Plane()], now=1000)
    assert not store.rows and engine.last_outcome == {"UAL1": "waiting"}


def test_rejected_route_retries_before_positive_ttl():
    misfit = replace(ROUTE, origin=IAH, destination=EWR)
    engine, store, asked = resolver(single=(True, ROUTE))
    store.store_route("UAL1", misfit.to_json(), now=1000)
    engine.refresh_aircraft([Plane()], now=1299)
    assert not asked
    engine.refresh_aircraft([Plane()], now=1300)
    assert engine.diagnostics["matched"] == 1


def test_corrupt_future_and_guessed_cache_entries_are_refreshed():
    for payload, updated in [("garbage", 1000), (ROUTE.to_json(), 2000),
                             (replace(ROUTE, codeshares=("DAL1",)).to_json(), 1000)]:
        engine, store, asked = resolver(single=(True, ROUTE))
        store.store_route("UAL1", payload, now=updated)
        engine.refresh_aircraft([Plane()], now=1001)
        assert len(asked) == 1


def test_stale_good_route_survives_provider_failure_without_extending_its_age():
    engine, store, _ = resolver(single=(False, None))
    store.store_route("UAL1", ROUTE.to_json(), now=1)
    engine.refresh_aircraft([Plane()], now=100000)
    assert store.rows["UAL1"] == (ROUTE.to_json(), 1)
    assert engine.diagnostics["matched"] == 1


def test_request_budgets_and_fairness():
    engine, store, asked = resolver(single=(True, None))
    planes = [Plane(f"UAL{i}", distance=i) for i in range(1, 11)]
    engine.refresh_aircraft(planes, now=1000)
    assert len(asked) == 3
    engine.refresh_aircraft(planes, now=1001)
    assert len(asked) == 6 and len(store.rows) == 6


def test_adsbdb_midpoint_and_json_roundtrip():
    from dataclasses import asdict
    payload = {"response": {"flightroute": {"callsign": "UAL1", "origin": asdict(SEA),
               "midpoint": asdict(ORD), "destination": asdict(EWR)}}}
    route = routes.parse_adsbdb(payload)
    assert route.stops == (SEA, ORD, EWR)
    assert len(routes.legs(route)) == 2
    assert routes.FlightRoute.from_json(route.to_json()) == route


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), 91])
def test_invalid_airport_latitude_is_not_a_plausible_route(bad):
    from dataclasses import asdict
    origin = {**asdict(SEA), "latitude": bad}
    payload = {"response": {"flightroute": {"callsign": "UAL1", "origin": origin,
               "destination": asdict(ORD)}}}
    assert routes.parse_adsbdb(payload) is None


class Response:
    def __init__(self, status, payload):
        self.status_code, self.payload = status, payload

    def json(self):
        return self.payload

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass


def transport(monkeypatch, response):
    try:
        from adsb_radar import metadata as backend
        monkeypatch.setattr(backend.requests, "get", lambda *a, **k: response)
        monkeypatch.setattr(backend.requests, "post", lambda *a, **k: response)
    except ImportError:
        backend = routes
        monkeypatch.setattr(backend, "http_get", lambda *a, **k: response)
        monkeypatch.setattr(backend, "http_post", lambda *a, **k: response)
    return backend


@pytest.mark.parametrize("status,answered", [(404, True), (403, False), (429, False), (503, False)])
def test_transport_distinguishes_provider_failure_from_unknown(monkeypatch, status, answered):
    backend = transport(monkeypatch, Response(status, {}))
    assert backend.fetch_route("UAL1", url_template="https://example/{callsign}", timeout=1) == (answered, None)
    assert backend.fetch_vrs_route("UAL1", url_template="https://example/{callsign}", timeout=1) == (answered, None)


def test_transport_rejects_malformed_and_wrong_callsign_replies(monkeypatch):
    from dataclasses import asdict
    for payload in [{}, {"response": {"flightroute": {"callsign": "DAL1", "origin": asdict(SEA),
                     "destination": asdict(ORD)}}}]:
        backend = transport(monkeypatch, Response(200, payload))
        assert backend.fetch_route("UAL1", url_template="https://example/{callsign}", timeout=1) == (False, None)


def test_batch_does_not_convert_missing_or_malformed_items_into_misses(monkeypatch):
    backend = transport(monkeypatch, Response(200, [
        {"callsign": "UAL1", "airport_codes": "KSEA-KORD", "_airports": []},
        {"callsign": "DAL1", "airport_codes": "unknown"},
    ]))
    assert backend.fetch_routeset([("UAL1", 42, -88)], url="https://example", timeout=1) == (True, {})


def test_empty_batch_success_code_does_not_suppress_static_fallback(monkeypatch):
    backend = transport(monkeypatch, Response(201, None))
    assert backend.fetch_routeset([("UAL1", 42, -88)], url="https://example", timeout=1) == (False, {})
