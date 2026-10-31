"""Route models and validation adapted from desk_display services/flight_routes."""
from __future__ import annotations

import json
import math
import re
from dataclasses import asdict, dataclass, replace
from typing import Any, Optional

from .models import EARTH_RADIUS_NM, haversine_distance, initial_bearing
from .route_enrichment import normalize_callsign

LOCAL_AIRPORT_RADIUS_NM = 50.0


@dataclass(frozen=True)
class Airport:
    iata: str
    icao: str
    name: str
    municipality: str
    latitude: Optional[float]
    longitude: Optional[float]

    @property
    def code(self) -> str:
        return self.iata or self.icao

    @property
    def short_name(self) -> str:
        return shorten_airport_name(self.name) or self.municipality or self.code


@dataclass(frozen=True)
class FlightRoute:
    callsign: str
    airline_name: str
    airline_icao: str
    airline_iata: str
    origin: Optional[Airport]
    destination: Optional[Airport]
    # Every stop of a multi-leg flight number, in order (empty for one leg).
    stops: tuple[Airport, ...] = ()
    # Marketed flights this route was found under ("UAL5432" for SKW5432).
    codeshares: tuple[str, ...] = ()
    source: str = ""

    def to_json(self) -> str:
        return json.dumps(asdict(self), sort_keys=True)

    @classmethod
    def from_json(cls, text: Optional[str]) -> Optional["FlightRoute"]:
        if not text:
            return None
        try:
            data = json.loads(text)
            if not isinstance(data, dict):
                return None
            for key in ("origin", "destination"):
                if data.get(key) is not None and _airport_from_dict(data[key]) is None:
                    return None
            if any(_airport_from_dict(stop) is None for stop in data.get("stops") or ()):
                return None
            return cls(
                callsign=normalize_callsign(data.get("callsign")),
                airline_name=str(data.get("airline_name") or ""),
                airline_icao=str(data.get("airline_icao") or ""),
                airline_iata=str(data.get("airline_iata") or ""),
                source=str(data.get("source") or ""),
                origin=_airport_from_dict(data.get("origin")),
                destination=_airport_from_dict(data.get("destination")),
                stops=tuple(a for a in map(_airport_from_dict, data.get("stops") or ()) if a is not None),
                codeshares=tuple(str(c).strip().upper() for c in data.get("codeshares") or () if c),
            )
        except (TypeError, ValueError, AttributeError):
            return None


def is_flight_callsign(callsign: Optional[str]) -> bool:
    return bool(normalize_callsign(callsign))


def _airport_from_dict(data: Any) -> Optional[Airport]:
    if not isinstance(data, dict):
        return None

    def number(value: Any) -> Optional[float]:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return None
        return float(value) if math.isfinite(value) else None

    lat = data.get("latitude", data.get("lat"))
    lon = data.get("longitude", data.get("lon"))
    if (lat is not None and number(lat) is None) or (lon is not None and number(lon) is None):
        return None
    airport = Airport(
        iata=str(data.get("iata") or data.get("iata_code") or "").strip().upper(),
        icao=str(data.get("icao") or data.get("icao_code") or "").strip().upper(),
        name=str(data.get("name") or "").strip(),
        municipality=str(data.get("municipality") or data.get("location") or "").strip(),
        latitude=number(data.get("latitude", data.get("lat"))),
        longitude=number(data.get("longitude", data.get("lon"))),
    )
    if airport.latitude is not None and not -90 <= airport.latitude <= 90:
        return None
    if airport.longitude is not None and not -180 <= airport.longitude <= 180:
        return None
    return airport if airport.code else None


def parse_adsbdb(payload: Any, callsign: str = "") -> Optional[FlightRoute]:
    """A :class:`FlightRoute` from an adsbdb ``/callsign`` reply, or None."""

    response = payload.get("response") if isinstance(payload, dict) else None
    route = response.get("flightroute") if isinstance(response, dict) else None
    if not isinstance(route, dict):
        return None
    if not normalize_callsign(route.get("callsign_icao") or route.get("callsign")):
        return None
    airline = route.get("airline") if isinstance(route.get("airline"), dict) else {}
    origin = _airport_from_dict(route.get("origin"))
    destination = _airport_from_dict(route.get("destination"))
    if (route.get("origin") and origin is None) or (route.get("destination") and destination is None):
        return None
    if route.get("midpoint") and _airport_from_dict(route["midpoint"]) is None:
        return None
    if origin is None and destination is None:
        return None
    stops = tuple(a for a in (origin, _airport_from_dict(route.get("midpoint")), destination) if a)
    return FlightRoute(
        callsign=normalize_callsign(route.get("callsign_icao") or route.get("callsign") or callsign),
        stops=stops if len(stops) > 2 else (),
        airline_name=str(airline.get("name") or "").strip(),
        airline_icao=str(airline.get("icao") or "").strip().upper(),
        airline_iata=str(airline.get("iata") or "").strip().upper(),
        origin=origin,
        destination=destination,
    )


def parse_routeset_item(item: Any) -> Optional[FlightRoute]:
    """A :class:`FlightRoute` from one adsb.lol ``routeset`` entry, or None when unknown."""

    if not isinstance(item, dict) or str(item.get("airport_codes") or "unknown") == "unknown":
        return None
    airports = item.get("_airports") if isinstance(item.get("_airports"), list) else []
    stops = tuple(a for a in map(_airport_from_dict, airports) if a is not None)
    if not stops or len(stops) != len(airports):
        return None
    airline = str(item.get("airline_code") or "").strip().upper()
    return FlightRoute(
        callsign=normalize_callsign(item.get("callsign")),
        airline_name="",
        airline_icao="" if airline == "UNKNOWN" else airline,
        airline_iata="",
        origin=stops[0],
        destination=stops[-1] if len(stops) > 1 else None,
        stops=stops if len(stops) > 2 else (),
    )



