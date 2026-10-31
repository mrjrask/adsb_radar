#!/usr/bin/env python3
"""Make the logos and aircraft illustrations a missing imagery log asks for, with Draw Things.

The ADS-B screens list every logo and illustration they lacked in
``logs/missing_imagery.log`` (desk_display) or ``/var/lib/adsb-radar/missing_imagery.log``
(adsb_radar; also on its admin page). Paste that log into this script and it asks
Draw Things' HTTP API for each file, cleans the picture up to the image policy in
``images/README.md`` and saves it under the path the log names:

    <output>/air/{AIRLINE}.png               logo, white background removed, longest edge 256 px
    <output>/aircraft/{AIRLINE}/{TYPE}.png   side view, nose right, background removed, under 400 KB

Review the results (AI art gets liveries and logos only roughly right, and the
odd aircraft faces left: ``--flip`` mirrors them), then copy the keepers into
``images/`` (desk_display) or ``images/`` of adsb_radar and commit them.

Setup: in Draw Things open Settings, turn on "API Server" (HTTP, port 7860) and
pick a model; the script uses whatever model and sampler are selected there.
Needs only Python 3 and Pillow, so it runs on the Mac beside Draw Things:

    python3 scripts/generate_missing_imagery.py                 # paste the log, then Ctrl-D
    python3 scripts/generate_missing_imagery.py missing_imagery.log --variants 3
    pbpaste | python3 scripts/generate_missing_imagery.py --kind logo
    python3 scripts/generate_missing_imagery.py log.tsv --dry-run   # just print the prompts

Rows whose airline has no name in the log (an operator the airline directory
does not know) get no logo, since there is nothing to draw; pass
``--name CODE=Name`` to supply one. Their aircraft are drawn in plain white.
"""

from __future__ import annotations

import argparse
import base64
import io
import json
import sys
import time
import urllib.error
import urllib.request
from collections import deque
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageOps

COLUMNS = (
    "first_seen",
    "kind",
    "airline",
    "airline_name",
    "type",
    "type_name",
    "callsign",
    "missing_file",
    "showing_instead",
)
DEFAULT_HOST = "http://127.0.0.1:7860"
DEFAULT_OUTPUT = Path.home() / "Desktop" / "missing_imagery"

LOGO_SIZE = (1024, 1024)
LOGO_MAX_EDGE = 256  # images/README.md: airline logos
LOGO_MAX_BYTES = 75_000
AIRCRAFT_SIZE = (1536, 512)  # about the 2400x816 master's 3:1
AIRCRAFT_MAX_EDGE = 2400
AIRCRAFT_MAX_BYTES = 400_000

LOGO_PROMPT = (
    "the official logo of {name}, the airline, flat vector emblem, simple bold shapes, "
    "brand colours, centered, isolated on a plain pure white background"
)
LOGO_NEGATIVE = (
    "photo, 3d render, mockup, airplane, tail fin, multiple logos, frame, border, "
    "watermark, signature, gradient background, shadow, blurry, distorted text"
)
AIRCRAFT_PROMPT = (
    "side view profile, {aircraft} {livery}, nose pointing to the right, whole aircraft "
    "in frame, landing gear retracted, flying, clean flat vector illustration, crisp lines, "
    "isolated on a plain pure white background"
)
AIRCRAFT_NEGATIVE = (
    "ground, runway, sky, clouds, shadow, people, text, watermark, cropped, cut off, "
    "front view, three-quarter view, top view, multiple aircraft, blurry, photo"
)


@dataclass(frozen=True)
class Job:
    kind: str  # "airline_logo" or "aircraft_image"
    airline: str
    airline_name: str
    type: str
    type_name: str
    target: str  # the log's missing_file, relative to images/

    @property
    def label(self) -> str:
        return self.target


