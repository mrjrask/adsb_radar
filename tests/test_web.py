import re
import time

import pytest

from adsb_radar.config import read_json, write_json
from adsb_radar.forms import RADAR_COLOR_DEFAULTS
from adsb_radar.web import create_app


@pytest.fixture
def client(config, tmp_path):
    app = create_app(config=config, state_path=tmp_path)
    app.config["TESTING"] = True
    return app.test_client()


def login(client):
    page = client.get("/login")
    token = re.search(rb'name=csrf value="([a-f0-9]+)"', page.data)[1].decode()
    assert client.post("/login", data={"username": "admin", "password": "test-password-123",
                                       "csrf": token}).status_code == 303
    with client.session_transaction() as session:
        return session["csrf"]


def test_authentication_and_csrf(client, tmp_path):
    assert client.get("/").status_code == 303
    assert client.get("/status.json").status_code == 401
    assert client.get("/healthz").status_code == 200
    assert client.post("/login", data={"username": "admin"}).status_code == 403
    token = login(client)
    page = client.get("/")
    assert page.status_code == 200 and b"RASPBERRY PI" in page.data
    assert b"Radar colors" in page.data and b"id=dome" in page.data
    assert b"reboot" not in page.data and b"light sensor" not in page.data
    assert client.post("/settings", data={"RADIUS": 7}).status_code == 403
    assert client.post("/settings", data={"csrf": token, "RADIUS": 7}).status_code == 303
    assert read_json(tmp_path / "settings.json")["RADIUS"] == 7
    assert client.post("/settings", data={"csrf": token, "RADIUS": "nan"}).status_code == 400
    assert read_json(tmp_path / "settings.json")["RADIUS"] == 7


def test_login_is_rate_limited(client):
    client.get("/login")
    with client.session_transaction() as session:
        token = session["csrf"]
    for _ in range(5):
        assert client.post("/login", data={"csrf": token, "username": "wrong"}).status_code == 200
    assert client.post("/login", data={"csrf": token}).status_code == 429


def test_palettes_only_change_colors_and_survive_reset(client, tmp_path):
    token = login(client)
    client.post("/settings", data={"csrf": token, "RADIUS": 8, "BRIGHTNESS": "0.1"})
    assert client.post("/presets", data={"csrf": token, "preset_apply": "Night"}).status_code == 303
    saved = read_json(tmp_path / "settings.json")
    assert saved["RADIUS"] == 8 and saved["BRIGHTNESS"] == 0.1
    assert saved["RADAR_BACKGROUND"] == "#000000"
    colors = {**RADAR_COLOR_DEFAULTS, "RADAR_BACKGROUND": "123456"}
    assert client.post("/presets", data={"csrf": token, "preset_action": "save", "preset_name": "Custom",
                                         **colors}).status_code == 303
    assert read_json(tmp_path / "presets.json")["Custom"]["RADAR_BACKGROUND"] == "#123456"
    assert client.post("/reset", data={"csrf": token}).status_code == 303
    assert read_json(tmp_path / "settings.json") == {}
    assert "Custom" in read_json(tmp_path / "presets.json")
    assert client.post("/presets", data={"csrf": token, "preset_action": "rename", "preset_source": "Night",
                                         "preset_name": "Overwrite"}).status_code == 400


def test_palette_rename_duplicate_and_limits(client, tmp_path):
    token = login(client)
    for action, source, name in (("duplicate", "Night", "Red"), ("rename", "Red", "Dim")):
        assert client.post("/presets", data={"csrf": token, "preset_action": action,
                                             "preset_source": source, "preset_name": name}).status_code == 303
    assert list(read_json(tmp_path / "presets.json")) == ["Dim"]
    for index in range(19):
        client.post("/presets", data={"csrf": token, "preset_action": "duplicate",
                                      "preset_source": "Night", "preset_name": str(index)})
    assert client.post("/presets", data={"csrf": token, "preset_action": "duplicate", "preset_source": "Night",
                                         "preset_name": "Too many"}).status_code == 400


def test_renderer_death_does_not_take_down_admin(client, tmp_path):
    login(client)
    write_json(tmp_path / "status.json", {"heartbeat": time.time() - 60, "state": "online"})
    assert client.get("/").status_code == 200
    assert client.get("/status.json").json["renderer_alive"] is False
    assert client.get("/preview.png").status_code == 404


def test_logout_and_output_escaping(client):
    token = login(client)
    assert b"<script>alert" not in client.get("/?message=<script>alert(1)</script>").data
    assert client.post("/logout", data={"csrf": token}).status_code == 303
    assert client.get("/status.json").status_code == 401
