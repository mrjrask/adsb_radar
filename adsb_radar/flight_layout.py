"""High resolution flight layout adapted from desk_display draw_adsb_overhead.

Artwork comes from images/air and images/aircraft; missing files use drawn
badges and the procedural aircraft fallback.
"""
from __future__ import annotations

import logging
import math
import os
import time
from dataclasses import dataclass, field, replace
from functools import lru_cache
from pathlib import Path
from typing import Any, Optional

from PIL import Image, ImageDraw, ImageFont

from . import aircraft_art, airline_directory, flight_routes, fonts, missing_imagery, radar
from .models import LiveAircraft, haversine_distance

LANCZOS = Image.Resampling.LANCZOS
ASSET_DIR = Path(os.environ.get("ADSB_RADAR_ASSETS", str(Path(__file__).resolve().parents[1] / "images")))


BACKGROUND = (0, 0, 0)
TEXT = (240, 244, 248)
SECONDARY = (176, 188, 202)
LABEL = (118, 132, 150)
FAINT = (52, 64, 80)
CARD = (13, 19, 27)
CARD_EDGE = (30, 41, 55)
TILE = (246, 247, 249)
CLIMB = (95, 220, 150)
DESCEND = (255, 150, 80)
FALLBACK_BADGE = (58, 74, 92)
DEFAULT_ACCENT = (96, 170, 255)
# Split-flap tiles for the airport codes, like a departures board.
FLAP_TOP = (46, 50, 58)
FLAP_BOTTOM = (34, 37, 44)
FLAP_EDGE = (62, 67, 77)
FLAP_HINGE = (6, 7, 9)
FLAP_TEXT = (246, 244, 236)
# A tile is this wide for its height; tiles in a code sit this far apart.
FLAP_ASPECT = 0.72
FLAP_SPACING = 0.08

# The sky map shows traffic out to this multiple of ADSB_OVERHEAD_RADIUS.
RADAR_RANGE_FACTOR = 2.0
# 1080p: the sky map takes a little less of the width so the route keeps a
# comfortable size instead of growing to poster scale.
_RADAR_SHARE_1080P = 0.36
_RADAR_SHARE = 0.37
# The aircraft illustration's box is this tall for its width.
_AIRCRAFT_ASPECT = 0.34
# On square panels the aircraft shares a column with the stats, so it gives up some height to them.
_AIRCRAFT_ASPECT_SQUARE = 0.24
# Shapes (track, plane icons, sky map) are drawn this many times larger and
# scaled down, which antialiases their edges.
_SUPERSAMPLE = 4

_LOGO_EXTENSIONS = (".png", ".jpg", ".jpeg")
_COMPASS = ("N", "NE", "E", "SE", "S", "SW", "W", "NW")
_COMPASS_WORDS = ("north", "northeast", "east", "southeast", "south", "southwest", "west", "northwest")

# A top-down airliner, nose up, in a -1..1 box: the right half, nose to tail.
_PLANE_RIGHT = (
    (0.0, -1.0), (0.1, -0.86), (0.11, -0.28), (0.98, 0.18), (0.98, 0.34), (0.11, 0.12),
    (0.09, 0.64), (0.36, 0.84), (0.36, 0.98), (0.0, 0.9),
)
PLANE_SHAPE = _PLANE_RIGHT + tuple((-x, y) for x, y in reversed(_PLANE_RIGHT[1:-1]))

@dataclass(frozen=True)
class OverheadFlight:
    aircraft: LiveAircraft
    route: Optional[flight_routes.FlightRoute]
    airline: Optional[airline_directory.Airline]
    nearby_count: int = 1
    # Every aircraft on the sky map (the overhead one included), nearest first.
    traffic: tuple[LiveAircraft, ...] = field(default_factory=tuple)
    # The flight sold under other airlines' numbers: (airline, callsign), e.g. Delta's DAL5432.
    codeshares: tuple[tuple[Optional[airline_directory.Airline], str], ...] = ()
    # Which of identities() the header shows (0: the operator).
    brand: int = 0


def identities(flight: OverheadFlight) -> tuple[tuple[Optional[airline_directory.Airline], str], ...]:
    """The airlines and flight numbers the header cycles through, operator first."""

    return ((flight.airline, _callsign(flight.aircraft)),) + flight.codeshares


# A codeshare flight's logo and flight number hold this long, then fade out
# and the next one fades in, in place, over CODESHARE_FADE.
CODESHARE_HOLD = 4.0
CODESHARE_FADE = 1.2


def codeshare_phase(now: float) -> tuple[int, float]:
    """(step, fade): every codeshare flight shows identity ``step % count``; fade is 0 while
    holding and runs to 1 as it fades out (to 0.5) and the next one fades in."""

    period = CODESHARE_HOLD + CODESHARE_FADE
    step = math.floor(now / period)
    return step, max(0.0, min(1.0, (now - step * period - CODESHARE_HOLD) / CODESHARE_FADE))


def crossfade(shown: Image.Image, blank: Image.Image, following: Image.Image, fade: float) -> Image.Image:
    """*shown* fading out to *blank*, then *following* fading in, for fade 0..1."""

    if fade <= 0:
        return shown
    if fade >= 1:
        return following
    half = fade * 2 if fade < 0.5 else fade * 2 - 1
    eased = half * half * (3 - 2 * half)
    return Image.blend(shown, blank, eased) if fade < 0.5 else Image.blend(blank, following, eased)


