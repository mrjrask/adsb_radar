"""Shared route resolver, vendored identically in adsb_radar and desk_display.

Only the storage and HTTP/model adapters depend on the application. Never infer
codeshares from matching flight-number digits: that is not an identity mapping.
"""

import logging
import re
import time
from collections import Counter
from dataclasses import replace

LOG = logging.getLogger(__name__)
ROUTE_TTL_SECONDS = 86400
NO_ROUTE_TTL_SECONDS = 300
MISFIT_RETRY_SECONDS = 300
FAILURE_BACKOFF_SECONDS = 120
ROUTESET_MAX_PLANES = 100
VRS_LOOKUPS_PER_CYCLE = 10
LOOKUPS_PER_CYCLE = 3
STALE_ROUTE_SECONDS = 7 * 86400


def normalize_callsign(value):
    """Canonical ICAO callsign; retain suffixes and reject registrations/URLs.

    ADS-B uses ICAO designators. IATA codes are intentionally not expanded:
    several airlines can share one IATA code and it is not an operator identity.
    Numeric flight numbers are unpadded; alphanumeric ATC identifiers are kept.
    """
    text = re.sub(r"[ \t\r\n]+", "", value.upper()) if isinstance(value, str) else ""
    match = re.fullmatch(r"([A-Z]{3})([0-9][A-Z0-9]{0,4})", text)
    if not match:
        return ""
    prefix, number = match.groups()
    if number.isdigit():
        number = str(int(number))
    return prefix + number


def route_is_fresh(cached, payload, fetched_at, now):
    ttl = ROUTE_TTL_SECONDS if payload else NO_ROUTE_TTL_SECONDS
    return bool(cached and fetched_at is not None and 0 <= now - fetched_at < ttl)


