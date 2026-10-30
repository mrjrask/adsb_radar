import os
import time
from dataclasses import replace

import pytest
from werkzeug.security import generate_password_hash

from adsb_radar.config import DEFAULTS
from adsb_radar.models import LiveAircraft

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")


@pytest.fixture
def config():
    return {**DEFAULTS, "RECEIVER_URLS": ["http://receiver"], "LATITUDE": 41.88, "LONGITUDE": -87.63,
            "ADMIN_PASSWORD_HASH": generate_password_hash("test-password-123"), "SECRET_KEY": "s" * 64,
            "ROUTE_LOOKUP": False, "TYPE_LOOKUP": False}


@pytest.fixture
def plane():
    return LiveAircraft("a12345", "DAL123", "B738", 41.89, -87.61, 6500, 90, 200, -500,
                        time.time(), "1", 1.5, 45)


@pytest.fixture
def distant(plane):
    return replace(plane, distance=7)