# Maker by ICAO type designator prefix, so the prompt says "Airbus A319", not just "A319".
_MAKERS = (
    ("A3", "Airbus"),
    ("BCS", "Airbus"),
    ("B7", "Boeing"),
    ("B3", "Boeing"),
    ("MD", "McDonnell Douglas"),
    ("DC", "McDonnell Douglas"),
    ("CRJ", "Bombardier"),
    ("CL", "Bombardier"),
    ("GLF", "Gulfstream"),
    ("GL", "Bombardier"),
    ("LJ", "Learjet"),
    ("E1", "Embraer"),
    ("E2", "Embraer"),
    ("E3", "Embraer"),
    ("E4", "Embraer"),
    ("E5", "Embraer"),
    ("E6", "Embraer"),
    ("E7", "Embraer"),
    ("G2", "Gulfstream"),
    ("G6", "Gulfstream"),
    ("DH8", "De Havilland"),
    ("AT", "ATR"),
    ("C", "Cessna"),
    ("BE", "Beechcraft"),
    ("H25", "Hawker"),
    ("PC", "Pilatus"),
    ("SR", "Cirrus"),
    ("P28", "Piper"),
    ("PA", "Piper"),
    ("DA", "Diamond"),
    ("F2TH", "Dassault Falcon"),
    ("FA", "Dassault Falcon"),
    ("HDJT", "Honda"),
)


def _maker_and_model(designator: str, type_name: str) -> str:
    """'Airbus A319' from 'A319'; the log's name alone when it names the maker or none is known."""

    name = type_name or designator
    maker = next((m for prefix, m in _MAKERS if designator.startswith(prefix)), "")
    if not maker:
        return name if name.upper() != designator else f"aircraft type {designator}"
    if maker.split()[0].lower() in name.lower():
        return name
    return f"{maker} {name}"


def parse_log(text: str) -> list[dict[str, str]]:
    """The rows of a pasted log; the header is optional and blank or odd lines are skipped."""

    rows = []
    for line in text.splitlines():
        fields = line.rstrip("\r\n").split("\t")
        if len(fields) != len(COLUMNS) or fields[0] == COLUMNS[0]:
            continue
        rows.append(dict(zip(COLUMNS, (f.strip() for f in fields), strict=True)))
    return rows


def jobs_for(
    rows: list[dict[str, str]], *, kind: str, names: dict[str, str]
) -> tuple[list[Job], list[str]]:
    """One job per missing file, and a note for each row that cannot be drawn."""

    jobs: dict[str, Job] = {}
    skipped = []
    for row in rows:
        target = row["missing_file"].replace("\\", "/")
        target = (
            target.split("images/", 1)[1] if "images/" in target else target
        )  # desk_display paths
        if row["kind"] not in ("airline_logo", "aircraft_image") or target in jobs:
            continue
        if kind != "all" and not row["kind"].startswith(kind):
            continue
        name = names.get(row["airline"].upper()) or row["airline_name"]
        if row["kind"] == "airline_logo" and not name:
            skipped.append(
                f"{target}: no airline name for {row['airline']} "
                f"(pass --name {row['airline']}=Name)"
            )
            continue
        jobs[target] = Job(
            row["kind"], row["airline"].upper(), name, row["type"].upper(), row["type_name"], target
        )
    return list(jobs.values()), skipped


def prompt_for(job: Job) -> tuple[str, str, tuple[int, int]]:
    if job.kind == "airline_logo":
        return LOGO_PROMPT.format(name=job.airline_name), LOGO_NEGATIVE, LOGO_SIZE
    aircraft = _maker_and_model(job.type, job.type_name)
    if job.airline_name:
        livery = f"airliner in the current {job.airline_name} livery, airline colours and tail logo"
    else:
        livery = (
            "aircraft in a plain white unbranded paint scheme with grey trim, "
            "no logos or registration"
        )
    return (
        AIRCRAFT_PROMPT.format(aircraft=aircraft, livery=livery),
        AIRCRAFT_NEGATIVE,
        AIRCRAFT_SIZE,
    )


