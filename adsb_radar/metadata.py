"""Best-effort cached aircraft types and routes. Never blocks receiver polls."""

import gzip
import io
import json
import logging
import queue
import re
import sqlite3
import sys
import threading
import time
from dataclasses import replace
from pathlib import Path

import requests

from . import flight_routes
from .route_enrichment import STALE_ROUTE_SECONDS, RouteEnricher, normalize_callsign

LOG = logging.getLogger(__name__)
TYPE_URL = "https://raw.githubusercontent.com/wiedehopf/tar1090-db/csv/aircraft.csv.gz"
ROUTE_URL = "https://api.adsbdb.com/v0/callsign/{callsign}"
ROUTESET_URL = "https://api.adsb.lol/api/0/routeset"
VRS_URL = "https://vrs-standing-data.adsb.lol/routes/{prefix}/{callsign}.json"


# Transport adapters share the validated parsers used by the renderer.
FlightRoute = flight_routes.FlightRoute
fitting_route = flight_routes.fitting_route


def fetch_route(callsign, *, url_template, timeout):
    return _fetch(callsign, url_template.format(callsign=callsign), timeout, "adsbdb")


def fetch_vrs_route(callsign, *, url_template, timeout):
    return _fetch(callsign, url_template.format(prefix=callsign[:2], callsign=callsign), timeout, "vrs")


def _fetch(callsign, url, timeout, source):
    with requests.get(url, timeout=(3, timeout), allow_redirects=False,
                      headers={"User-Agent": "adsb_radar route lookup"}) as response:
        if response.status_code == 404:
            return True, None
        if response.status_code != 200:
            LOG.info("Route provider %s for %s: HTTP %s", source, callsign, response.status_code)
            return False, None
        payload = response.json()
        if source == "adsbdb":
            route = flight_routes.parse_adsbdb(payload, callsign)
        else:
            route = flight_routes.parse_routeset_item(payload)
        if route is None or normalize_callsign(route.callsign) != callsign:
            return False, None
        return True, route


def fetch_routeset(planes, *, url, timeout):
    body = {"planes": [{"callsign": c, "lat": lat, "lng": lon} for c, lat, lon in planes]}
    with requests.post(url, json=body, timeout=(3, timeout), allow_redirects=False,
                       headers={"User-Agent": "adsb_radar route lookup"}) as response:
        if response.status_code != 200:
            return False, {}
        payload = response.json()
    if not isinstance(payload, list):
        return False, {}
    expected = {p[0] for p in planes}
    result = {}
    for item in payload:
        if not isinstance(item, dict):
            continue
        callsign = normalize_callsign(item.get("callsign"))
        if callsign not in expected:
            continue
        route = flight_routes.parse_routeset_item(item)
        if route or item.get("airport_codes") == "unknown":
            result[callsign] = route
    return True, result


