"""scripts/generate_missing_imagery.py: from a pasted missing imagery log to files."""

from __future__ import annotations

import base64
import importlib.util
import io
import json
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import ClassVar

import pytest
from PIL import Image, ImageDraw

_SPEC = importlib.util.spec_from_file_location(
    "generate_missing_imagery", Path(__file__).resolve().parents[1] / "scripts" / "generate_missing_imagery.py"
)
gen = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = gen  # dataclasses look their module up
_SPEC.loader.exec_module(gen)

LOG = "\n".join(
    "\t".join(row)
    for row in [
        gen.COLUMNS,
        (
            "2026-10-30 22:30:17 UTC",
            "airline_logo",
            "JZA",
            "Air Canada Jazz",
            "",
            "",
            "JZA909",
            "air/JZA.png",
            "badge",
        ),
        (
            "2026-10-30 22:30:47 UTC",
            "aircraft_image",
            "JZA",
            "Air Canada Jazz",
            "E75S",
            "E175",
            "JZA909",
            "aircraft/JZA/E75S.png",
            "drawn",
        ),
        (
            "2026-10-30 22:31:37 UTC",
            "airline_logo",
            "TWY",
            "",
            "",
            "",
            "TWY70",
            "air/TWY.png",
            "badge",
        ),
        (
            "2026-10-30 22:31:37 UTC",
            "aircraft_image",
            "",
            "",
            "GLF4",
            "Gulfstream IV",
            "TWY70",
            "aircraft/_generic/GLF4.png",
            "aircraft/_generic/GLF6.png",
        ),
        (
            "2026-10-30 22:31:38 UTC",
            "airline_logo",
            "POE",
            "Porter Airlines",
            "",
            "",
            "POE641",
            "images/air/POE.png",
            "badge",
        ),  # desk_display writes paths from the project root
        (
            "2026-10-30 22:31:39 UTC",
            "airline_logo",
            "POE",
            "Porter Airlines",
            "",
            "",
            "POE642",
            "images/air/POE.png",
            "badge",
        ),
    ]
)


class _DrawThings(BaseHTTPRequestHandler):
    requests: ClassVar[list[dict]] = []

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        type(self).requests.append({"path": self.path, **body})
        image = Image.new("RGB", (body["width"], body["height"]), (250, 250, 250))
        w, h = image.size
        ImageDraw.Draw(image).rectangle(
            (w // 4, h // 3, 3 * w // 4, 2 * h // 3), fill=(200, 20, 40)
        )
        buffer = io.BytesIO()
        image.save(buffer, "PNG")
        reply = json.dumps({"images": [base64.b64encode(buffer.getvalue()).decode()]}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(reply)))
        self.end_headers()
        self.wfile.write(reply)

    def log_message(self, *args):
        pass


@pytest.fixture
def draw_things():
    _DrawThings.requests = []
    server = HTTPServer(("127.0.0.1", 0), _DrawThings)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_port}"
    server.shutdown()


def test_one_job_per_missing_file_and_unnamed_airlines_need_a_name():
    jobs, skipped = gen.jobs_for(gen.parse_log(LOG), kind="all", names={})
    assert [j.target for j in jobs] == [
        "air/JZA.png",
        "aircraft/JZA/E75S.png",
        "aircraft/_generic/GLF4.png",
        "air/POE.png",
    ]
    assert skipped and "TWY" in skipped[0]
    named, _ = gen.jobs_for(
        gen.parse_log(LOG), kind="airline_logo", names={"TWY": "Tradewind Aviation"}
    )
    assert [j.target for j in named] == ["air/JZA.png", "air/TWY.png", "air/POE.png"]


def test_prompts_name_the_airline_and_aircraft():
    jobs, _ = gen.jobs_for(gen.parse_log(LOG), kind="all", names={})
    logo, livery, generic = (gen.prompt_for(j) for j in jobs[:3])
    assert "Air Canada Jazz" in logo[0] and logo[2] == gen.LOGO_SIZE
    assert (
        "Embraer E175" in livery[0]
        and "Air Canada Jazz livery" in livery[0]
        and "nose pointing to the right" in livery[0]
    )
    assert "Gulfstream IV" in generic[0] and "unbranded" in generic[0]


def test_files_are_saved_where_the_log_says_with_the_background_removed(draw_things, tmp_path):
    assert (
        gen.main(
            [
                *("--host", draw_things, "--output", str(tmp_path), "--steps", "8"),
                *("--name", "TWY=Tradewind Aviation", _log(tmp_path)),
            ]
        )
        == 0
    )
    assert {r["path"] for r in _DrawThings.requests} == {"/sdapi/v1/txt2img"}
    assert (
        _DrawThings.requests[0]["steps"] == 8
        and "Air Canada Jazz" in _DrawThings.requests[0]["prompt"]
    )
    logo = tmp_path / "air" / "JZA.png"
    with Image.open(logo) as image:
        assert max(image.size) <= gen.LOGO_MAX_EDGE
        rgba = image.convert("RGBA")
        assert rgba.getpixel((0, 0))[3] == 0  # the white background is gone
        assert rgba.getpixel((rgba.width // 2, rgba.height // 2))[3] == 255
    assert logo.stat().st_size <= gen.LOGO_MAX_BYTES
    with Image.open(tmp_path / "aircraft" / "JZA" / "E75S.png") as image:
        assert image.width > image.height
    assert (tmp_path / "air" / "TWY.png").is_file() and (tmp_path / "air" / "POE.png").is_file()
    assert (
        tmp_path / "aircraft" / "_generic" / "GLF4.png"
    ).stat().st_size <= gen.AIRCRAFT_MAX_BYTES
    # Run again: what exists is kept.
    count = len(_DrawThings.requests)
    gen.main(["--host", draw_things, "--output", str(tmp_path), _log(tmp_path)])
    assert len(_DrawThings.requests) == count


def test_variants_are_numbered(draw_things, tmp_path):
    gen.main(
        [
            "--host",
            draw_things,
            "--output",
            str(tmp_path),
            "--kind",
            "logo",
            "--variants",
            "2",
            _log(tmp_path),
        ]
    )
    assert sorted(p.name for p in (tmp_path / "air").iterdir()) == [
        "JZA-1.png",
        "JZA-2.png",
        "POE-1.png",
        "POE-2.png",
    ]


def test_unreachable_draw_things_says_how_to_turn_the_api_on(tmp_path, capsys):
    assert (
        gen.main(
            [
                "--host",
                "http://127.0.0.1:9",
                "--output",
                str(tmp_path),
                "--timeout",
                "2",
                _log(tmp_path),
            ]
        )
        == 2
    )
    assert "API Server" in capsys.readouterr().err


def test_dry_run_draws_nothing(tmp_path, capsys):
    assert gen.main(["--dry-run", "--output", str(tmp_path), _log(tmp_path)]) == 0
    assert "Embraer E175" in capsys.readouterr().out and not any(tmp_path.glob("**/*.png"))


def _log(tmp_path) -> str:
    path = tmp_path / "missing_imagery.log"
    path.write_text(LOG + "\n", encoding="utf-8")
    return str(path)