# ── Drawing helpers ─────────────────────────────────────────────────────────


@lru_cache(maxsize=256)
def _font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    return fonts.load("heading" if bold else "body", size, bold)


def _width(draw: ImageDraw.ImageDraw, text: str, font) -> int:
    return int(draw.textlength(text, font=font))


def _cap(font) -> int:
    """Height of a capital letter above the baseline."""

    return -font.getbbox("H", anchor="ls")[1]


def _fit(draw, text: str, cap_height: float, max_width: int, *, bold: bool = False, minimum: int = 7, role=None):
    """The largest font whose capitals are at most *cap_height* and whose *text* fits *max_width*.

    Returns (font, text); the text is ellipsis-cut only when even *minimum* overflows.
    """

    def selected(size):
        return fonts.load(role, size, bold) if role else _font(size, bold)

    size = max(minimum, int(cap_height / 0.73))
    while size > minimum and (_cap(selected(size)) > cap_height or _width(draw, text, selected(size)) > max_width):
        size -= 1
    font = selected(size)
    if _width(draw, text, font) <= max_width:
        return font, text
    while len(text) > 1 and _width(draw, text + "…", font) > max_width:
        text = text[:-1]
    return font, text.rstrip() + "…"


def _text_line(draw, x: float, baseline: float, text: str, cap_height: float, max_width: int, fill,
               *, bold: bool = False, minimum: int = 7, anchor: str = "ls") -> int:
    """Draw *text* with its baseline at *baseline*; return the drawn width."""

    font, text = _fit(draw, text, cap_height, max_width, bold=bold, minimum=minimum)
    draw.text((round(x), round(baseline)), text, font=font, fill=fill, anchor=anchor)
    return _width(draw, text, font)


