import re

import pytest
from PIL import Image

from adsb_radar import aircraft_art, airline_directory, flight_layout, missing_imagery
from adsb_radar.web import create_app


@pytest.fixture
def log(tmp_path):
    path = tmp_path / "state" / missing_imagery.FILENAME
    missing_imagery.configure(path, tmp_path / "images")
    yield path
    missing_imagery.configure(None)


def rows(path):
    lines = path.read_text(encoding="utf-8").splitlines()
    assert lines[0].split("\t") == list(missing_imagery.COLUMNS)
    return [dict(zip(missing_imagery.COLUMNS, line.split("\t"), strict=True)) for line in lines[1:]]


def flight(plane):
    return flight_layout.OverheadFlight(plane, None, airline_directory.airline_for("DAL"))


def test_nothing_is_logged_until_configured(tmp_path):
    assert missing_imagery.log_path() is None
    assert not missing_imagery.record_logo("UAL", tmp_path)


def test_missing_logo_is_logged_once_relative_to_the_images_folder(log, tmp_path):
    air = tmp_path / "images" / "air"
    assert missing_imagery.record_logo("ual", air, callsign="ual123")
    assert not missing_imagery.record_logo("UAL", air, callsign="UAL456")
    for code in ("N12345", "UA", "", None):
        assert not missing_imagery.record_logo(code, air)
    (row,) = rows(log)
    assert (row["kind"], row["airline"], row["airline_name"]) == ("airline_logo", "UAL", "United Airlines")
    assert (row["callsign"], row["missing_file"], row["showing_instead"]) == ("UAL123", "air/UAL.png", "badge")


def test_missing_aircraft_is_logged_per_airline_and_type(log, tmp_path):
    art = tmp_path / "images" / "aircraft"
    assert missing_imagery.record_aircraft("b39m", "UAL", art, type_name="737 MAX 9", callsign="UAL1")
    assert missing_imagery.record_aircraft("C25B", None, art, showing_instead="nothing")
    assert not missing_imagery.record_aircraft("B39M", "ual", art)
    assert not missing_imagery.record_aircraft(None, "UAL", art)
    assert [(r["missing_file"], r["type_name"]) for r in rows(log)] == [
        ("aircraft/UAL/B39M.png", "737 MAX 9"), ("aircraft/_generic/C25B.png", "")]


def test_restart_keeps_entries_and_drops_ones_since_added(log, tmp_path):
    air = tmp_path / "images" / "air"
    missing_imagery.record_logo("UAL", air)
    missing_imagery.record_logo("DAL", air)
    missing_imagery.configure(log, tmp_path / "images")  # a restart
    assert not missing_imagery.record_logo("UAL", air)
    air.mkdir(parents=True)
    Image.new("RGBA", (4, 4)).save(air / "DAL.png")
    missing_imagery.configure(log, tmp_path / "images")
    missing_imagery.record_logo("AAL", air)
    assert [r["airline"] for r in rows(log)] == ["UAL", "AAL"]


def test_flight_board_logs_its_badge_and_drawn_aircraft(log, tmp_path, monkeypatch, plane):
    monkeypatch.setattr(flight_layout, "ASSET_DIR", tmp_path / "images")
    monkeypatch.setattr(aircraft_art, "ASSET_DIR", str(tmp_path / "images" / "aircraft"))
    image = Image.new("RGB", (400, 400))
    flight_layout._draw_logo_tile(image, 0, 0, 200, flight(plane).airline, plane.callsign)
    flight_layout._draw_aircraft(image, (0, 200, 400, 400), flight(plane))
    found = rows(log)
    assert [(r["kind"], r["airline"], r["type"], r["missing_file"]) for r in found] == [
        ("airline_logo", "DAL", "", "air/DAL.png"), ("aircraft_image", "DAL", "B738", "aircraft/DAL/B738.png")]
    assert (found[1]["type_name"], found[1]["callsign"], found[1]["showing_instead"]) == ("737-800", "DAL123", "drawn")


def test_flight_board_names_the_stand_in_illustration(log, tmp_path, monkeypatch, plane):
    art = tmp_path / "images" / "aircraft"
    (art / "_generic").mkdir(parents=True)
    Image.new("RGBA", (40, 12), (200, 30, 30, 255)).save(art / "_generic" / "B738.png")
    monkeypatch.setattr(aircraft_art, "ASSET_DIR", str(art))
    flight_layout._draw_aircraft(Image.new("RGB", (400, 200)), (0, 0, 400, 200), flight(plane))
    (row,) = rows(log)
    assert (row["missing_file"], row["showing_instead"]) == ("aircraft/DAL/B738.png", "aircraft/_generic/B738.png")


def test_unknown_airline_callsigns_are_logged(log, tmp_path, monkeypatch, plane):
    monkeypatch.setattr(flight_layout, "ASSET_DIR", tmp_path / "images")
    flight_layout._draw_logo_tile(Image.new("RGB", (100, 100)), 0, 0, 100, None, "ZZQ12")
    (row,) = rows(log)
    assert (row["airline"], row["airline_name"], row["missing_file"]) == ("ZZQ", "", "air/ZZQ.png")


def test_admin_serves_the_log(config, tmp_path):
    client = create_app(config=config, state_path=tmp_path).test_client()
    assert client.get("/missing-imagery.log").status_code == 401
    page = client.get("/login")
    token = re.search(rb'name=csrf value="([a-f0-9]+)"', page.data)[1].decode()
    client.post("/login", data={"username": "admin", "password": "test-password-123", "csrf": token})
    assert b'href="/missing-imagery.log"' in client.get("/").data
    assert b"Nothing missing yet" in client.get("/missing-imagery.log").data
    (tmp_path / missing_imagery.FILENAME).write_text("first_seen\tkind\n", encoding="utf-8")
    reply = client.get("/missing-imagery.log")
    assert reply.status_code == 200 and reply.data.startswith(b"first_seen") and reply.mimetype == "text/plain"