def generate(
    host: str,
    prompt: str,
    negative: str,
    size: tuple[int, int],
    *,
    steps: int | None,
    guidance: float | None,
    seed: int,
    timeout: float,
) -> Image.Image:
    """One image from Draw Things' txt2img endpoint (the model and sampler selected in the app)."""

    body = {
        "prompt": prompt,
        "negative_prompt": negative,
        "width": size[0],
        "height": size[1],
        "seed": seed,
        "batch_count": 1,
        "batch_size": 1,
    }
    if steps is not None:
        body["steps"] = steps
    if guidance is not None:
        body["guidance_scale"] = guidance
    request = urllib.request.Request(
        f"{host.rstrip('/')}/sdapi/v1/txt2img",
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        payload = json.loads(response.read())
    images = payload.get("images") or []
    if not images:
        raise RuntimeError(f"Draw Things returned no image: {str(payload)[:200]}")
    data = images[0].split(",", 1)[-1]  # tolerate a data: URL
    with Image.open(io.BytesIO(base64.b64decode(data))) as image:
        return image.convert("RGBA")


def remove_background(image: Image.Image, tolerance: int = 28) -> Image.Image:
    """Make the plain background transparent: what is near the corner colour, from the edge in."""

    rgb = image.convert("RGB")
    width, height = rgb.size
    pixels = rgb.load()
    corners = [
        pixels[0, 0],
        pixels[width - 1, 0],
        pixels[0, height - 1],
        pixels[width - 1, height - 1],
    ]
    background = tuple(
        sorted(c[i] for c in corners)[1] for i in range(3)
    )  # robust to one odd corner

    def near(color) -> bool:
        return max(abs(color[i] - background[i]) for i in range(3)) <= tolerance

    alpha = Image.new("L", rgb.size, 255)
    mask = alpha.load()
    queue = deque()
    for x in range(width):
        queue.extend(((x, 0), (x, height - 1)))
    for y in range(height):
        queue.extend(((0, y), (width - 1, y)))
    while queue:
        x, y = queue.popleft()
        if mask[x, y] == 0 or not near(pixels[x, y]):
            continue
        mask[x, y] = 0
        if x > 0:
            queue.append((x - 1, y))
        if x < width - 1:
            queue.append((x + 1, y))
        if y > 0:
            queue.append((x, y - 1))
        if y < height - 1:
            queue.append((x, y + 1))
    result = image.convert("RGBA")
    result.putalpha(alpha)
    return result


def _trim(image: Image.Image, margin: float) -> Image.Image:
    bbox = image.getchannel("A").point(lambda v: 255 if v > 16 else 0).getbbox()
    if bbox is None:
        raise RuntimeError("nothing left after removing the background")
    image = image.crop(bbox)
    pad = round(max(image.size) * margin)
    framed = Image.new("RGBA", (image.width + 2 * pad, image.height + 2 * pad), (0, 0, 0, 0))
    framed.paste(image, (pad, pad))
    return framed


def _encode(image: Image.Image, max_bytes: int) -> bytes:
    """PNG under *max_bytes*: full colour if it fits, else a 256-colour palette, else smaller."""

    while True:
        for candidate in (image, image.quantize(256, method=Image.Quantize.FASTOCTREE)):
            buffer = io.BytesIO()
            candidate.save(buffer, "PNG", optimize=True)
            if buffer.tell() <= max_bytes:
                return buffer.getvalue()
        image = image.resize(
            (max(1, round(image.width * 0.85)), max(1, round(image.height * 0.85))),
            Image.Resampling.LANCZOS,
        )


def finish(job: Job, image: Image.Image, *, flip: bool) -> bytes:
    image = remove_background(image)
    if job.kind == "airline_logo":
        image = _trim(image, 0.02)
        image.thumbnail((LOGO_MAX_EDGE, LOGO_MAX_EDGE), Image.Resampling.LANCZOS)
        return _encode(image, LOGO_MAX_BYTES)
    image = _trim(image, 0.02)  # the renderer trims the margin again and scales to the slot
    if flip:
        image = ImageOps.mirror(image)
    image.thumbnail((AIRCRAFT_MAX_EDGE, AIRCRAFT_MAX_EDGE), Image.Resampling.LANCZOS)
    return _encode(image, AIRCRAFT_MAX_BYTES)


def _output_paths(output: Path, job: Job, variants: int) -> list[Path]:
    path = output / job.target
    if variants == 1:
        return [path]
    return [path.with_name(f"{path.stem}-{n}{path.suffix}") for n in range(1, variants + 1)]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument(
        "log", nargs="?", type=Path, help="the log file (default: read the pasted log from stdin)"
    )
    parser.add_argument(
        "--host", default=DEFAULT_HOST, help=f"Draw Things API server (default {DEFAULT_HOST})"
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
        help=f"where to save (default {DEFAULT_OUTPUT})",
    )
    parser.add_argument(
        "--kind",
        choices=("all", "airline_logo", "aircraft_image", "logo", "aircraft"),
        default="all",
        help="only logos or only aircraft",
    )
    parser.add_argument(
        "--variants",
        type=int,
        default=1,
        help="pictures per file to choose from (saved as -1, -2, ...)",
    )
    parser.add_argument("--steps", type=int, help="sampling steps (default: Draw Things' setting)")
    parser.add_argument(
        "--guidance", type=float, help="guidance scale (default: Draw Things' setting)"
    )
    parser.add_argument("--seed", type=int, default=-1, help="seed (-1 for random)")
    parser.add_argument(
        "--name",
        action="append",
        default=[],
        metavar="CODE=Name",
        help="airline name for a code the log has none for, e.g. --name TWY=Tradewind Aviation",
    )
    parser.add_argument(
        "--flip",
        action="store_true",
        help="mirror aircraft (for a model that draws them nose left)",
    )
    parser.add_argument(
        "--overwrite", action="store_true", help="replace files already in the output folder"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="print what would be drawn and the prompts, then stop",
    )
    parser.add_argument(
        "--timeout", type=float, default=600, help="seconds to wait for each picture"
    )
    args = parser.parse_args(argv)

    if args.log is None and sys.stdin.isatty():
        print(
            "Paste the missing imagery log, then press Ctrl-D (Ctrl-Z, Enter on Windows):",
            file=sys.stderr,
        )
    text = args.log.read_text(encoding="utf-8") if args.log else sys.stdin.read()
    names = {}
    for item in args.name:
        code, sep, name = item.partition("=")
        if not sep or not name.strip():
            parser.error(f"--name wants CODE=Name, not {item!r}")
        names[code.strip().upper()] = name.strip()
    kind = {"logo": "airline_logo", "aircraft": "aircraft_image"}.get(args.kind, args.kind)
    jobs, skipped = jobs_for(parse_log(text), kind=kind, names=names)
    for note in skipped:
        print(f"skip  {note}", file=sys.stderr)
    if not jobs:
        print("Nothing to draw: no usable rows in the log.", file=sys.stderr)
        return 1 if not skipped else 0

    made = failed = 0
    for index, job in enumerate(jobs, 1):
        prompt, negative, size = prompt_for(job)
        paths = _output_paths(args.output, job, max(1, args.variants))
        if not args.overwrite:
            paths = [p for p in paths if not p.exists()]
        print(
            f"[{index}/{len(jobs)}] {job.label}"
            + ("" if paths else "  (already made; --overwrite to redo)")
        )
        if args.dry_run:
            print(f"    prompt: {prompt}\n    size: {size[0]}x{size[1]}")
            continue
        for path in paths:
            seed = args.seed if args.seed >= 0 else int(time.time() * 1000) % 2**31
            try:
                image = generate(
                    args.host,
                    prompt,
                    negative,
                    size,
                    steps=args.steps,
                    guidance=args.guidance,
                    seed=seed,
                    timeout=args.timeout,
                )
                data = finish(job, image, flip=args.flip)
            except urllib.error.URLError as error:
                print(
                    f"Cannot reach Draw Things at {args.host} ({error.reason}). "
                    "In Draw Things, open Settings "
                    "and turn on API Server (HTTP), then try again.",
                    file=sys.stderr,
                )
                return 2
            except Exception as error:  # one bad picture should not stop the rest
                print(f"    failed: {error}", file=sys.stderr)
                failed += 1
                continue
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
            made += 1
            print(f"    saved {path} ({len(data) // 1024} KB)")
    if not args.dry_run:
        print(
            f"\nMade {made} file(s) in {args.output}"
            + (f"; {failed} failed" if failed else "")
            + ". Review them, rename a chosen variant to drop its -N, and copy them into images/."
        )
    return 1 if failed and not made else 0


if __name__ == "__main__":
    sys.exit(main())
