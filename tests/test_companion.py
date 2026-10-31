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


def test_hidden_patterns_alternate_without_changing_visible_content():
    first = render(snapshot(), 101)
    second = render(snapshot(), 102)
    for index, visible, hidden, margin in (
        (0, (0, 0, 96, 128), (104, 0, 128, 128), (96, 0, 104, 128)),
        (2, (32, 0, 128, 128), (0, 0, 24, 128), (24, 0, 32, 128)),
    ):
        assert first[index].crop(visible).tobytes() == second[index].crop(visible).tobytes()
        assert first[index].crop(visible).getbbox()
        assert first[index].crop(margin).getbbox() is None
        before = first[index].crop(hidden).convert("L").tobytes()
        after = second[index].crop(hidden).convert("L").tobytes()
        assert all(bool(a) != bool(b) for a, b in zip(before, after, strict=True))
        assert sum(bool(a) for a in before) == len(before) // 2


def test_overlap_can_be_disabled_independently():
    defaults = render(snapshot(), 101)
    custom = render(snapshot(), 101, {"left_hidden_columns": 0})
    assert defaults[0].tobytes() != custom[0].tobytes()
    assert defaults[1].tobytes() == custom[1].tobytes()
    assert defaults[2].tobytes() == custom[2].tobytes()


@pytest.mark.parametrize("value", [-1, 49, True, 32.5, "32"])
def test_invalid_overlap_is_rejected(value):
    with pytest.raises(ValueError, match="left_hidden_columns"):
        render(snapshot(), 101, {"left_hidden_columns": value})
