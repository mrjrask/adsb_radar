import json
import os
import subprocess
import sys

import pytest
from PIL import Image


@pytest.mark.parametrize("mode", ["flight", "radar"])
@pytest.mark.parametrize("profile,expected", [("4k", [3840, 2160]), ("1080p", [1920, 1080]), ("848x480", [848, 480])])
def test_real_pygame_render_loop_and_shutdown(tmp_path, mode, profile, expected):
    env = {**os.environ, "SDL_VIDEODRIVER": "dummy"}
    subprocess.run([sys.executable, "-m", "adsb_radar.display", "--windowed", "--demo", mode,
                    "--resolution", profile,
                    "--frames", "2", "--state-dir", str(tmp_path)], env=env, check=True, timeout=30)
    status = json.loads((tmp_path / "status.json").read_text())
    assert status["state"] == "stopped" and status["driver"] == "dummy"
    assert status["render_size"] == expected
    with Image.open(tmp_path / "preview.png") as image:
        assert image.size == ((848, 480) if profile == "848x480" else (960, 540))