class Metadata:
    def __init__(self, state):
        self.path = Path(state) / "metadata.db"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as connection:
            connection.executescript("""
                CREATE TABLE IF NOT EXISTS types (hex TEXT PRIMARY KEY, type TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS routes (callsign TEXT PRIMARY KEY, payload TEXT, updated REAL);
                CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value REAL);
            """)

        self.routes = RouteEnricher(self, sys.modules[__name__], url_template=ROUTE_URL,
                                    routeset_url=ROUTESET_URL, vrs_url=VRS_URL)

    def cached_route(self, callsign):
        with self.connect() as connection:
            row = connection.execute("SELECT payload,updated FROM routes WHERE callsign=?", (callsign,)).fetchone()
        return (True, row[0], row[1]) if row else (False, None, None)

    def store_route(self, callsign, payload, *, now):
        with self.connect() as connection:
            connection.execute("INSERT OR REPLACE INTO routes VALUES (?,?,?)", (callsign, payload, now))
            connection.commit()

    def store_route_diagnostics(self, diagnostics):
        with self.connect() as connection:
            connection.execute("INSERT OR REPLACE INTO meta VALUES ('route_diagnostics',?)",
                               (json.dumps(diagnostics),))
            connection.commit()

    def connect(self):
        # Explicitly close after each use: sqlite's context manager only commits/rolls back.
        from contextlib import closing
        return closing(sqlite3.connect(self.path, timeout=2))

    def enrich(self, aircraft):
        with self.connect() as connection:
            result = []
            for plane in aircraft:
                row = connection.execute("SELECT type FROM types WHERE hex=?", (plane.hex,)).fetchone()
                result.append(replace(plane, aircraft_type=plane.aircraft_type or (row[0] if row else None)))
        return tuple(result)

    def route(self, aircraft):
        _cached, payload, updated = self.cached_route(normalize_callsign(aircraft.callsign))
        if not payload or updated is None or not 0 <= time.time() - updated < STALE_ROUTE_SECONDS:
            return None
        route = flight_routes.FlightRoute.from_json(payload)
        if route and route.codeshares and not route.source:
            return None
        return fitting_route(route, aircraft.latitude, aircraft.longitude, aircraft.altitude_ft) if route else None

    def update_route(self, plane):
        return self.routes.refresh_aircraft([plane])

    def update_types(self):
        with self.connect() as connection:
            row = connection.execute("SELECT value FROM meta WHERE key='types_updated'").fetchone()
        if row and time.time() - row[0] < 30 * 86400:
            return
        try:
            with requests.get(TYPE_URL, timeout=(3, 30), stream=True, allow_redirects=False) as response:
                response.raise_for_status()
                chunks, length = [], 0
                for chunk in response.iter_content(65536):
                    length += len(chunk)
                    if length > 32 * 1024 * 1024:
                        raise ValueError("Type database download too large")
                    chunks.append(chunk)
            with gzip.GzipFile(fileobj=io.BytesIO(b"".join(chunks))) as stream:
                raw = stream.read(128 * 1024 * 1024 + 1)
            if len(raw) > 128 * 1024 * 1024:
                raise ValueError("Type database too large")
            rows = []
            for line in raw.decode("utf-8", errors="replace").splitlines():
                fields = line.split(";")
                if len(fields) >= 3 and re.fullmatch(r"[0-9a-fA-F]{6}", fields[0]) and re.fullmatch(r"[A-Z0-9]{1,8}", fields[2]):
                    rows.append((fields[0].lower(), fields[2]))
            if not rows:
                raise ValueError("Empty aircraft type database")
            with self.connect() as connection:
                connection.execute("DELETE FROM types")
                connection.executemany("INSERT OR REPLACE INTO types VALUES (?,?)", rows)
                connection.execute("INSERT OR REPLACE INTO meta VALUES ('types_updated',?)", (time.time(),))
                connection.commit()
        except (requests.RequestException, ValueError, OSError):
            LOG.warning("Aircraft type database refresh unavailable; keeping cached types")


class MetadataWorker(threading.Thread):
    def __init__(self, cache, config):
        super().__init__(name="metadata-worker", daemon=True)
        self.cache, self.config = cache, config
        self.pending = queue.Queue(maxsize=1)
        self.stopping = threading.Event()

    def submit(self, aircraft):
        try:
            self.pending.get_nowait()
        except queue.Empty:
            pass
        # The nearest planes: the flight board's and the radar list's (up to 10 rows at 4K).
        self.pending.put_nowait(aircraft[:10])

    def run(self):
        if self.config["TYPE_LOOKUP"]:
            self.cache.update_types()
        while not self.stopping.is_set():
            try:
                aircraft = self.pending.get(timeout=1)
            except queue.Empty:
                continue
            if self.config["ROUTE_LOOKUP"]:
                if not self.stopping.is_set():
                    try:
                        self.cache.routes.refresh_aircraft(aircraft)
                    except (sqlite3.Error, OSError):
                        LOG.warning("Route cache temporarily unavailable", exc_info=True)
