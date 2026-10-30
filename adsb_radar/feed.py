"""Read dump1090/readsb JSON directly; poll receivers outside the render loop."""

import concurrent.futures
import logging
import math
import queue
import re
import threading
import time
from urllib.parse import urlsplit

import requests

from .config import display_settings
from .models import LiveAircraft, haversine_distance, initial_bearing

LOG = logging.getLogger(__name__)
PATHS = ("/data/aircraft.json", "/tar1090/data/aircraft.json", "/skyaware/data/aircraft.json",
         "/dump1090-fa/data/aircraft.json")
MAX_POSITION_AGE = 30


def number(value):
    if isinstance(value, bool):
        return None
    try:
        value = float(value)
        return value if math.isfinite(value) else None
    except (TypeError, ValueError):
        return None


def parse_aircraft(payload, source, home, unit="nm", now=None):
    now = time.time() if now is None else now
    if not isinstance(payload, dict) or not isinstance(payload.get("aircraft"), list):
        raise ValueError("Receiver did not return an aircraft.json object")
    reported = number(payload.get("now"))
    age = max(0, now - reported) if reported is not None else 0
    if age > MAX_POSITION_AGE:
        raise ValueError("Receiver data is stale; check receiver and Pi clocks")
    result = []
    for entry in payload["aircraft"]:
        if not isinstance(entry, dict):
            continue
        lat, lon = number(entry.get("lat")), number(entry.get("lon"))
        seen = number(entry.get("seen_pos"))
        hex_id = str(entry.get("hex", "")).lower()
        if (lat is None or lon is None or not -90 <= lat <= 90 or not -180 <= lon <= 180
                or seen is None or seen < 0 or seen + age > MAX_POSITION_AGE
                or not re.fullmatch(r"~?[0-9a-f]{6}", hex_id)):
            continue
        altitude = entry.get("alt_baro", entry.get("alt_geom"))
        if altitude == "ground":
            continue
        altitude = number(altitude)
        if altitude is not None and altitude <= 0:
            continue
        code = str(entry.get("t", "")).upper().strip()
        code = code if re.fullmatch(r"[A-Z0-9]{1,8}", code) else None
        callsign = str(entry.get("flight", "")).strip().upper()[:16] or None
        rate = number(entry.get("baro_rate", entry.get("geom_rate")))
        category = str(entry.get("category", "")).upper().strip()
        result.append(LiveAircraft(
            hex_id, callsign, code, lat, lon, int(altitude) if altitude is not None else None,
            number(entry.get("track")), number(entry.get("gs")), int(rate) if rate is not None else None,
            now - seen - age, source, haversine_distance(*home, lat, lon, unit=unit),
            initial_bearing(*home, lat, lon), category if re.fullmatch(r"[A-D][0-7]", category) else None))
    return tuple(result)


class Receiver:
    def __init__(self, url):
        self.url = url.rstrip("/")
        self.working = None

    def fetch(self):
        if urlsplit(self.url).path.endswith(".json"):
            candidates = [self.url]
        else:
            candidates = list(dict.fromkeys([self.working] + [self.url + path for path in PATHS]))
        for url in candidates:
            if url is None:
                continue
            try:
                with requests.get(url, timeout=(2, 3), allow_redirects=False, stream=True) as response:
                    if response.status_code != 200:
                        continue
                    chunks, length = [], 0
                    for chunk in response.iter_content(65536):
                        length += len(chunk)
                        if length > 4 * 1024 * 1024:
                            raise ValueError("Receiver response exceeds 4 MiB")
                        chunks.append(chunk)
                    import json
                    data = json.loads(b"".join(chunks))
                    if not isinstance(data, dict) or not isinstance(data.get("aircraft"), list):
                        continue
                    self.working = url
                    return data
            except (requests.RequestException, ValueError):
                continue
        raise ValueError("No reachable aircraft.json endpoint")


class Poller(threading.Thread):
    def __init__(self, config, state):
        super().__init__(name="receiver-poller", daemon=True)
        self.config, self.state = config, state
        self.results = queue.Queue(maxsize=1)
        self.stopping = threading.Event()
        self.receivers = [Receiver(url) for url in config["RECEIVER_URLS"]]

    def run(self):
        failures = 0
        with concurrent.futures.ThreadPoolExecutor(max_workers=len(self.receivers)) as pool:
            while not self.stopping.is_set():
                began = time.monotonic()
                settings = self.config
                fresh, errors, healthy = {}, [], 0
                try:
                    settings = display_settings(self.config, self.state)
                    home = settings["LATITUDE"], settings["LONGITUDE"]
                    jobs = {pool.submit(receiver.fetch): index for index, receiver in enumerate(self.receivers)}
                    for future in concurrent.futures.as_completed(jobs):
                        index = jobs[future]
                        try:
                            aircraft = parse_aircraft(future.result(), str(index + 1), home, settings["DISTANCE_UNIT"])
                            healthy += 1
                            for plane in aircraft:
                                if plane.hex not in fresh or fresh[plane.hex].seen_at < plane.seen_at:
                                    fresh[plane.hex] = plane
                        except Exception as error:
                            message = str(error) if isinstance(error, ValueError) else type(error).__name__
                            errors.append(f"Receiver {index + 1}: {message}")
                except (OSError, ValueError):
                    errors.append("Invalid saved display settings")
                failures = 0 if healthy else failures + 1
                result = {"aircraft": tuple(sorted(fresh.values(), key=lambda a: a.distance)),
                          "failures": failures, "healthy_receivers": healthy, "errors": errors,
                          "duration_ms": round((time.monotonic() - began) * 1000), "received": time.time()}
                if errors:
                    LOG.warning("; ".join(errors))
                try:
                    self.results.get_nowait()
                except queue.Empty:
                    pass
                self.results.put_nowait(result)
                self.stopping.wait(max(0.1, (settings.get("POLL_SECONDS") or 5) - (time.monotonic() - began)))