def compass_point(bearing: Optional[float]) -> str:
    if bearing is None:
        return ""
    return _COMPASS[int(((bearing % 360) + 22.5) // 45) % 8]


def _compass_word(bearing: Optional[float]) -> str:
    if bearing is None:
        return ""
    return _COMPASS_WORDS[int(((bearing % 360) + 22.5) // 45) % 8]


def altitude_text(feet: Optional[int]) -> str:
    if feet is None:
        return "--"
    return f"{feet:,} ft"


def speed_text(knots: Optional[float]) -> str:
    return "--" if knots is None else f"{knots:.0f} kt"


def distance_text(distance: Optional[float], bearing: Optional[float], unit: str) -> str:
    if distance is None:
        return "--"
    value = f"{distance:.1f}" if distance < 10 else f"{distance:.0f}"
    point = compass_point(bearing)
    return f"{value} {unit} {point}".strip()


def _vertical_state(rate: Optional[int]) -> int:
    """1 climbing, -1 descending, 0 level/unknown (under 300 ft/min either way)."""

    if rate is None or abs(rate) < 300:
        return 0
    return 1 if rate > 0 else -1


def _luminance(color: tuple[int, int, int]) -> float:
    return 0.2126 * color[0] + 0.7152 * color[1] + 0.0722 * color[2]


def _contrast_text(color: tuple[int, int, int]) -> tuple[int, int, int]:
    return (20, 24, 30) if _luminance(color) > 160 else (255, 255, 255)


def _mix(a: tuple[int, int, int], b: tuple[int, int, int], t: float) -> tuple[int, int, int]:
    return tuple(round(a[i] + (b[i] - a[i]) * t) for i in range(3))  # type: ignore[return-value]


def accent_color(airline: Optional[airline_directory.Airline]) -> tuple[int, int, int]:
    """The airline's brand colour, lightened until it reads on black."""

    color = (airline.color if airline is not None and airline.color else None) or DEFAULT_ACCENT
    step = 0
    while _luminance(color) < 105 and step < 10:
        color = _mix(color, (255, 255, 255), 0.18)
        step += 1
    return color


def _plane_points(cx: float, cy: float, size: float, heading: float) -> list[tuple[float, float]]:
    """PLANE_SHAPE centred on (cx, cy), *size* nose to tail, nose along *heading* (0 = up/north)."""

    theta = math.radians(heading)
    cos_t, sin_t = math.cos(theta), math.sin(theta)
    half = size / 2
    return [(cx + (x * cos_t - y * sin_t) * half, cy + (x * sin_t + y * cos_t) * half) for x, y in PLANE_SHAPE]


class _Smooth:
    """An oversized RGBA layer over *box* for antialiased shapes; ``paste()`` puts it on the image."""

    def __init__(self, image: Image.Image, box: tuple[float, float, float, float]):
        self.image = image
        self.left, self.top = int(box[0]), int(box[1])
        self.width = max(1, int(math.ceil(box[2])) - self.left)
        self.height = max(1, int(math.ceil(box[3])) - self.top)
        self.layer = Image.new("RGBA", (self.width * _SUPERSAMPLE, self.height * _SUPERSAMPLE), (0, 0, 0, 0))
        self.draw = ImageDraw.Draw(self.layer)

    def xy(self, x: float, y: float) -> tuple[float, float]:
        return (x - self.left) * _SUPERSAMPLE, (y - self.top) * _SUPERSAMPLE

    def s(self, value: float) -> float:
        return value * _SUPERSAMPLE

    def polygon(self, points, fill) -> None:
        self.draw.polygon([self.xy(x, y) for x, y in points], fill=fill)

    def ellipse(self, cx: float, cy: float, r: float, *, fill=None, outline=None, width: float = 1) -> None:
        x, y = self.xy(cx, cy)
        rr = self.s(r)
        self.draw.ellipse((x - rr, y - rr, x + rr, y + rr), fill=fill, outline=outline,
                          width=max(1, round(self.s(width))))

    def line(self, points, fill, width: float) -> None:
        self.draw.line([self.xy(x, y) for x, y in points], fill=fill, width=max(1, round(self.s(width))))

    def paste(self) -> None:
        small = self.layer.resize((self.width, self.height), LANCZOS)
        self.image.paste(small, (self.left, self.top), small)


# ── Logos ───────────────────────────────────────────────────────────────────


@lru_cache(maxsize=4)
def _logo_index(directory: str, mtime: float) -> dict[str, str]:
    return {name.lower(): os.path.join(directory, name) for name in os.listdir(directory)}


def _logo_path(icao: str) -> Optional[str]:
    directory = str(ASSET_DIR / "air")
    if not icao:
        return None
    try:
        index = _logo_index(directory, os.path.getmtime(directory))
    except OSError:
        return None
    return next((index[f"{icao}{ext}".lower()] for ext in _LOGO_EXTENSIONS if f"{icao}{ext}".lower() in index), None)


@lru_cache(maxsize=64)
def _load_logo(path: str, mtime: float, box: int) -> Optional[Image.Image]:
    try:
        with Image.open(path) as raw:
            logo = raw.convert("RGBA")
    except Exception:
        logging.warning("ADS-B: could not read airline logo %s", path)
        return None
    bbox = logo.getchannel("A").getbbox()
    if bbox:
        logo = logo.crop(bbox)
    scale = min(box / logo.width, box / logo.height)
    size = (max(1, round(logo.width * scale)), max(1, round(logo.height * scale)))
    return logo.resize(size, LANCZOS)


def airline_logo(icao: Optional[str], box: int) -> Optional[Image.Image]:
    path = _logo_path((icao or "").upper())
    if path is None:
        return None
    try:
        mtime = os.path.getmtime(path)
    except OSError:
        return None
    return _load_logo(path, mtime, int(box))


@lru_cache(maxsize=256)
def _logo_tile(airline: Optional[airline_directory.Airline], size: int, logo_mtime: Optional[float]) -> Image.Image:
    tile = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(tile)
    icao = airline.icao if airline else ""
    padding = max(2, round(size * 0.13))
    logo = airline_logo(icao, size - 2 * padding) if icao else None
    radius = max(2, round(size * 0.22))
    if logo is not None:
        draw.rounded_rectangle((0, 0, size - 1, size - 1), radius=radius, fill=TILE + (255,))
        tile.alpha_composite(logo, ((size - logo.width) // 2, (size - logo.height) // 2))
        return tile
    color = (airline.color if airline and airline.color else None) or FALLBACK_BADGE
    smooth = _Smooth(tile, (0, 0, size, size))
    smooth.ellipse(size / 2, size / 2, size / 2, fill=color + (255,))
    code = (airline.iata or airline.icao) if airline else ""
    if not code:
        smooth.polygon(_plane_points(size / 2, size / 2, size * 0.56, 45), fill=(255, 255, 255, 255))
    small = smooth.layer.resize((smooth.width, smooth.height), LANCZOS)
    tile.alpha_composite(small)
    if code:
        font, text = _fit(draw, code, size * 0.3, round(size * 0.74), bold=True)
        draw.text((size / 2, size / 2), text, font=font, fill=_contrast_text(color), anchor="mm")
    return tile


def logo_tile(airline: Optional[airline_directory.Airline], size: int, callsign: Optional[str] = None) -> Image.Image:
    """A *size* square RGBA tile: the airline's logo on white, else a brand-colour badge (and a log entry)."""

    path = _logo_path(airline.icao) if airline and airline.icao else None
    if airline and path is None:
        missing_imagery.record_logo(airline.icao, ASSET_DIR / "air", airline_name=airline.name, callsign=callsign)
    try:
        mtime = os.path.getmtime(path) if path else None
    except OSError:
        mtime = None
    return _logo_tile(airline, int(size), mtime)


def _draw_logo_tile(image: Image.Image, x: int, y: int, size: int,
                    airline: Optional[airline_directory.Airline], callsign: Optional[str] = None) -> None:
    """White rounded tile with the airline's logo, or a brand-colour badge."""

    if airline is None:  # a callsign naming an airline the directory lacks
        missing_imagery.record_logo(airline_directory.airline_code(callsign), ASSET_DIR / "air", callsign=callsign)
    tile = logo_tile(airline, size, callsign)
    image.paste(tile, (x, y), tile)


# ── Pieces ──────────────────────────────────────────────────────────────────


def _callsign(aircraft: LiveAircraft) -> str:
    return (aircraft.callsign or "").strip().upper() or aircraft.hex.upper()


def route_progress(flight: OverheadFlight, unit: str) -> Optional[tuple[float, float, float]]:
    """(fraction flown, distance flown, distance to go) from the route's airports, or None."""

    route, aircraft = flight.route, flight.aircraft
    if route is None or route.origin is None or route.destination is None:
        return None
    origin, destination = route.origin, route.destination
    if None in (origin.latitude, origin.longitude, destination.latitude, destination.longitude):
        return None
    flown = haversine_distance(origin.latitude, origin.longitude, aircraft.latitude, aircraft.longitude, unit=unit)
    to_go = haversine_distance(aircraft.latitude, aircraft.longitude, destination.latitude, destination.longitude,
                               unit=unit)
    total = flown + to_go
    if total <= 0:
        return None
    return flown / total, flown, to_go


def _subtitle(flight: OverheadFlight, airline, callsign: str) -> str:
    """'UAE235 · A380-800' (flight number and aircraft type)."""

    parts = []
    if airline is not None:
        parts.append(callsign)
    type_name = airline_directory.aircraft_type_name(flight.aircraft.aircraft_type)
    if type_name:
        parts.append(type_name)
    return " · ".join(parts)


def _draw_header(image: Image.Image, box, flight: OverheadFlight) -> None:
    left, top, right, bottom = box
    draw = ImageDraw.Draw(image)
    tile = round(bottom - top)
    choices = identities(flight)
    airline, callsign = choices[flight.brand % len(choices)]
    # The hex ID stands in for a missing callsign; only a real callsign can name an airline.
    _draw_logo_tile(image, round(left), round(top), tile, airline,
                    callsign if airline is not None else flight.aircraft.callsign)
    x = left + tile + max(4, round(tile * 0.2))
    width = round(right - x)
    name = airline.name if airline is not None else callsign
    font, fitted = _fit(draw, name, tile * 0.3, width, bold=True)
    if fitted != name and airline is not None:
        name = airline.short_name
    subtitle = _subtitle(flight, airline, callsign)
    name_cap = tile * 0.3
    sub_cap = tile * 0.19
    gap = tile * 0.16
    block = name_cap + gap + sub_cap if subtitle else name_cap
    baseline = top + (tile - block) / 2 + name_cap
    _text_line(draw, x, baseline, name, name_cap, width, TEXT, bold=True)
    if subtitle:
        _text_line(draw, x, baseline + gap + sub_cap, subtitle, sub_cap, width, SECONDARY)


def _draw_track(image: Image.Image, x0: float, x1: float, y: float, thickness: float, fraction: Optional[float],
                accent, plane: float) -> None:
    """The route line from origin to destination, filled up to the plane."""

    if x1 - x0 < plane * 2:
        return
    smooth = _Smooth(image, (x0 - plane, y - plane, x1 + plane, y + plane))
    dot = thickness * 1.6
    smooth.line([(x0, y), (x1, y)], fill=FAINT + (255,), width=thickness)
    smooth.ellipse(x0, y, dot, fill=accent + (255,))
    smooth.ellipse(x1, y, dot, fill=FAINT + (255,), outline=accent + (255,), width=thickness * 0.8)
    # The plane stays clear of the end dots (and the codes beyond them).
    reach0, reach1 = x0 + plane * 0.6, x1 - plane * 0.6
    position = reach0 + (reach1 - reach0) * (0.5 if fraction is None else min(1.0, max(0.0, fraction)))
    if fraction is not None:
        smooth.line([(x0, y), (position, y)], fill=accent + (255,), width=thickness)
    smooth.polygon(_plane_points(position, y, plane, 90), fill=(accent if fraction is not None else TEXT) + (255,))
    smooth.paste()


def flap_width(code: str, tile_h: float) -> float:
    count = max(1, len(code))
    return count * tile_h * FLAP_ASPECT + (count - 1) * tile_h * FLAP_SPACING


def _draw_flaps(image: Image.Image, x: float, middle: float, code: str, tile_h: float) -> None:
    """*code* as split-flap tiles starting at *x*, centred on *middle*: one tile per letter, split across the middle."""

    tile_w = tile_h * FLAP_ASPECT
    top = middle - tile_h / 2
    radius = max(1, round(tile_h * 0.09))
    hinge = max(1, round(tile_h * 0.035))
    font = _fit(ImageDraw.Draw(image), "W", tile_h * 0.72, round(tile_w * 0.86), bold=True, role="flap")[0]
    for index, letter in enumerate(code):
        x0 = round(x + index * tile_w * (1 + FLAP_SPACING / FLAP_ASPECT))
        y0 = round(top)
        x1, y1 = x0 + round(tile_w) - 1, y0 + round(tile_h) - 1
        split = round(middle)
        tile = Image.new("RGB", (x1 - x0 + 1, y1 - y0 + 1), BACKGROUND)
        draw = ImageDraw.Draw(tile)
        w, h, mid = tile.width, tile.height, split - y0
        draw.rectangle((0, 0, w - 1, mid), fill=FLAP_TOP)
        draw.rectangle((0, mid, w - 1, h - 1), fill=FLAP_BOTTOM)
        draw.rounded_rectangle((0, 0, w - 1, h - 1), radius=radius, outline=FLAP_EDGE)
        draw.text((w / 2, mid + _cap(font) / 2), letter, font=font, fill=FLAP_TEXT, anchor="ms")
        # The lower flap sits a shade darker, under the upper one.
        shade = Image.new("RGB", (w, h - mid), (0, 0, 0))
        lower = tile.crop((0, mid, w, h))
        tile.paste(Image.blend(lower, shade, 0.14), (0, mid))
        draw.rectangle((0, mid - hinge // 2, w - 1, mid - hinge // 2 + hinge - 1), fill=FLAP_HINGE)
        mask = Image.new("L", tile.size, 0)
        ImageDraw.Draw(mask).rounded_rectangle((0, 0, w - 1, h - 1), radius=radius, fill=255)
        image.paste(tile, (x0, y0), mask)


def _draw_route(image: Image.Image, box, flight: OverheadFlight, home, unit: str, accent) -> None:
    """Codes, cities and the progress track; then the phase line and distances."""

    left, top, right, bottom = box
    draw = ImageDraw.Draw(image)
    height, width = bottom - top, right - left
    route = flight.route
    code_cap = min(height * 0.3, width * 0.11)
    city_cap = code_cap * 0.36
    phase_cap = code_cap * 0.42
    stat_cap = code_cap * 0.3
    gap = code_cap * 0.42

    has_route = route is not None and (route.origin or route.destination)
    progress = route_progress(flight, unit) if has_route else None
    progress_line = progress is not None
    origin = (route.origin.code if route.origin else "") or "?" if has_route else ""
    destination = (route.destination.code if route.destination else "") or "?" if has_route else ""
    tile_h = min(code_cap * 1.45, height * 0.36)
    if has_route:
        # Both codes plus a track with room for its plane must fit across.
        across = (flap_width(origin, 1) + flap_width(destination, 1) + 1.9) * tile_h
        if across > width:
            tile_h *= width / across
    head_h = tile_h if has_route else code_cap
    block = head_h + gap * 0.55 + city_cap + gap * 1.15 + phase_cap
    if progress and block + gap * 0.7 + stat_cap <= height:
        block += gap * 0.7 + stat_cap
    else:
        progress_line = False
    y = top + max(0.0, (height - block) / 2)
    code_base = y + (head_h + code_cap) / 2

    if has_route:
        middle = y + tile_h / 2
        origin_w, dest_w = flap_width(origin, tile_h), flap_width(destination, tile_h)
        _draw_flaps(image, left, middle, origin, tile_h)
        _draw_flaps(image, right - dest_w, middle, destination, tile_h)
        pad = tile_h * 0.3
        _draw_track(image, left + origin_w + pad, right - dest_w - pad, middle,
                    max(1.5, tile_h * 0.05), progress[0] if progress else None, accent, tile_h * 0.56)
        city_base = y + tile_h + gap * 0.55 + city_cap
        half = round(width / 2 - gap)
        if route.origin:
            _text_line(draw, left, city_base, route.origin.municipality or route.origin.short_name, city_cap, half,
                       LABEL)
        if route.destination:
            _text_line(draw, right, city_base, route.destination.municipality or route.destination.short_name,
                       city_cap, half, LABEL, anchor="rs")
        phase, airport = flight_routes.flight_phase(route, home or (None, None))
        phase_base = city_base + gap * 1.15 + phase_cap
        label_w = _text_line(draw, left, phase_base, phase + " ", phase_cap, round(width * 0.5), SECONDARY)
        if airport is not None:
            _text_line(draw, left + label_w, phase_base, airport.short_name, phase_cap, round(width - label_w), TEXT,
                       bold=True)
        if progress_line:
            _fraction, flown, to_go = progress
            stats = f"{flown:,.0f} {unit} flown · {to_go:,.0f} {unit} to go"
            _text_line(draw, left, phase_base + gap * 0.7 + stat_cap, stats, stat_cap, round(width), LABEL)
        return

    # No route on file: the plane's heading is the headline.
    aircraft = flight.aircraft
    heading = _compass_word(aircraft.track)
    icon = code_cap * 1.15
    if aircraft.track is not None:
        smooth = _Smooth(image, (left, code_base - code_cap / 2 - icon / 2, left + icon, code_base - code_cap / 2 + icon / 2))
        smooth.polygon(_plane_points(left + icon / 2, code_base - code_cap / 2, icon, aircraft.track), fill=accent + (255,))
        smooth.paste()
    text_x = left + (icon + gap if aircraft.track is not None else 0)
    title = f"Heading {heading}" if heading else "Overhead now"
    _text_line(draw, text_x, code_base, title, code_cap * 0.62, round(right - text_x), TEXT, bold=True)
    detail = f"Track {aircraft.track:.0f}°" if aircraft.track is not None else ""
    city_base = code_base + gap * 0.55 + city_cap
    if detail:
        _text_line(draw, text_x, city_base, detail, city_cap, round(right - text_x), LABEL)
    note = "No route on file for this flight" if flight.airline is not None else "Private or general aviation"
    _text_line(draw, left, city_base + gap * 1.15 + phase_cap, note, phase_cap, round(width), SECONDARY)


def _cards(flight: OverheadFlight, unit: str, *, units_in_label: bool = False) -> list[tuple[str, str, int]]:
    """(label, value, climb/descent) per card; *units_in_label* moves the units up so the numbers can be bigger."""

    aircraft = flight.aircraft
    if units_in_label:
        distance = distance_text(aircraft.distance, aircraft.bearing, unit)
        if distance.startswith(f"{distance.split(' ')[0]} {unit}"):
            distance = distance.replace(f" {unit}", "", 1)
        return [
            ("ALT · FT", "--" if aircraft.altitude_ft is None else f"{aircraft.altitude_ft:,}",
             _vertical_state(aircraft.vertical_rate_fpm)),
            ("SPEED · KT", "--" if aircraft.ground_speed_kt is None else f"{aircraft.ground_speed_kt:.0f}", 0),
            (f"DIST · {unit.upper()}", distance, 0),
        ]
    return [
        ("ALTITUDE", altitude_text(aircraft.altitude_ft), _vertical_state(aircraft.vertical_rate_fpm)),
        ("SPEED", speed_text(aircraft.ground_speed_kt), 0),
        ("FROM YOU", distance_text(aircraft.distance, aircraft.bearing, unit), 0),
    ]


def _draw_cards(image: Image.Image, box, flight: OverheadFlight, unit: str, *, vertical: bool = False) -> None:
    draw = ImageDraw.Draw(image)
    left, top, right, bottom = box
    count = 3
    if vertical:
        gap = max(3, round((bottom - top) * 0.035))
        card_w, card_h = right - left, (bottom - top - gap * (count - 1)) / count
    else:
        gap = max(3, round((right - left) * 0.02))
        card_w, card_h = (right - left - gap * (count - 1)) / count, bottom - top
    radius = max(2, round(min(card_w, card_h) * 0.16))
    # Short, wide cards put the label and value on one line; tall, narrow ones
    # print the units in the label so the numbers get the width.
    inline = card_h < card_w * 0.3
    cards = _cards(flight, unit, units_in_label=not inline)
    pad = max(3, round(min(card_h * 0.15, card_w * 0.07) if not inline else card_w * 0.05))
    inner = round(card_w) - 1 - 2 * pad
    label_cap = min(card_h * 0.15, card_w * 0.085) if not inline else card_h * 0.27
    value_cap = min(card_h * 0.4, card_w * 0.22) if not inline else card_h * 0.46
    if inline:
        inner = round(inner * 0.62)
    arrow_gap = max(2, round(value_cap * 0.35))
    # One size for every value (and every label) so the row reads as a set.
    value_font = min(
        (_fit(draw, value, value_cap, inner - (round(value_cap) + arrow_gap if trend else 0), bold=True, role="mono",
              minimum=6)[0] for _label, value, trend in cards),
        key=lambda font: font.size,
    )
    label_font = min((_fit(draw, label, label_cap, inner, bold=True, minimum=6)[0] for label, _v, _t in cards),
                     key=lambda font: font.size)
    for index, (label, value, trend) in enumerate(cards):
        if vertical:
            x0, y0 = left, top + index * (card_h + gap)
        else:
            x0, y0 = left + index * (card_w + gap), top
        x0, y0 = round(x0), round(y0)
        x1, y1 = round(x0 + card_w) - 1, round(y0 + card_h) - 1
        draw.rounded_rectangle((x0, y0, x1, y1), radius=radius, fill=CARD, outline=CARD_EDGE)
        if inline:
            middle = (y0 + y1) / 2
            draw.text((x0 + pad, round(middle + _cap(label_font) / 2)), label, font=label_font, fill=LABEL,
                      anchor="ls")
            value_base = round(middle + _cap(value_font) / 2)
            value_w = _width(draw, value, value_font)
            x = x1 - pad - value_w - ((round(_cap(value_font) * 0.9) + arrow_gap) if trend else 0)
        else:
            draw.text((x0 + pad, y0 + pad + _cap(label_font)), label, font=label_font, fill=LABEL, anchor="ls")
            value_base = y1 - pad
            x = x0 + pad
        if trend:
            cap = _cap(value_font)
            arrow = _Smooth(image, (x, value_base - cap, x + cap, value_base))
            if trend > 0:
                points = [(x, value_base), (x + cap * 0.9, value_base), (x + cap * 0.45, value_base - cap)]
            else:
                points = [(x, value_base - cap), (x + cap * 0.9, value_base - cap), (x + cap * 0.45, value_base)]
            arrow.polygon(points, fill=(CLIMB if trend > 0 else DESCEND) + (255,))
            arrow.paste()
            x += round(cap * 0.9) + arrow_gap
        _font_used, text = _fit(draw, value, _cap(value_font), x1 - pad - x, bold=True, minimum=value_font.size, role="mono")
        draw.text((x, value_base), text, font=value_font, fill=TEXT, anchor="ls")


def _sky_geometry(box, radius: float, reach: Optional[float]):
    """(cx, cy, outer, size, reach, line) of the sky map in *box*."""

    left, top, right, bottom = box
    size = min(right - left, bottom - top)
    label_cap = max(5.0, size * 0.035)
    reach = max(radius, reach) if reach else radius * RADAR_RANGE_FACTOR
    return (left + right) / 2, (top + bottom) / 2, size / 2 - label_cap * 1.8, size, reach, max(1.0, size / 260)


def _draw_radar(image: Image.Image, box, radius: float, unit: str, reach=None, settings=None) -> None:
    """The sky map's scope, styled like the radar screen: filled disc, range rings, flight-radius ring."""

    cx, cy, outer, size, reach, line = _sky_geometry(box, radius, reach)
    colors = radar.colors_for(settings)
    radar.draw_scope(image, cx, cy, outer, colors, radius=radius, reach=reach, line=line, fill=True)
    draw = ImageDraw.Draw(image)
    label_cap = max(5.0, size * 0.035)
    font = _font(max(6, round(label_cap / 0.73)), True)
    draw.text((round(cx), round(cy - outer - label_cap * 0.5)), "N", font=font, fill=colors["RADAR_NORTH"],
              anchor="ms")
    ring_font = _font(max(6, round(label_cap * 0.85 / 0.73)))
    draw.text((round(cx), round(cy + outer + label_cap * 1.4)), f"{reach:g} {unit}", font=ring_font,
              fill=colors["RADAR_RANGE_COLOR"], anchor="ms")


def draw_sky_traffic(image: Image.Image, box, flight: OverheadFlight, settings, now: float, *, radius: float,
                     unit: str, reach=None) -> None:
    """The sky map's sweep and traffic for one frame; the overhead flight is larger and ringed in its accent."""

    cx, cy, outer, size, reach, line = _sky_geometry(box, radius, reach)
    colors = radar.colors_for(settings)
    if (settings or {}).get("RADAR_SWEEP", True) is not False:
        radar.draw_sweep(image, cx, cy, outer, now, colors, line)
    radar.draw_home(image, cx, cy, colors, size * 0.012)
    planes = radar.in_motion(flight.traffic or (flight.aircraft,), settings, now, unit)
    radar.draw_traffic(image, planes, cx=cx, cy=cy, outer=outer, reach=reach, colors=colors, settings=settings,
                       now=now, icon=max(12.0, size * 0.07), trail_step=size / 230, focus=flight.aircraft.hex,
                       accent=accent_color(flight.airline))


def radar_box(width: int, height: int):
    """Where the flight board's sky map sits, or None when the layout has none."""

    return _layout(width, height).get("radar")


# ── Composition ─────────────────────────────────────────────────────────────


def _layout(width: int, height: int) -> dict[str, Any]:
    """Boxes for header, route, cards and sky map, as (left, top, right, bottom)."""

    margin = max(4, round(min(width, height) * 0.045))
    gap = max(4, round(min(width, height) * 0.04))
    inner_w, inner_h = width - 2 * margin, height - 2 * margin
    boxes: dict[str, Any] = {"margin": margin}
    if height >= width * 0.85:
        # Square: header and route across the top, sky map and stacked cards below.
        header_h = round(inner_h * 0.15)
        route_h = round(inner_h * 0.34)
        lower_top = margin + header_h + gap + route_h + gap
        lower_h = height - margin - lower_top
        side = min(lower_h, round(inner_w * 0.56))
        boxes["header"] = (margin, margin, width - margin, margin + header_h)
        boxes["route"] = (margin, margin + header_h + gap, width - margin, margin + header_h + gap + route_h)
        boxes["radar"] = (margin, lower_top, margin + side, lower_top + side)
        art_h = round((width - margin - (margin + side + gap)) * _AIRCRAFT_ASPECT_SQUARE)
        boxes["aircraft"] = (margin + side + gap, lower_top, width - margin, lower_top + art_h)
        boxes["cards"] = (margin + side + gap, lower_top + art_h + gap, width - margin, lower_top + side)
        boxes["cards_vertical"] = True
        return boxes
    with_radar = width >= 480 and height >= 240
    share = _RADAR_SHARE_1080P if (width >= 1600 and height >= 900) else _RADAR_SHARE
    radar_side = min(inner_h, round(inner_w * share)) if with_radar else 0
    content_right = width - margin - (radar_side + gap * 2 if with_radar else 0)
    compact = height < 200
    header_h = round(inner_h * (0.2 if not compact else 0.24))
    cards_h = 0 if compact else round(inner_h * 0.23)
    route_top = margin + header_h + gap
    # Compact panels print the stats as one line under the route instead of cards.
    footer = cards_h + gap if cards_h else round(max(5, height * 0.05) * 1.6)
    route_bottom = height - margin - footer
    boxes["header"] = (margin, margin, content_right, margin + header_h)
    boxes["route"] = (margin, route_top, content_right, route_bottom)
    if cards_h:
        boxes["cards"] = (margin, height - margin - cards_h, content_right, height - margin)
    if with_radar:
        # The aircraft above the sky map, the pair centred in the right-hand column.
        art_h = round(radar_side * _AIRCRAFT_ASPECT)
        side = min(radar_side, inner_h - art_h - gap)
        column_top = margin + (inner_h - art_h - gap - side) / 2
        x0 = width - margin - radar_side
        boxes["aircraft"] = (x0, column_top, width - margin, column_top + art_h)
        radar_left = x0 + (radar_side - side) / 2
        boxes["radar"] = (radar_left, column_top + art_h + gap, radar_left + side, column_top + art_h + gap + side)
    return boxes


def _wash(image: Image.Image, accent, depth: float) -> None:
    """A soft glow of the airline's colour across the top of the screen."""

    width, height = image.size
    rows = max(1, round(height * depth))
    tint = _mix(BACKGROUND, accent, 0.2)
    gradient = Image.new("RGB", (1, rows))
    for row in range(rows):
        t = (1 - row / rows) ** 1.6
        gradient.putpixel((0, row), _mix(BACKGROUND, tint, t))
    image.paste(gradient.resize((width, rows)), (0, 0))


def header_box(width: int, height: int) -> tuple[int, int, int, int]:
    """The flight board's logo, airline and flight number, as whole pixels (left, top, right, bottom)."""

    left, top, right, bottom = _layout(width, height)["header"]
    return math.floor(left), math.floor(top), math.ceil(right), math.ceil(bottom)


def compose_header(flight: OverheadFlight, width: int, height: int, brand: Optional[int]) -> Image.Image:
    """The board's header area showing identity *brand*, or just its background for None.

    Pixel-identical to that area of :func:`compose_overhead_image`, so it can be pasted over it.
    """

    image = Image.new("RGB", (width, height), BACKGROUND)
    _wash(image, accent_color(flight.airline), 0.45)
    box = _layout(width, height)["header"]
    if brand is not None:
        _draw_header(image, box, replace(flight, brand=brand))
    return image.crop(header_box(width, height))


def _compose_flight(image: Image.Image, flight: OverheadFlight, home, unit: str, radius: float, radar_range=None,
                    settings=None, traffic: bool = True, now: Optional[float] = None) -> None:
    width, height = image.size
    accent = accent_color(flight.airline)
    boxes = _layout(width, height)
    _wash(image, accent, 0.45)
    _draw_header(image, boxes["header"], flight)
    _draw_route(image, boxes["route"], flight, home, unit, accent)
    if "cards" in boxes:
        _draw_cards(image, boxes["cards"], flight, unit, vertical=boxes.get("cards_vertical", False))
    else:
        draw = ImageDraw.Draw(image)
        margin = boxes["margin"]
        stats = " · ".join((altitude_text(flight.aircraft.altitude_ft), speed_text(flight.aircraft.ground_speed_kt),
                            distance_text(flight.aircraft.distance, flight.aircraft.bearing, unit)))
        _text_line(draw, margin, height - margin, stats, max(5, height * 0.05), width - 2 * margin, SECONDARY,
                   minimum=6)
    if "radar" in boxes:
        _draw_radar(image, boxes["radar"], radius, unit, radar_range, settings)
        if traffic:
            draw_sky_traffic(image, boxes["radar"], flight, settings, time.time() if now is None else now,
                             radius=radius, unit=unit, reach=radar_range)
    if "aircraft" in boxes:
        _draw_aircraft(image, boxes["aircraft"], flight)


def _draw_aircraft(image: Image.Image, box, flight: OverheadFlight) -> None:
    """The aircraft's type in its airline's livery, centred in *box* (see ``rendering/aircraft_art.py``)."""

    left, top, right, bottom = box
    airline = flight.airline
    icao = airline.icao if airline is not None else None
    width = round(right - left)
    art = aircraft_art.aircraft_image(width, designator=flight.aircraft.aircraft_type, airline_icao=icao,
                                      brand=airline.color if airline is not None else None,
                                      logo_path=_logo_path(icao or ""))
    _log_missing_aircraft(flight, art is not None)
    if art is None:  # helicopters and military types have no illustration
        return
    if art.height > bottom - top:
        scale = (bottom - top) / art.height
        art = art.resize((max(1, round(art.width * scale)), max(1, round(art.height * scale))), LANCZOS)
    x = round(left + (width - art.width) / 2)
    y = round(top + (bottom - top - art.height) / 2)
    image.paste(art, (x, y), art)


def _log_missing_aircraft(flight: OverheadFlight, shown: bool) -> None:
    """Log this type's illustration in the airline's livery when it is not delivered."""

    designator = flight.aircraft.aircraft_type
    airline = flight.airline
    icao = airline.icao if airline is not None else None
    used = aircraft_art.asset_path(designator, icao, aircraft_art.ASSET_DIR)
    exact = os.path.join(aircraft_art.ASSET_DIR, (icao or aircraft_art.GENERIC).upper(),
                         f"{(designator or '').strip().upper()}.png")
    if used is not None and os.path.abspath(used) == os.path.abspath(exact):
        return
    if used is not None:
        instead = os.path.relpath(used, os.path.dirname(aircraft_art.ASSET_DIR))
    else:
        instead = "drawn" if shown else "nothing"
    missing_imagery.record_aircraft(designator, icao, aircraft_art.ASSET_DIR,
                                    airline_name=airline.name if airline is not None else "",
                                    type_name=airline_directory.aircraft_type_name(designator),
                                    callsign=flight.aircraft.callsign, showing_instead=instead)


def compose_overhead_image(
    flight: OverheadFlight,
    *,
    width: Optional[int] = None,
    height: Optional[int] = None,
    home: Optional[tuple[float, float]] = None,
    unit: Optional[str] = None,
    radius: Optional[float] = None,
    radar_range: Optional[float] = None,
    settings: Optional[dict] = None,
    traffic: bool = True,
    now: Optional[float] = None,
) -> Image.Image:
    """The flight board for *flight*. Idle screens (radar, clock, clear skies) are drawn by scene.py.

    *settings* supplies the radar colours and controls. With *traffic* off the sky map is left empty
    for ``draw_sky_traffic`` to animate each frame."""

    width = int(width or 1920)
    height = int(height or 1080)
    unit = unit or "nm"
    radius = 3.0 if radius is None else radius
    image = Image.new("RGB", (width, height), BACKGROUND)
    _compose_flight(image, flight, home, unit, radius, radar_range, settings, traffic, now)
    return image