class RouteEnricher:
    """Local cache first, batched VRS, static VRS, then adsbdb, within budgets."""

    def __init__(self, store, backend, *, url_template, routeset_url="", vrs_url="", timeout=5.0):
        self.store, self.backend = store, backend
        self.url_template, self.routeset_url, self.vrs_url = url_template, routeset_url, vrs_url
        self.timeout = timeout
        self.retry_after = {}
        self.counters = Counter()
        self.last_outcome = {}
        self.diagnostics = {}

    def _cached(self, callsign):
        cached, payload, fetched_at = self.store.cached_route(callsign)
        return cached, self.backend.FlightRoute.from_json(payload), payload, fetched_at

    def _fits(self, route, plane):
        return route and self.backend.fitting_route(
            route, plane.latitude, plane.longitude, plane.altitude_ft
        )

    def _due(self, plane, now):
        if now < self.retry_after.get("flight:" + plane.callsign, 0):
            return False
        cached, route, payload, fetched_at = self._cached(plane.callsign)
        if route and route.codeshares and not route.source:
            return True  # invalidate old guessed codeshare routes
        if not route_is_fresh(cached, payload, fetched_at, now):
            return True
        if payload and route is None:
            return True  # corrupt cache is not a confirmed miss
        if route and (not self._fits(route, plane) or not route.origin or not route.destination):
            return now - fetched_at >= MISFIT_RETRY_SECONDS
        return False

    def _request(self, source, function, now, *args, **kwargs):
        if now < self.retry_after.get(source, 0):
            return False, None
        self.counters[source + "_requests"] += 1
        try:
            answered, result = function(*args, **kwargs)
        except Exception:  # an adapter must never stop position polling
            LOG.warning("Route provider %s unavailable", source, exc_info=True)
            answered, result = False, None
        if not answered:
            self.counters[source + "_failures"] += 1
            self.retry_after[source] = now + FAILURE_BACKOFF_SECONDS
        return answered, result

    def refresh_aircraft(self, aircraft, *, now=None):
        now = time.time() if now is None else now
        nearest = {}
        for plane in aircraft:
            callsign = normalize_callsign(plane.callsign)
            if callsign and (callsign not in nearest or (plane.distance or 0) < (nearest[callsign].distance or 0)):
                nearest[callsign] = replace(plane, callsign=callsign)
        ordered = sorted(nearest.values(), key=lambda p: (p.distance or 0, p.callsign))
        due = [p for p in ordered if self._due(p, now)][:ROUTESET_MAX_PLANES]
        outcome = {}
        batch = {}
        if due and self.routeset_url:
            ok, result = self._request(
                "routeset", self.backend.fetch_routeset, now,
                [(p.callsign, p.latitude, p.longitude) for p in due],
                url=self.routeset_url, timeout=self.timeout,
            )
            batch = result if ok and isinstance(result, dict) else {}
        writes = files = singles = 0
        for plane in due:
            callsign = plane.callsign
            # Only entries actually returned count as answers; omitted entries retry.
            answered = callsign in batch
            found = batch.get(callsign)
            source = "adsb.lol"
            complete = bool(found and found.origin and found.destination and self._fits(found, plane))
            if not answered and self.vrs_url and files < VRS_LOOKUPS_PER_CYCLE:
                files += 1
                answered, found = self._request(
                    "vrs", self.backend.fetch_vrs_route, now, callsign,
                    url_template=self.vrs_url, timeout=self.timeout,
                )
                source = "adsb.lol file"
                complete = bool(found and found.origin and found.destination and self._fits(found, plane))
            all_answered = answered if (self.routeset_url or self.vrs_url) else True
            if not complete and self.url_template:
                ok, other = False, None
                if singles < LOOKUPS_PER_CYCLE:
                    singles += 1
                    ok, other = self._request(
                        "adsbdb", self.backend.fetch_route, now, callsign,
                        url_template=self.url_template, timeout=self.timeout,
                    )
                all_answered = all_answered and ok
                if other and self._fits(other, plane):
                    found, source = other, "adsbdb"
                elif found is None and other:
                    found, source = other, "adsbdb"
            if found:
                _cached, previous, _payload, _updated = self._cached(callsign)
                if previous and not previous.codeshares and self._fits(previous, plane):
                    if not self._fits(found, plane) or (
                        previous.origin and previous.destination and (not found.origin or not found.destination)
                    ):
                        outcome[callsign] = "keeping cached route; refresh incomplete"
                        self.retry_after["flight:" + callsign] = now + FAILURE_BACKOFF_SECONDS
                        continue
                found = replace(found, callsign=callsign, source=source, codeshares=())
                self.store.store_route(callsign, found.to_json(), now=now)
                writes += 1
                outcome[callsign] = f"route ({source})" if self._fits(found, plane) else "route does not fit"
            elif all_answered and (self.routeset_url or self.vrs_url or self.url_template):
                self.store.store_route(callsign, None, now=now)
                writes += 1
                outcome[callsign] = "no route"
            else:
                outcome[callsign] = "waiting"
        self.last_outcome = outcome
        counts = Counter()
        for plane in ordered:
            cached, route, payload, fetched_at = self._cached(plane.callsign)
            if route and route.codeshares and not route.source:
                counts["unverified"] += 1
            elif route and fetched_at is not None and 0 <= now - fetched_at < STALE_ROUTE_SECONDS:
                if self._fits(route, plane):
                    counts["matched" if route.origin and route.destination else "partial"] += 1
                else:
                    counts["rejected"] += 1
            else:
                counts["unknown" if cached and not payload else "pending"] += 1
        self.diagnostics = {
            "updated": now, "eligible": len(ordered), **dict(counts),
            "coverage_percent": round(100 * counts["matched"] / len(ordered), 1) if ordered else None,
            "providers": dict(self.counters), "last_outcome": outcome,
        }
        if hasattr(self.store, "store_route_diagnostics"):
            self.store.store_route_diagnostics(self.diagnostics)
        if outcome:
            LOG.info("ADS-B routes: %s/%s matched; %s", counts["matched"], len(ordered), outcome)
        return writes