_AIRPORT_WORDS = (
    (re.compile(r"\bInternational\b", re.I), "Intl"),
    (re.compile(r"\bIntercontinental\b", re.I), "Intcntl"),
    (re.compile(r"\bRegional\b", re.I), "Rgnl"),
    (re.compile(r"\bMunicipal\b", re.I), "Muni"),
)


def shorten_airport_name(name: str) -> str:
    """'Dubai International Airport' -> 'Dubai Intl', the way flight boards print it."""

    text = re.sub(r"\s+(Air ?port|Airfield|Aerodrome)$", "", (name or "").strip(), flags=re.I)
    for pattern, short in _AIRPORT_WORDS:
        text = pattern.sub(short, text)
    return re.sub(r"\s{2,}", " ", text).strip()


def _distance_from_home(airport: Optional[Airport], home: tuple[Optional[float], Optional[float]]) -> Optional[float]:
    if airport is None or airport.latitude is None or airport.longitude is None:
        return None
    if home[0] is None or home[1] is None:
        return None
    return haversine_distance(home[0], home[1], airport.latitude, airport.longitude, unit="nm")


ROUTE_OFF_TRACK_MIN_NM = 100.0


ROUTE_OFF_TRACK_SHARE = 0.25


ROUTE_LOW_ALTITUDE_FT = 10000


ROUTE_LOW_AIRPORT_NM = 120.0


def route_fits(route: FlightRoute, latitude: float, longitude: float, altitude_ft: Optional[int] = None) -> bool:
    """Whether an aircraft at this position could be flying *route*.

    False for a route that is clearly another flight's, e.g. "IAH→EWR" on a
    plane at 5,700 ft over Chicago. True when the airports lack coordinates.
    """

    ends = [a for a in (route.origin, route.destination)
            if a is not None and a.latitude is not None and a.longitude is not None]
    if len(ends) < 2:
        return True
    origin, destination = ends
    length = haversine_distance(origin.latitude, origin.longitude, destination.latitude, destination.longitude)
    from_origin = haversine_distance(origin.latitude, origin.longitude, latitude, longitude)
    to_destination = haversine_distance(latitude, longitude, destination.latitude, destination.longitude)
    if altitude_ft is not None and altitude_ft < ROUTE_LOW_ALTITUDE_FT:
        if min(from_origin, to_destination) > ROUTE_LOW_AIRPORT_NM:
            return False
    tolerance = max(ROUTE_OFF_TRACK_MIN_NM, ROUTE_OFF_TRACK_SHARE * length)
    if length < 1.0:
        return from_origin <= tolerance
    angle = math.radians(
        initial_bearing(origin.latitude, origin.longitude, latitude, longitude)
        - initial_bearing(origin.latitude, origin.longitude, destination.latitude, destination.longitude)
    )
    off_track = abs(math.asin(max(-1.0, min(1.0, math.sin(from_origin / EARTH_RADIUS_NM) * math.sin(angle)))))
    if off_track * EARTH_RADIUS_NM > tolerance:
        return False
    # Beyond either end of the route (the great circle continues round the globe).
    return from_origin <= length + tolerance and to_destination <= length + tolerance


def legs(route: FlightRoute) -> list[FlightRoute]:
    """Each leg of a multi-leg flight number as its own route (just *route* for one leg)."""

    if len(route.stops) < 3:
        return [route]
    return [replace(route, origin=a, destination=b, stops=()) for a, b in zip(route.stops, route.stops[1:])]


def fitting_route(
    route: FlightRoute, latitude: float, longitude: float, altitude_ft: Optional[int] = None
) -> Optional[FlightRoute]:
    """The leg of *route* an aircraft at this position is flying, or None when none fits.

    Of several legs that fit (an out-and-back), the one the aircraft is most
    nearly between the airports of.
    """

    best: Optional[tuple[float, FlightRoute]] = None
    for leg in legs(route):
        if not route_fits(leg, latitude, longitude, altitude_ft):
            continue
        detour = 0.0
        a, b = leg.origin, leg.destination
        if a and b and None not in (a.latitude, a.longitude, b.latitude, b.longitude):
            detour = (haversine_distance(a.latitude, a.longitude, latitude, longitude)
                      + haversine_distance(latitude, longitude, b.latitude, b.longitude)
                      - haversine_distance(a.latitude, a.longitude, b.latitude, b.longitude))
        if best is None or detour < best[0]:
            best = (detour, leg)
    return best[1] if best else None


ARRIVING = "Arriving from"


DEPARTING = "Departing to"


EN_ROUTE = "En route to"


FROM = "Flying from"


def flight_phase(route: FlightRoute, home: tuple[Optional[float], Optional[float]]) -> tuple[str, Optional[Airport]]:
    """The board's phrase and airport: "Arriving from Dubai Intl", "Departing to ...", "En route to ..."."""

    to_dest = _distance_from_home(route.destination, home)
    from_origin = _distance_from_home(route.origin, home)
    dest_local = to_dest is not None and to_dest <= LOCAL_AIRPORT_RADIUS_NM
    origin_local = from_origin is not None and from_origin <= LOCAL_AIRPORT_RADIUS_NM
    if dest_local and (not origin_local or to_dest <= from_origin):
        return ARRIVING, route.origin
    if origin_local:
        return DEPARTING, route.destination
    if route.destination is not None:
        return EN_ROUTE, route.destination
    return FROM, route.origin
