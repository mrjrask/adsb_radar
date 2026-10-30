"""Radar scope drawing shared by the idle radar screen and the flight board's sky map.

Aircraft are top-down silhouettes picked by type (an A380's four engines, a
CRJ's tail engines and T-tail, a turboprop's straight wing and propellers, a
helicopter's rotor), coloured by altitude band. Their lights sit where real
ones do: a steady red navigation light on the left wingtip and green on the
right, a white tail light, white double-flash strobes on the wingtips and
tail, and a red anti-collision beacon on the fuselage.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from functools import lru_cache
from typing import Optional

from PIL import Image, ImageDraw

from . import aircraft_art
from .forms import RADAR_COLOR_DEFAULTS
from .models import advance

LANCZOS = Image.Resampling.LANCZOS
# Icons are drawn this many times larger, then scaled down: antialiased edges.
_SUPERSAMPLE = 4

# Upper bounds of the altitude bands RADAR_ALT_1..4; RADAR_ALT_5 is everything above.
ALTITUDE_CEILINGS = (4000, 10000, 20000, 30000)

NAV_LEFT = (255, 64, 64)
NAV_RIGHT = (70, 255, 120)
STROBE = (255, 255, 255)
BEACON = (255, 40, 30)
TAIL_LIGHT = (235, 240, 255)

# Strobes double-flash, the beacon flashes once; real lights run at 40-100 flashes a minute.
_STROBE_PERIOD = 1.2
_STROBE_GAP = 0.16
_BEACON_PERIOD = 1.05


def rgb(text: str) -> tuple[int, int, int]:
    return tuple(int(text[i:i + 2], 16) for i in (1, 3, 5))  # type: ignore[return-value]


def colors_for(settings) -> dict[str, tuple[int, int, int]]:
    return {key: rgb((settings or {}).get(key) or value) for key, value in RADAR_COLOR_DEFAULTS.items()}


def altitude_band(feet: Optional[int]) -> int:
    return next((i for i, ceiling in enumerate(ALTITUDE_CEILINGS, 1) if (feet or 0) < ceiling), 5)


def altitude_color(colors, feet: Optional[int]) -> tuple[int, int, int]:
    return colors[f"RADAR_ALT_{altitude_band(feet)}"]


# ── Top-down silhouettes ────────────────────────────────────────────────────


@dataclass(frozen=True)
class TopView:
    """A top-down aircraft in a -1..1 box, nose up (y = -1), right half described and mirrored."""

    length: float = 1.0  # fuselage half-length
    body: float = 0.1  # fuselage half-width
    nose: float = 0.22  # length of the nose taper
    span: float = 0.95  # wing half-span
    wing_y: float = -0.15  # wing leading edge at the root
    root_chord: float = 0.42
    tip_chord: float = 0.1
    sweep: float = 0.38  # the tip's leading edge sits this far aft of the root's
    tail_span: float = 0.36
    tail_y: float = 0.66
    tail_chord: float = 0.22
    tail_sweep: float = 0.16
    engines: tuple[tuple[float, float, float, float], ...] = ()  # (x, y, half-width, half-length)
    props: tuple[tuple[float, float, float], ...] = ()  # (x, y, half-span); x = 0 for a nose propeller
    rotor: float = 0.0  # helicopters: main rotor radius
    scale: float = 1.0  # icon size relative to an airliner's

    @property
    def wingtip(self) -> tuple[float, float]:
        return self.span, self.wing_y + self.sweep + self.tip_chord * 0.5


NARROWBODY = TopView(engines=((0.36, -0.1, 0.055, 0.15),))
REGIONAL = TopView(body=0.095, span=0.92, sweep=0.32, engines=((0.32, -0.08, 0.05, 0.13),), scale=0.88)
WIDEBODY = TopView(body=0.11, wing_y=-0.18, root_chord=0.48, tip_chord=0.08, sweep=0.48, tail_span=0.34,
                   engines=((0.36, -0.13, 0.075, 0.17),), scale=1.12)
B747 = TopView(body=0.12, nose=0.3, span=0.92, wing_y=-0.18, root_chord=0.5, tip_chord=0.08, sweep=0.5,
               engines=((0.32, -0.1, 0.06, 0.13), (0.6, 0.08, 0.055, 0.12)), scale=1.18)
A380 = TopView(length=0.9, body=0.14, nose=0.26, span=1.0, wing_y=-0.22, root_chord=0.58, sweep=0.48,
               tail_span=0.4, tail_y=0.54, engines=((0.34, -0.1, 0.065, 0.14), (0.62, 0.09, 0.06, 0.13)),
               scale=1.25)
TAILJET = TopView(body=0.09, span=0.78, wing_y=-0.02, root_chord=0.36, sweep=0.3, tail_span=0.3, tail_y=0.8,
                  tail_chord=0.17, tail_sweep=0.12, engines=((0.16, 0.52, 0.055, 0.14),), scale=0.9)
BIZJET = TopView(body=0.085, span=0.85, wing_y=0.0, root_chord=0.34, tip_chord=0.12, sweep=0.22, tail_span=0.3,
                 tail_y=0.78, tail_chord=0.17, tail_sweep=0.14, engines=((0.15, 0.48, 0.05, 0.12),), scale=0.8)
TURBOPROP = TopView(body=0.09, nose=0.16, span=1.0, wing_y=-0.18, root_chord=0.2, tip_chord=0.12, sweep=0.03,
                    tail_span=0.32, tail_y=0.76, tail_chord=0.18, tail_sweep=0.08,
                    engines=((0.32, -0.3, 0.045, 0.17),), props=((0.32, -0.47, 0.17),), scale=0.88)
LIGHT_PROP = TopView(length=0.78, body=0.085, nose=0.12, span=1.0, wing_y=-0.34, root_chord=0.22, tip_chord=0.18,
                     sweep=0.0, tail_span=0.34, tail_y=0.5, tail_chord=0.2, tail_sweep=0.04,
                     props=((0.0, -0.82, 0.2),), scale=0.72)
HELICOPTER = TopView(rotor=0.95, scale=0.8)

_VIEWS = {
    aircraft_art.A380: A380, aircraft_art.B747: B747, aircraft_art.WIDEBODY: WIDEBODY,
    aircraft_art.NARROWBODY: NARROWBODY, aircraft_art.REGIONAL: REGIONAL, aircraft_art.TAILJET: TAILJET,
    aircraft_art.TURBOPROP: TURBOPROP, aircraft_art.BIZJET: BIZJET, aircraft_art.PROP: LIGHT_PROP,
}
_HELICOPTER_PREFIXES = ("A109", "A119", "A139", "A169", "A189", "AS32", "AS35", "AS50", "AS55", "AS65", "B06",
                        "B105", "B212", "B407", "B412", "B427", "B429", "B430", "B505", "BK17", "EC", "EXPL", "H47",
                        "H60", "H64", "MD52", "MD60", "R22", "R44", "R66", "S61", "S70", "S76", "S92", "UH1")
_FOUR_PROPS = ("C130", "C30J", "P3", "A400")
# ADS-B emitter categories, for aircraft whose type is unknown.
_CATEGORY_VIEWS = {"A1": LIGHT_PROP, "A2": BIZJET, "A3": NARROWBODY, "A4": NARROWBODY, "A5": WIDEBODY,
                   "A7": HELICOPTER}


def view_for(designator: Optional[str], category: Optional[str] = None) -> TopView:
    """The silhouette for an ICAO type designator, else the ADS-B category, else an airliner."""

    code = (designator or "").strip().upper()
    if not code:
        return _CATEGORY_VIEWS.get((category or "").upper(), NARROWBODY)
    if code.startswith(_HELICOPTER_PREFIXES):
        return HELICOPTER
    if code.startswith(_FOUR_PROPS):
        return TURBOPROP
    family = aircraft_art.family_for(code)
    # The remaining shapeless types are big military jets (tankers, bombers, AWACS, C-17).
    return _VIEWS.get(family, B747)


def _ellipse(cx: float, cy: float, rx: float, ry: float, steps: int = 14) -> list[tuple[float, float]]:
    return [(cx + rx * math.cos(a), cy + ry * math.sin(a)) for a in (i * math.tau / steps for i in range(steps))]


def _mirror(right: list[tuple[float, float]]) -> list[tuple[float, float]]:
    return right + [(-x, y) for x, y in reversed(right)]


def _shapes(view: TopView) -> list[list[tuple[float, float]]]:
    if view.rotor:
        blade = 0.05
        rotor = [[(-view.rotor * c - blade * s, -view.rotor * s + blade * c),
                  (view.rotor * c - blade * s, view.rotor * s + blade * c),
                  (view.rotor * c + blade * s, view.rotor * s - blade * c),
                  (-view.rotor * c + blade * s, -view.rotor * s - blade * c)]
                 for c, s in ((math.cos(a), math.sin(a)) for a in (math.pi / 4, -math.pi / 4))]
        return [_ellipse(0, -0.18, 0.2, 0.42), [(0.045, 0.1), (0.045, 0.95), (-0.045, 0.95), (-0.045, 0.1)],
                [(0.16, 0.82), (0.16, 0.92), (-0.16, 0.92), (-0.16, 0.82)], *rotor]
    length, body = view.length, view.body
    fuselage = _mirror([(0.0, -length), (body * 0.6, -length + view.nose * 0.4), (body, -length + view.nose),
                        (body, length * 0.55), (body * 0.3, length)])
    root = body * 0.9
    wing = [(root, view.wing_y), (view.span, view.wing_y + view.sweep),
            (view.span, view.wing_y + view.sweep + view.tip_chord), (root, view.wing_y + view.root_chord)]
    tail = [(root * 0.6, view.tail_y), (view.tail_span, view.tail_y + view.tail_sweep),
            (view.tail_span, view.tail_y + view.tail_sweep + view.tail_chord * 0.55),
            (root * 0.6, view.tail_y + view.tail_chord)]
    shapes = [fuselage]
    for half in (wing, tail):
        shapes += [half, [(-x, y) for x, y in half]]
    for x, y, rx, ry in view.engines:
        shapes += [_ellipse(x, y, rx, ry), _ellipse(-x, y, rx, ry)]
    for x, y, half in view.props:
        thick = 0.03
        shapes.append([(x - half, y - thick), (x + half, y - thick), (x + half, y + thick), (x - half, y + thick)])
        if x:
            shapes.append([(-x - half, y - thick), (-x + half, y - thick), (-x + half, y + thick),
                           (-x - half, y + thick)])
    return shapes


def _rotate(points, heading: float, cx: float, cy: float, half: float) -> list[tuple[float, float]]:
    theta = math.radians(heading)
    cos_t, sin_t = math.cos(theta), math.sin(theta)
    return [(cx + (x * cos_t - y * sin_t) * half, cy + (x * sin_t + y * cos_t) * half) for x, y in points]


@lru_cache(maxsize=4096)
def icon_mask(view: TopView, size: int, heading: int) -> Image.Image:
    """An antialiased *size* x *size* mask of *view* with its nose along *heading* (0 = north)."""

    big = size * _SUPERSAMPLE
    mask = Image.new("L", (big, big), 0)
    draw = ImageDraw.Draw(mask)
    for shape in _shapes(view):
        draw.polygon(_rotate(shape, heading, big / 2, big / 2, big / 2 * 0.96), fill=255)
    return mask.resize((size, size), LANCZOS)


@lru_cache(maxsize=64)
def _glow(color: tuple[int, int, int], radius: int) -> Image.Image:
    """A soft light: a hot core fading out over *radius* pixels."""

    side = radius * 2 + 1
    glow = Image.new("RGBA", (side, side), (0, 0, 0, 0))
    for y in range(side):
        for x in range(side):
            d = math.hypot(x - radius, y - radius) / max(1, radius)
            if d < 1:
                core = max(0.0, 1 - d * 3)
                pixel = tuple(round(c + (255 - c) * core) for c in color)
                glow.putpixel((x, y), pixel + (round(255 * (1 - d) ** 1.6),))
    return glow


def _paste_glow(image: Image.Image, x: float, y: float, color, radius: float) -> None:
    sprite = _glow(color, max(1, round(radius)))
    image.paste(sprite, (round(x - sprite.width / 2), round(y - sprite.height / 2)), sprite)


def _dot(draw: ImageDraw.ImageDraw, x: float, y: float, color, radius: float) -> None:
    if radius < 1:
        draw.point((round(x), round(y)), fill=color)
    else:
        draw.ellipse((x - radius, y - radius, x + radius, y + radius), fill=color)


def draw_lights(image: Image.Image, view: TopView, x: float, y: float, size: float, heading: float,
                now: float, seed: float, fps: float = 15) -> None:
    """Navigation, tail, strobe and beacon lights for an icon of *size* at (x, y)."""

    draw = ImageDraw.Draw(image)
    half = size / 2 * 0.96
    if view.rotor:
        left, right, tail, beacon = (-0.2, -0.18), (0.2, -0.18), (0.0, 0.95), (0.0, 0.05)
        strobes = (tail,)
    else:
        tip_x, tip_y = view.wingtip
        left, right, tail = (-tip_x, tip_y), (tip_x, tip_y), (0.0, view.length)
        beacon = (0.0, view.wing_y + view.root_chord * 0.35)
        strobes = (left, right, tail)
    (lx, ly), (rx, ry), (tx, ty), (bx, by) = _rotate((left, right, tail, beacon), heading, x, y, half)
    steady = size * 0.04
    _dot(draw, lx, ly, NAV_LEFT, steady)
    _dot(draw, rx, ry, NAV_RIGHT, steady)
    _dot(draw, tx, ty, TAIL_LIGHT, steady * 0.8)
    # A flash lasts at least about a frame so a slow display still shows it.
    flash = max(0.06, 1.1 / max(1, fps))
    phase = (now + seed) % _STROBE_PERIOD
    if phase < flash or _STROBE_GAP <= phase < _STROBE_GAP + flash:
        for point in _rotate(strobes, heading, x, y, half):
            _paste_glow(image, *point, STROBE, max(2, size * 0.17))
    if (now + seed + _BEACON_PERIOD / 2) % _BEACON_PERIOD < flash * 1.4:
        _paste_glow(image, bx, by, BEACON, max(2, size * 0.14))


# ── The scope ───────────────────────────────────────────────────────────────


def draw_scope(image: Image.Image, cx: float, cy: float, outer: float, colors, *, radius: float, reach: float,
               line: float, fill: bool = False) -> None:
    """Range rings, the flight-radius ring, crosshairs and the home dot, antialiased."""

    # Keep the oversized layer to a few megapixels at 4K.
    ss = max(1, min(4, int(3000 // max(1, 2 * outer + 8))))
    pad = line * 2 + 2
    left, top = int(cx - outer - pad), int(cy - outer - pad)
    side = int(math.ceil(2 * (outer + pad))) + 1
    layer = Image.new("RGBA", (side * ss, side * ss), (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)
    ox, oy = (cx - left) * ss, (cy - top) * ss

    def ring(r, color, width):
        r *= ss
        draw.ellipse((ox - r, oy - r, ox + r, oy + r), outline=color + (255,), width=max(1, round(width * ss)))

    if fill:
        r = outer * ss
        draw.ellipse((ox - r, oy - r, ox + r, oy + r), fill=colors["RADAR_BACKGROUND"] + (255,))
    for factor in (0.25, 0.5, 0.75):
        ring(outer * factor, colors["RADAR_RING_DIM"], line * 0.8)
    width = max(1, round(line * 0.7 * ss))
    draw.line((ox - outer * ss, oy, ox + outer * ss, oy), fill=colors["RADAR_RING_DIM"] + (255,), width=width)
    draw.line((ox, oy - outer * ss, ox, oy + outer * ss), fill=colors["RADAR_RING_DIM"] + (255,), width=width)
    ring(outer, colors["RADAR_RING"], line)
    ring(outer * radius / reach, colors["RADAR_HOME_RING"], line)
    small = layer.resize((side, side), LANCZOS) if ss > 1 else layer
    image.paste(small, (left, top), small)


def draw_home(image: Image.Image, cx: float, cy: float, colors, size: float) -> None:
    draw = ImageDraw.Draw(image)
    r = max(2.0, size)
    draw.ellipse((cx - r, cy - r, cx + r, cy + r), fill=colors["RADAR_NORTH"])


def draw_sweep(image: Image.Image, cx: float, cy: float, outer: float, now: float, colors, line: float) -> None:
    draw = ImageDraw.Draw(image)
    angle = now % 3.6 / 3.6 * math.tau
    sweep, base = colors["RADAR_SWEEP_COLOR"], colors["RADAR_BACKGROUND"]
    for step in range(32, -1, -1):
        theta = angle - step * 0.014
        amount = (1 - step / 34) * 0.7
        color = tuple(round(base[i] * (1 - amount) + sweep[i] * amount) for i in range(3))
        draw.line((cx, cy, cx + math.sin(theta) * outer, cy - math.cos(theta) * outer),
                  fill=color, width=max(1, round(line)))


def in_motion(aircraft, settings, now: float, unit: str):
    if (settings or {}).get("RADAR_MOTION", True) is False:
        return tuple(aircraft)
    return tuple(advance(a, now, unit=unit) for a in aircraft)


def position(plane, cx: float, cy: float, outer: float, reach: float) -> Optional[tuple[float, float]]:
    """Screen position of *plane*, or None when it is off the scope (never pinned to the rim)."""

    if plane.distance is None or plane.bearing is None or plane.distance > reach:
        return None
    r, b = plane.distance / reach * outer, math.radians(plane.bearing)
    return cx + r * math.sin(b), cy - r * math.cos(b)


def draw_traffic(image: Image.Image, planes, *, cx: float, cy: float, outer: float, reach: float, colors,
                 settings, now: float, icon: float, trail_step: float, focus: Optional[str] = None,
                 accent=None) -> None:
    """Every plane within *reach*, nearest drawn last; *focus* (a hex) drawn larger and ringed in *accent*."""

    settings = settings or {}
    draw = ImageDraw.Draw(image)
    lights = settings.get("RADAR_LIGHTS", True) is not False
    trail = settings.get("RADAR_TRAIL")
    trail = 6 if trail is None else trail
    fps = settings.get("FPS") or 15
    ordered = sorted(planes, key=lambda a: (a.hex == focus, -(a.distance or 0)))
    for plane in ordered:
        spot = position(plane, cx, cy, outer, reach)
        if spot is None:
            continue
        x, y = spot
        view = view_for(plane.aircraft_type, getattr(plane, "category", None))
        focused = plane.hex == focus
        size = max(6, round(icon * view.scale * (1.6 if focused else 1)))
        color = altitude_color(colors, plane.altitude_ft)
        heading = plane.track
        if focused and accent is not None:
            width = max(1, round(icon / 12))
            draw.line((cx, cy, x, y), fill=tuple(c // 2 for c in accent), width=width)
            r = size * 0.62
            draw.ellipse((x - r, y - r, x + r, y + r), outline=accent, width=width)
        if heading is None:
            r = max(2, size * 0.18)
            draw.ellipse((x - r, y - r, x + r, y + r), fill=color)
            continue
        if trail:
            t = math.radians(heading)
            length = trail * trail_step
            draw.line((x, y, x - math.sin(t) * length, y + math.cos(t) * length),
                      fill=tuple(c // 3 for c in color), width=max(1, round(icon / 14)))
        mask = icon_mask(view, size, round(heading / 3) * 3 % 360)
        image.paste(color, (round(x - size / 2), round(y - size / 2)), mask)
        if lights:
            seed = int(plane.hex.lstrip("~") or "0", 16) % 997 / 997 * _STROBE_PERIOD
            draw_lights(image, view, x, y, size, heading, now, seed, fps)
