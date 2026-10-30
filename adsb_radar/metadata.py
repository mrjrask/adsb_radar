"""Best-effort cached aircraft types and routes. Never blocks receiver polls."""

import gzip
import io
import logging
import queue
import re
import sqlite3
import threading
import time
from dataclasses import replace
from pathlib import Path

import requests

from . import flight_routes

LOG = logging.getLogger(__name__)
TYPE_URL = "https://raw.githubusercontent.com/wiedehopf/tar1090-db/csv/aircraft.csv.gz"
ROUTE_URL = "https://api.adsbdb.com/v0/callsign/{}"


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
        with self.connect() as connection:
            row = connection.execute("SELECT payload,updated FROM routes WHERE callsign=?", (aircraft.callsign,)).fetchone()
        if not row or not row[0] or time.time() - row[1] > 86400:
            return None
        route = flight_routes.FlightRoute.from_json(row[0])
        return flight_routes.fitting_route(route, aircraft.latitude, aircraft.longitude, aircraft.altitude_ft) if route else None

    def update_route(self, plane):
        if not flight_routes.is_flight_callsign(plane.callsign):
            return
        with self.connect() as connection:
            row = connection.execute("SELECT payload,updated FROM routes WHERE callsign=?", (plane.callsign,)).fetchone()
        if row and time.time() - row[1] < (86400 if row[0] else 3600):
            return
        try:
            with requests.get(ROUTE_URL.format(plane.callsign), timeout=(3, 4), allow_redirects=False) as response:
                if response.status_code not in (200, 404):
                    return
                route = flight_routes.parse_adsbdb(response.json(), plane.callsign) if response.status_code == 200 else None
            with self.connect() as connection:
                connection.execute("INSERT OR REPLACE INTO routes VALUES (?,?,?)",
                                   (plane.callsign, route.to_json() if route else None, time.time()))
                connection.commit()
        except (requests.RequestException, ValueError):
            LOG.info("Route lookup unavailable; continuing with receiver data")

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
        self.pending.put_nowait(aircraft[:3])

    def run(self):
        if self.config["TYPE_LOOKUP"]:
            self.cache.update_types()
        while not self.stopping.is_set():
            try:
                aircraft = self.pending.get(timeout=1)
            except queue.Empty:
                continue
            if self.config["ROUTE_LOOKUP"]:
                for plane in aircraft:
                    if not self.stopping.is_set():
                        self.cache.update_route(plane)
