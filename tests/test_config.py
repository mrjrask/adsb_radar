import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from werkzeug.security import check_password_hash

from adsb_radar.config import check_settings, display_settings, load_config, read_json, write_json


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
