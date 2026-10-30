import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from werkzeug.security import check_password_hash

from adsb_radar.config import check_settings, display_settings, load_config, read_json, tar1090_address, write_json


def test_config_bootstrap_and_reinstall_preserve_credentials(tmp_path):
    seed = tmp_path / "seed.json"
    seed.write_text(json.dumps({"RECEIVER_URLS": ["http://receiver"], "LATITUDE": 41.88, "LONGITUDE": -87.63,
                                "ADMIN_PASSWORD": "test-password-123"}))
    destination = tmp_path / "private.json"
    command = [sys.executable, str(Path(__file__).parents[1] / "scripts/configure.py"),
               str(destination), "--seed", str(seed)]
    result = subprocess.run(command, check=True, capture_output=True, text=True)
    assert "test-password" not in result.stdout
    value = load_config(destination)
    assert check_password_hash(value["ADMIN_PASSWORD_HASH"], "test-password-123")
    assert "ADMIN_PASSWORD" not in value
    original = destination.read_bytes()
    subprocess.run(command, check=True, capture_output=True)
    assert destination.read_bytes() == original
    assert os.stat(destination).st_mode & 0o777 == 0o640


@pytest.mark.parametrize(("key", "value"), [
    ("RECEIVER_URLS", []), ("RECEIVER_URLS", ["http://user:password@receiver"]),
    ("RECEIVER_URLS", ["file:///tmp/aircraft.json"]), ("RECEIVER_URLS", ["http://receiver?q=x"]),
    ("LATITUDE", None), ("LONGITUDE", float("nan")), ("FPS", True), ("FPS", 0),
    ("ROTATION", 45), ("ADMIN_PORT", 80), ("SECRET_KEY", "short"),
    ("ADMIN_PASSWORD_HASH", "plaintext"), ("RESOLUTION", "720p"), ("DISTANCE_UNIT", "yards"),
])
def test_reject_invalid_config(config, tmp_path, key, value):
    path = tmp_path / "config.json"
    path.write_text(json.dumps({**config, key: value}))
    with pytest.raises(ValueError):
        load_config(path)


def test_saved_settings_override_config_and_reset(config, tmp_path):
    write_json(tmp_path / "settings.json", {"RADIUS": 6, "RADAR_BACKGROUND": "#123456"})
    assert display_settings(config, tmp_path)["RADIUS"] == 6
    write_json(tmp_path / "settings.json", {})
    assert display_settings(config, tmp_path)["RADIUS"] == 3
    assert not list(tmp_path.glob(".*.tmp"))


@pytest.mark.parametrize("value", [True, -1, 0, float("nan"), float("inf"), "auto"])
def test_hdmi_brightness_is_numeric(value):
    with pytest.raises(ValueError):
        check_settings({"BRIGHTNESS": value})


def test_bad_settings_are_reported_instead_of_silently_discarded(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text("broken")
    with pytest.raises(ValueError):
        read_json(path)


@pytest.mark.parametrize("address,expected", [
    ("cm5", "http://cm5"),
    ("192.0.2.10:8080", "http://192.0.2.10:8080"),
    ("http://192.0.2.10:8080/", "http://192.0.2.10:8080"),
    ("https://cm5/combo/index.html?lat=41&lon=-87#map", "https://cm5/combo"),
    ("http://cm5/tar1090/", "http://cm5/tar1090"),
    ("http://cm5/data/aircraft.json", "http://cm5/data/aircraft.json"),
])
def test_tar1090_accepts_host_port_and_map_addresses(address, expected):
    assert tar1090_address(address) == expected


@pytest.mark.parametrize("address", ["", "file:///tmp/planes", "http://user:password@cm5", "http://cm5:bad", "cm5:99999", "cm 5"])
def test_tar1090_rejects_invalid_addresses(address):
    with pytest.raises(ValueError):
        tar1090_address(address)


def test_switch_existing_config_to_combined_feed_preserves_credentials(config, tmp_path):
    path = tmp_path / "config.json"
    write_json(path, {**config, "RECEIVER_URLS": ["http://receiver1", "http://receiver2"]})
    write_json(tmp_path / "settings.json", {"RADIUS": 7})
    original = path.stat()
    result = subprocess.run([sys.executable, str(Path(__file__).parents[1] / "scripts/configure.py"),
                             str(path), "--tar1090", "192.0.2.10:8080"], capture_output=True, text=True, check=True)
    value = load_config(path)
    assert value["RECEIVER_URLS"] == ["http://192.0.2.10:8080"]
    assert value["ADMIN_PASSWORD_HASH"] == config["ADMIN_PASSWORD_HASH"]
    assert value["SECRET_KEY"] == config["SECRET_KEY"]
    assert value["LATITUDE"] == config["LATITUDE"]
    assert read_json(tmp_path / "settings.json") == {"RADIUS": 7}
    assert (path.stat().st_uid, path.stat().st_gid) == (original.st_uid, original.st_gid)
    assert "Generated admin password" not in result.stdout


def test_first_install_tar1090_prompt_accepts_host_port(monkeypatch):
    import importlib.util
    spec = importlib.util.spec_from_file_location("configure_script", Path(__file__).parents[1] / "scripts/configure.py")
    script = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(script)
    answers = iter(["", "192.0.2.10:8080"])
    monkeypatch.setattr("builtins.input", lambda _prompt: next(answers))
    assert script.prompt_feed() == ["http://192.0.2.10:8080"]
