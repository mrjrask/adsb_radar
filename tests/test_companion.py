"""Companion behavior without requiring GPIO, SPI or I2C on CI."""

from dataclasses import asdict
from unittest.mock import MagicMock

import pytest

from adsb_radar.models import LiveAircraft
from pimoroni_companion.companion import Hardware, live_snapshot, render


def snapshot():
    plane = LiveAircraft("a12345", "DAL123", "B738", 41.9, -87.6, 6500, 65, 230, -500,
                         100, "1", 1.5, 45)
    return {"heartbeat": 100, "online": True, "selected": plane.hex,
            "unit": "nm", "range": 12, "aircraft": [asdict(plane)]}


def test_three_native_panels_and_selected_instruments():
    images = render(snapshot(), 101)
    assert [i.size for i in images] == [(128, 128), (240, 240), (128, 128)]
    assert [i.mode for i in images] == ["1", "RGB", "1"]
    idle = snapshot()
    idle["selected"] = None
    assert images[0].tobytes() != render(idle, 101)[0].tobytes()
    assert images[2].tobytes() != render(idle, 101)[2].tobytes()


@pytest.mark.parametrize("change, now", [({}, 106), ({"online": False}, 101), ({}, 99)])
def test_stale_offline_and_future_heartbeat_hide_aircraft(change, now):
    data = {**snapshot(), **change}
    assert live_snapshot(data, now)["aircraft"] == []
    assert render(data, now)[1].getbbox()


def test_individual_positions_expire_and_missing_telemetry_renders():
    data = snapshot()
    data["aircraft"][0]["seen_at"] = 60
    assert live_snapshot(data, 101)["aircraft"] == []
    data = snapshot()
    for key in ("altitude_ft", "ground_speed_kt", "vertical_rate_fpm", "aircraft_type", "callsign"):
        data["aircraft"][0][key] = None
    assert all(image.getbbox() for image in render(data, 101))
    assert all(image.getbbox() for image in render({}, 101))


def test_shutdown_attempts_every_panel_even_if_one_fails():
    hardware = Hardware.__new__(Hardware)
    hardware.oleds = [MagicMock(), MagicMock()]
    hardware.oleds[0].cleanup.side_effect = OSError("disconnected")
    hardware.lcd = MagicMock()
    hardware.close()
    hardware.oleds[1].cleanup.assert_called_once()
    hardware.lcd.set_backlight.assert_called_once_with(0)
