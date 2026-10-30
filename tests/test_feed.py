import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from adsb_radar.feed import Poller, Receiver, parse_aircraft


def payload(now=1000, **entry):
    return {"now": now, "aircraft": [{"hex": "a12345", "flight": "DAL123 ", "t": "B738", "lat": 41.89,
                                    "lon": -87.62, "seen_pos": 1, "alt_baro": 5000, "gs": 200, **entry}]}


def test_parse_valid_plane_and_staleness():
    result = parse_aircraft(payload(), "1", (41.88, -87.63), now=1001)
    assert len(result) == 1 and result[0].callsign == "DAL123"
    assert result[0].seen_at == 999
    assert 0 < result[0].distance < 1
    assert 0 < result[0].bearing < 90
    with pytest.raises(ValueError, match="stale"):
        parse_aircraft(payload(), "1", (0, 0), now=1040)


@pytest.mark.parametrize("entry", [{"lat": None}, {"lat": 100}, {"lon": float("nan")},
                                   {"seen_pos": 31}, {"seen_pos": -1}, {"alt_baro": "ground"},
                                   {"alt_baro": 0}, {"hex": "not-a-plane"}])
def test_drop_invalid_ground_and_old_positions(entry):
    assert parse_aircraft(payload(**entry), "1", (41.88, -87.63), now=1000) == ()


def test_receiver_type_cannot_traverse_asset_folders():
    plane = parse_aircraft(payload(t="../../secrets"), "1", (41.88, -87.63), now=1000)[0]
    assert plane.aircraft_type is None


def test_real_http_path_discovery_and_polling(config, tmp_path):
    paths = []

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            paths.append(self.path)
            self.send_response(200 if self.path == "/tar1090/data/aircraft.json" else 404)
            self.end_headers()
            self.wfile.write(json.dumps(payload(now=time.time())).encode())

        def log_message(self, *_args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    url = f"http://127.0.0.1:{server.server_port}"
    try:
        receiver = Receiver(url)
        receiver.fetch()
        assert paths == ["/data/aircraft.json", "/tar1090/data/aircraft.json"]
        receiver.fetch()
        assert paths[-1] == "/tar1090/data/aircraft.json"
        poller = Poller({**config, "RECEIVER_URLS": [url]}, tmp_path)
        poller.start()
        result = poller.results.get(timeout=5)
        poller.stopping.set()
        poller.join(timeout=3)
        assert result["healthy_receivers"] == 1 and len(result["aircraft"]) == 1
        assert result["failures"] == 0
    finally:
        server.shutdown()
        server.server_close()


def test_multiple_receivers_deduplicate_and_tolerate_partial_outage(config, tmp_path, monkeypatch):
    def fetch(receiver):
        if receiver.url == "http://bad":
            raise ValueError("Offline")
        return payload(now=time.time(), seen_pos=1 if receiver.url == "http://new" else 10)
    monkeypatch.setattr(Receiver, "fetch", fetch)
    poller = Poller({**config, "RECEIVER_URLS": ["http://old", "http://new", "http://bad"]}, tmp_path)
    poller.start()
    result = poller.results.get(timeout=3)
    poller.stopping.set()
    poller.join(timeout=2)
    assert len(result["aircraft"]) == 1
    assert result["aircraft"][0].device == "2"
    assert result["healthy_receivers"] == 2 and result["failures"] == 0


@pytest.mark.parametrize("prefix", ["", "/tar1090", "/combo"])
def test_combined_tar1090_feed_uses_selected_instance_and_contains_both_receivers(config, tmp_path, prefix):
    paths = []
    endpoint = prefix + "/data/aircraft.json"

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            paths.append(self.path)
            if self.path != endpoint:
                self.send_response(404)
                self.end_headers()
                return
            merged = payload(now=time.time())
            merged["aircraft"].append({**merged["aircraft"][0], "hex": "b23456", "flight": "UAL456"})
            self.send_response(200)
            self.end_headers()
            self.wfile.write(json.dumps(merged).encode())

        def log_message(self, *_args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    source = f"http://127.0.0.1:{server.server_port}{prefix}"
    poller = Poller({**config, "RECEIVER_URLS": [source]}, tmp_path)
    try:
        poller.start()
        result = poller.results.get(timeout=5)
        assert {a.callsign for a in result["aircraft"]} == {"DAL123", "UAL456"}
        assert result["healthy_receivers"] == 1
        assert paths == [endpoint]
    finally:
        poller.stopping.set()
        poller.join(timeout=2)
        server.shutdown()
        server.server_close()
