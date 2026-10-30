"""Side-view aircraft illustrations painted in airline liveries.

The "adsb overhead" screen shows the aircraft passing over: the right shape
for its type (an A380's double deck, a 747's hump, a CRJ's tail engines, an
ATR's high wing and propellers) painted in a close match to the operator's
livery, with the airline's logo on the tail when it reads there.

Shapes are drawn from a handful of families rather than per type: what the
type designator tells us (``B39M`` -> narrowbody, ``A388`` -> A380) is enough
to pick the silhouette, and proportions are close enough at panel sizes.
Liveries are a table of colours per airline ICAO code (body, belly, tail,
tail stripes, cheatline, engines); airlines without an entry get a white
body with the brand colour on the tail and engines.

Everything is drawn here, so it works offline and needs no image licences.

Delivered illustrations win over the drawing: ``images/aircraft/{AIRLINE}/{TYPE}.png``
(see the aircraft illustration spec) is looked up first by exact type, then by a
sibling type in the same series in that airline's folder (a B38M stands in for a
B39M), then ``_generic/{TYPE}.png`` or a sibling there (the CJ3 for any light jet); only when none exists is the aircraft drawn.
"""
from __future__ import annotations

import math
import os
import re
from dataclasses import dataclass
from functools import lru_cache
from typing import Optional, Sequence

from PIL import Image, ImageChops, ImageDraw

LANCZOS = Image.Resampling.LANCZOS

Color = tuple[int, int, int]

WHITE: Color = (244, 246, 248)
LIGHT_GREY: Color = (206, 211, 217)
WINDOW: Color = (38, 48, 60)
WING: Color = (150, 157, 166)
SHADOW: Color = (110, 117, 126)

# Drawn this many times larger, then scaled down: antialiased edges.
_SUPERSAMPLE = 4

ASSET_DIR = os.environ.get("ADSB_RADAR_ASSETS", os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "images"))
ASSET_DIR = os.path.join(ASSET_DIR, "aircraft")
GENERIC = "_generic"

# Types in one series share a livery and nearly a silhouette, so one airline's file
# can stand in for its siblings (length differs a little). Closest sibling first.
_SERIES: tuple[tuple[str, ...], ...] = (
    ("B37M", "B38M", "B39M", "B3XM"),
    ("B736", "B737", "B738", "B739"),
    ("B788", "B789", "B78X"),
    ("B772", "B77L", "B773", "B77W", "B778", "B779"),
    ("B762", "B763", "B764"),
    ("B752", "B753"),
    ("B742", "B744", "B74S", "B748"),
    ("A19N", "A20N", "A21N"),
    ("A318", "A319", "A320", "A321"),
    ("A332", "A333", "A338", "A339"),
    ("A342", "A343", "A345", "A346"),
    ("A359", "A35K"),
    ("BCS1", "BCS3"),
    ("E170", "E75S", "E75L", "E190", "E195", "E290", "E295"),
    ("E135", "E140", "E145"),
    ("CRJ1", "CRJ2", "CRJ7", "CRJ9", "CRJX"),
    ("DH8A", "DH8B", "DH8C", "DH8D"),
    ("AT43", "AT45", "AT46", "AT72", "AT75", "AT76"),
    ("MD82", "MD83", "MD88", "MD90"),
    # Private and general aviation: one picture stands for a whole class (a CJ3 for every light
    # jet, a Cherokee for every low-wing single), since these are drawn plain, not in liveries.
    ("C150", "C152", "C172", "C182", "C206", "C210"),
    ("P28A", "P28B", "P28R", "DA40", "SR20", "SR22", "S22T", "BE33", "BE35", "BE36", "M20P", "M20T",
     "PA32", "P32R", "P32T", "PA46"),
    ("BE58", "BE55", "PA34", "PA44", "DA42", "C310", "C340"),
    ("C208",),
    ("PC12", "TBM7", "TBM8", "TBM9", "P46T"),
    ("BE20", "BE30", "B350", "BE9L", "BE9T"),
    ("C25B", "C25A", "C25C", "C25M", "C525", "C510", "E50P", "E55P", "PC24", "HDJT", "BE40", "PRM1",
     "LJ31", "LJ35", "LJ40", "LJ45"),
    ("C56X", "C560", "C550", "C680", "C68A", "C700", "C750", "H25B", "H25C", "LJ60", "LJ70", "LJ75",
     "E545", "E550", "G280"),
    ("CL35", "CL30", "CL60", "F2TH", "FA50", "F900", "FA7X", "FA8X"),
    ("GLF6", "GLF5", "GLF4", "GA5C", "GA6C", "GA7C", "GA8C", "GLEX", "GL5T", "GL7T", "GL8T"),
    ("EC35", "EC45", "EC30", "AS50", "A109", "A119", "A139", "A169", "B06", "B407", "B429", "R22", "R44",
     "R66", "S76"),
)


@dataclass(frozen=True)
class Livery:
    body: Color = WHITE
    tail: Optional[Color] = None  # None: the airline's brand colour
    belly: Optional[Color] = None  # lower fuselage from ``belly_from`` down
    belly_from: float = 0.35  # in fuselage radii below the centreline
    cheatline: Optional[Color] = None  # a band along the windows
    tail_stripes: Sequence[Color] = ()  # horizontal bands across the fin, top first
    tail_band: Optional[Color] = None  # a band up the fin's leading edge
    engines: Optional[Color] = None  # None: the tail colour
    logo_on_tail: bool = True  # paste the airline logo on the fin when it contrasts


# Close matches to current liveries for airlines seen over North America and
# the big international carriers. Colours, not artwork: enough to know the
# airline at a glance.
LIVERIES: dict[str, Livery] = {
    "AAL": Livery(body=(196, 202, 209), tail_stripes=((0, 69, 140), (0, 69, 140), WHITE, (200, 16, 46), WHITE,
                                                     (200, 16, 46)), engines=(196, 202, 209), logo_on_tail=False),
    "ENY": Livery(body=(196, 202, 209), tail_stripes=((0, 69, 140), (0, 69, 140), WHITE, (200, 16, 46), WHITE,
                                                     (200, 16, 46)), engines=(196, 202, 209), logo_on_tail=False),
    "PDT": Livery(body=(196, 202, 209), tail_stripes=((0, 69, 140), (0, 69, 140), WHITE, (200, 16, 46), WHITE,
                                                     (200, 16, 46)), engines=(196, 202, 209), logo_on_tail=False),
    "PSA": Livery(body=(196, 202, 209), tail_stripes=((0, 69, 140), (0, 69, 140), WHITE, (200, 16, 46), WHITE,
                                                     (200, 16, 46)), engines=(196, 202, 209), logo_on_tail=False),
    "UAL": Livery(tail=(0, 34, 102), belly=(0, 92, 185), belly_from=0.2, engines=(0, 92, 185), logo_on_tail=False),
    "DAL": Livery(tail=(178, 18, 45), belly=(0, 32, 77), belly_from=0.3, engines=(0, 32, 77), logo_on_tail=False),
    "EDV": Livery(tail=(178, 18, 45), belly=(0, 32, 77), belly_from=0.3, engines=(0, 32, 77), logo_on_tail=False),
    "SWA": Livery(body=(48, 72, 170), tail=(48, 72, 170), belly=(255, 191, 39), belly_from=0.55,
                  cheatline=(224, 34, 41), engines=(48, 72, 170), logo_on_tail=False),
    "ASA": Livery(tail=(1, 66, 106), cheatline=(0, 132, 202), engines=(1, 66, 106), logo_on_tail=False),
    "QXE": Livery(tail=(1, 66, 106), cheatline=(0, 132, 202), engines=(1, 66, 106), logo_on_tail=False),
    "JBU": Livery(tail=(0, 32, 91), belly=(0, 32, 91), belly_from=0.45, engines=(0, 32, 91), logo_on_tail=False),
    "NKS": Livery(body=(255, 222, 0), tail=(255, 222, 0), engines=(255, 222, 0), logo_on_tail=False),
    "FFT": Livery(tail=(0, 104, 71), engines=(0, 104, 71), logo_on_tail=False),
    "AAY": Livery(tail=(0, 82, 160), tail_band=(255, 158, 27), engines=(0, 82, 160), logo_on_tail=False),
    "HAL": Livery(tail=(64, 32, 120), tail_band=(204, 0, 102), engines=(64, 32, 120), logo_on_tail=False),
    "SCX": Livery(tail=(255, 102, 0), engines=(255, 102, 0)),
    "ACA": Livery(tail=(20, 20, 22), belly=(20, 20, 22), belly_from=0.55, engines=(20, 20, 22), logo_on_tail=False),
    "JZA": Livery(tail=(20, 20, 22), belly=(20, 20, 22), belly_from=0.55, engines=(20, 20, 22), logo_on_tail=False),
    "WJA": Livery(tail=(0, 56, 101), tail_band=(0, 146, 151), engines=(0, 56, 101), logo_on_tail=False),
    "AMX": Livery(tail=(11, 35, 65), engines=(11, 35, 65), logo_on_tail=False),
    "UAE": Livery(tail=WHITE, tail_band=(206, 17, 38), tail_stripes=((0, 122, 61), WHITE, (20, 20, 20)),
                  engines=WHITE, logo_on_tail=False),
    "QTR": Livery(tail=(93, 16, 59), engines=(93, 16, 59), logo_on_tail=False),
    "ETD": Livery(tail=(189, 150, 92), engines=(189, 150, 92), logo_on_tail=False),
    "THY": Livery(tail=(200, 16, 46), engines=WHITE, logo_on_tail=False),
    "BAW": Livery(belly=(7, 34, 86), belly_from=0.4, tail_stripes=((7, 34, 86), (204, 22, 40), WHITE,
                                                                  (7, 34, 86)), engines=(150, 157, 166),
                  logo_on_tail=False),
    "VIR": Livery(body=(198, 202, 208), tail=(205, 0, 33), engines=(205, 0, 33), logo_on_tail=False),
    "DLH": Livery(tail=(5, 22, 77), engines=(5, 22, 77)),
    "SWR": Livery(tail=(220, 0, 24), engines=WHITE, logo_on_tail=False),
    "AUA": Livery(tail=(220, 0, 24), engines=WHITE, logo_on_tail=False),
    "AFR": Livery(tail=WHITE, tail_stripes=(WHITE, WHITE, (0, 35, 149), (237, 41, 57)), engines=WHITE),
    "KLM": Livery(body=(0, 161, 222), belly=WHITE, belly_from=0.25, tail=(0, 161, 222), engines=(0, 161, 222),
                  logo_on_tail=False),
    "IBE": Livery(tail=(214, 34, 49), tail_band=(255, 204, 0), engines=WHITE, logo_on_tail=False),
    "EIN": Livery(tail=(0, 121, 107), belly=(0, 121, 107), belly_from=0.6, engines=(0, 121, 107),
                  logo_on_tail=False),
    "RYR": Livery(tail=(7, 53, 144), belly=(7, 53, 144), belly_from=0.6, engines=(7, 53, 144), logo_on_tail=False),
    "EZY": Livery(tail=(255, 102, 0), engines=(255, 102, 0), logo_on_tail=False),
    "SAS": Livery(tail=(0, 12, 102), engines=(0, 12, 102), logo_on_tail=False),
    "FIN": Livery(tail=(0, 41, 121), engines=WHITE, logo_on_tail=False),
    "ICE": Livery(tail=(0, 50, 115), engines=(0, 50, 115), logo_on_tail=False),
    "TAP": Livery(tail=(0, 140, 80), tail_band=(226, 0, 26), engines=WHITE, logo_on_tail=False),
    "SIA": Livery(tail=(0, 38, 100), cheatline=(253, 185, 19), engines=WHITE, logo_on_tail=False),
    "CPA": Livery(tail=(0, 101, 100), belly=LIGHT_GREY, belly_from=0.45, engines=(0, 101, 100), logo_on_tail=False),
    "QFA": Livery(tail=(226, 0, 26), engines=(226, 0, 26), logo_on_tail=False),
    "ANA": Livery(tail=(0, 51, 153), cheatline=(0, 51, 153), engines=(0, 51, 153), logo_on_tail=False),
    "JAL": Livery(tail=WHITE, engines=WHITE),
    "KAL": Livery(body=(156, 203, 230), belly=LIGHT_GREY, belly_from=0.4, tail=WHITE, engines=(156, 203, 230)),
    "EVA": Livery(tail=(0, 117, 75), cheatline=(255, 148, 30), engines=WHITE, logo_on_tail=False),
    "CAL": Livery(tail=(250, 190, 200), engines=WHITE),
    "CCA": Livery(tail=WHITE, cheatline=(220, 36, 31), engines=WHITE),
    "AVA": Livery(tail=(218, 26, 50), engines=(218, 26, 50), logo_on_tail=False),
    "CMP": Livery(tail=(0, 50, 130), engines=(0, 50, 130), logo_on_tail=False),
    "LAN": Livery(tail=(30, 20, 100), engines=(30, 20, 100), logo_on_tail=False),
    "FDX": Livery(tail=(77, 20, 140), belly=LIGHT_GREY, belly_from=0.55, engines=(77, 20, 140),
                  logo_on_tail=False),
    "UPS": Livery(body=(53, 30, 16), tail=(53, 30, 16), belly=(53, 30, 16), engines=(53, 30, 16),
                  cheatline=(255, 181, 0), logo_on_tail=False),
    "GTI": Livery(tail=(0, 50, 100), engines=(0, 50, 100), logo_on_tail=False),
}


# ── Families: which silhouette a type designator gets ───────────────────────

A380, B747, WIDEBODY, NARROWBODY, REGIONAL, TAILJET, TURBOPROP, BIZJET, PROP, NONE = (
    "a380", "b747", "widebody", "narrowbody", "regional", "tailjet", "turboprop", "bizjet", "prop", "none",
)

# Designators that are also the start of others (C17 vs C172).
_FAMILY_EXACT: dict[str, str] = {"C17": NONE}

# First matching prefix wins, so exact designators come before the shorter
# prefixes that would otherwise catch them (A310 before A31, C750 before C7).
_FAMILY_PREFIXES: tuple[tuple[str, str], ...] = (
    # No illustration: helicopters and military types none of the shapes fit.
    ("A139", NONE), ("A169", NONE), ("AS50", NONE), ("B06", NONE), ("B407", NONE), ("B429", NONE),
    ("EC", NONE), ("H60", NONE), ("R22", NONE), ("R44", NONE), ("R66", NONE), ("S76", NONE), ("S92", NONE),
    ("C130", NONE), ("C30J", NONE), ("K35R", NONE), ("B52", NONE), ("E3TF", NONE),
    ("A38", A380),
    ("B74", B747),
    ("A310", WIDEBODY), ("A30", WIDEBODY), ("A33", WIDEBODY), ("A34", WIDEBODY), ("A35", WIDEBODY),
    ("B76", WIDEBODY), ("B77", WIDEBODY), ("B78", WIDEBODY), ("KC46", WIDEBODY), ("MD11", WIDEBODY),
    ("DC10", WIDEBODY),
    ("CRJ", TAILJET), ("E135", TAILJET), ("E140", TAILJET), ("E145", TAILJET), ("E45X", TAILJET),
    ("MD8", TAILJET), ("MD9", TAILJET), ("DC9", TAILJET), ("B712", TAILJET), ("B72", TAILJET),
    ("F100", TAILJET), ("F70", TAILJET),
    ("E17", REGIONAL), ("E75", REGIONAL), ("E19", REGIONAL), ("E29", REGIONAL), ("BCS", REGIONAL),
    ("AT4", TURBOPROP), ("AT7", TURBOPROP), ("DH8", TURBOPROP), ("SF34", TURBOPROP), ("E120", TURBOPROP),
    ("B190", TURBOPROP), ("B350", TURBOPROP), ("BE20", TURBOPROP), ("BE30", TURBOPROP), ("BE9", TURBOPROP),
    ("C208", PROP), ("PC12", PROP),
    ("GLF", BIZJET), ("GL", BIZJET), ("GA5C", BIZJET), ("GA6C", BIZJET), ("G280", BIZJET), ("CL3", BIZJET),
    ("CL6", BIZJET), ("C25", BIZJET), ("C5", BIZJET), ("C6", BIZJET), ("C700", BIZJET), ("C750", BIZJET),
    ("E55P", BIZJET), ("E50P", BIZJET), ("E545", BIZJET), ("E550", BIZJET), ("LJ", BIZJET), ("FA", BIZJET),
    ("F2TH", BIZJET), ("F900", BIZJET), ("H25", BIZJET), ("PC24", BIZJET), ("HDJT", BIZJET), ("BE40", BIZJET),
    ("PRM1", BIZJET), ("SF50", BIZJET),
    ("C1", PROP), ("C2", PROP), ("P28", PROP), ("PA", PROP), ("SR2", PROP), ("BE", PROP), ("M20", PROP),
    ("DA4", PROP),
)


def family_for(designator: Optional[str]) -> str:
    """The shape family for an ICAO type designator; unknown or missing types are drawn as a narrowbody."""

    code = (designator or "").strip().upper()
    if code in _FAMILY_EXACT:
        return _FAMILY_EXACT[code]
    for prefix, family in _FAMILY_PREFIXES:
        if code.startswith(prefix):
            return family
    return NARROWBODY


@dataclass(frozen=True)
class _Shape:
    radius: float  # fuselage radius, in fuselage lengths
    fin: float  # fin height above the fuselage top
    nose: float  # length of the nose taper
    tail_cone: float  # length of the upturned tail cone
    engines: str  # "wing", "wing4", "tail", "prop", "none"
    engine_x: float = 0.52  # engine pod centre along the fuselage
    engine_len: float = 0.13
    engine_r: float = 0.85  # pod radius, in fuselage radii
    hump: float = 0.0  # upper-deck length (747)
    decks: int = 1
    t_tail: bool = False
    high_wing: bool = False
    wing_x: float = 0.5
    window: float = 1.0  # window size and spacing (bizjets have few, big ovals)


_SHAPES: dict[str, _Shape] = {
    A380: _Shape(radius=0.06, fin=0.15, nose=0.08, tail_cone=0.2, engines="wing4", engine_x=0.5,
                 engine_len=0.085, engine_r=0.55, decks=2),
    B747: _Shape(radius=0.047, fin=0.15, nose=0.09, tail_cone=0.2, engines="wing4", engine_x=0.5,
                 engine_len=0.08, engine_r=0.7, hump=0.33),
    WIDEBODY: _Shape(radius=0.045, fin=0.16, nose=0.08, tail_cone=0.2, engines="wing", engine_x=0.53,
                     engine_len=0.11, engine_r=0.95),
    NARROWBODY: _Shape(radius=0.05, fin=0.19, nose=0.08, tail_cone=0.21, engines="wing", engine_x=0.55,
                       engine_len=0.12, engine_r=0.75),
    REGIONAL: _Shape(radius=0.052, fin=0.2, nose=0.08, tail_cone=0.22, engines="wing", engine_x=0.55,
                     engine_len=0.12, engine_r=0.72),
    TAILJET: _Shape(radius=0.045, fin=0.2, nose=0.08, tail_cone=0.2, engines="tail", engine_x=0.2,
                    engine_len=0.13, engine_r=0.75, t_tail=True, wing_x=0.55),
    TURBOPROP: _Shape(radius=0.06, fin=0.22, nose=0.07, tail_cone=0.24, engines="prop", engine_x=0.62,
                      engine_len=0.14, engine_r=0.6, t_tail=True, high_wing=True, wing_x=0.55),
    BIZJET: _Shape(radius=0.06, fin=0.22, nose=0.12, tail_cone=0.22, engines="tail", engine_x=0.22,
                   engine_len=0.16, engine_r=0.7, t_tail=True, wing_x=0.55, window=1.8),
    PROP: _Shape(radius=0.09, fin=0.2, nose=0.12, tail_cone=0.38, engines="none", high_wing=True, wing_x=0.62,
                 window=2.2),
}


# ── Drawing ─────────────────────────────────────────────────────────────────


def _bezier(p0, p1, p2, steps: int = 16) -> list[tuple[float, float]]:
    out = []
    for i in range(steps + 1):
        t = i / steps
        a, b, c = (1 - t) ** 2, 2 * (1 - t) * t, t * t
        out.append((a * p0[0] + b * p1[0] + c * p2[0], a * p0[1] + b * p1[1] + c * p2[1]))
    return out


def _fuselage(shape: _Shape) -> list[tuple[float, float]]:
    """Outline in fuselage lengths: x 0 (tail) .. 1 (nose), y down, centreline 0."""

    r = shape.radius
    top = -r
    bottom = r
    tail_top, tail_bottom = -r * 0.7, -r * 0.35
    nose_x = 1 - shape.nose
    points = [(0.0, tail_top), (0.06, top)]
    if shape.hump:
        hump_start = nose_x - shape.hump
        points += [(hump_start - 0.04, top)]
        lift = r * 0.75
        points += _bezier((hump_start - 0.04, top), (hump_start + 0.03, top - lift),
                          (hump_start + 0.12, top - lift))[1:]
        points += _bezier((nose_x - 0.02, top - lift), (1.0, top - lift * 0.7), (1.0, r * 0.1))
    else:
        points += [(nose_x, top)]
        points += _bezier((nose_x, top), (0.995, top * 0.6), (1.0, r * 0.2))[1:]
    points += _bezier((1.0, r * 0.2), (0.995, bottom), (nose_x, bottom))[1:]
    points += [(shape.tail_cone + 0.08, bottom)]
    points += _bezier((shape.tail_cone + 0.08, bottom), (shape.tail_cone * 0.5, bottom * 0.95),
                      (0.0, tail_bottom))[1:]
    return points


def _fin(shape: _Shape) -> list[tuple[float, float]]:
    r, h = shape.radius, shape.fin
    base_front = 0.2 if not shape.t_tail else 0.17
    return [(base_front, -r * 0.9), (0.075, -r - h), (0.015, -r - h), (0.0, -r * 0.7)]


def _stabiliser(shape: _Shape) -> list[tuple[float, float]]:
    r = shape.radius
    if shape.t_tail:
        y = -r - shape.fin
        return [(0.12, y + 0.004), (0.0, y - 0.004), (-0.02, y + 0.012), (0.08, y + 0.016)]
    return [(0.16, -r * 0.15), (0.03, -r * 0.45), (0.0, -r * 0.2), (0.1, r * 0.05)]


def _wing(shape: _Shape) -> list[tuple[float, float]]:
    r, x = shape.radius, shape.wing_x
    if shape.high_wing:
        return [(x + 0.08, -r * 0.95), (x - 0.06, -r * 0.95), (x - 0.08, -r * 0.7), (x + 0.07, -r * 0.7)]
    return [(x + 0.05, r * 0.55), (x - 0.1, r * 0.55), (x - 0.2, r * 0.25), (x - 0.15, r * 0.2)]


def _capsule(x0: float, x1: float, cy: float, ry: float) -> list[tuple[float, float]]:
    """A pod from x0 (exhaust) to x1 (intake), rounded at the intake."""

    pts = [(x0, cy - ry * 0.7), (x1 - ry, cy - ry)]
    pts += _bezier((x1 - ry, cy - ry), (x1 + ry * 0.25, cy - ry), (x1, cy))[1:]
    pts += _bezier((x1, cy), (x1 + ry * 0.25, cy + ry), (x1 - ry, cy + ry))[1:]
    pts += [(x0, cy + ry * 0.7)]
    return pts


def _engines(shape: _Shape) -> list[list[tuple[float, float]]]:
    r = shape.radius
    er = r * shape.engine_r
    pods = []
    if shape.engines == "wing":
        cy = r + er * 0.55
        pods.append(_capsule(shape.engine_x - shape.engine_len / 2, shape.engine_x + shape.engine_len / 2, cy, er))
    elif shape.engines == "wing4":
        for dx, dy in ((0.0, 0.0), (-0.07, -er * 0.25)):
            x = shape.engine_x + dx
            cy = r + er * 0.6 + dy
            pods.append(_capsule(x - shape.engine_len / 2, x + shape.engine_len / 2, cy, er))
    elif shape.engines == "tail":
        x = shape.engine_x
        pods.append(_capsule(x - shape.engine_len / 2, x + shape.engine_len / 2, -r * 0.55, er))
    elif shape.engines == "prop":
        x = shape.engine_x
        pods.append(_capsule(x - shape.engine_len / 2, x + shape.engine_len / 2, -r * 0.75, er))
    return pods


def _scaled(points, scale: float, ox: float, oy: float) -> list[tuple[float, float]]:
    return [(ox + x * scale, oy + y * scale) for x, y in points]


def _bounds(shape: _Shape) -> tuple[float, float, float, float]:
    """(left, top, right, bottom) of the drawing, in fuselage lengths."""

    r = shape.radius
    top = -r - shape.fin - 0.02
    bottom = r + (r * shape.engine_r * 1.6 if shape.engines in ("wing", "wing4") else r * 0.1)
    return -0.03, top, 1.01, bottom


def _mask(size, polygons) -> Image.Image:
    mask = Image.new("L", size, 0)
    draw = ImageDraw.Draw(mask)
    for polygon in polygons:
        draw.polygon(polygon, fill=255)
    return mask


def _fill(canvas: Image.Image, mask: Image.Image, color: Color, clip: Optional[Image.Image] = None) -> None:
    if clip is not None:
        mask = ImageChops.multiply(mask, clip)
    canvas.paste(color + (255,), (0, 0), mask)


def _shade(canvas: Image.Image, mask: Image.Image, top: float, bottom: float) -> None:
    """Light the upper part of *mask* and darken the lower part, so a tube reads as round."""

    height = canvas.height
    light = Image.new("L", (1, height), 0)
    dark = Image.new("L", (1, height), 0)
    span = max(1.0, bottom - top)
    for y in range(height):
        t = min(1.0, max(0.0, (y - top) / span))
        light.putpixel((0, y), round(70 * max(0.0, 1 - t / 0.35) ** 1.5))
        dark.putpixel((0, y), round(95 * max(0.0, (t - 0.45) / 0.55) ** 1.4))
    light = light.resize(canvas.size)
    dark = dark.resize(canvas.size)
    canvas.paste((255, 255, 255, 255), (0, 0), ImageChops.multiply(light, mask))
    canvas.paste((0, 0, 0, 255), (0, 0), ImageChops.multiply(dark, mask))


def _luminance(color: Color) -> float:
    return 0.2126 * color[0] + 0.7152 * color[1] + 0.0722 * color[2]


def _mix(a: Color, b: Color, t: float) -> Color:
    return tuple(round(a[i] + (b[i] - a[i]) * t) for i in range(3))  # type: ignore[return-value]


def livery_for(icao: Optional[str], brand: Optional[Color]) -> Livery:
    livery = LIVERIES.get((icao or "").upper())
    if livery is not None:
        return livery
    if brand is None:
        return Livery(tail=LIGHT_GREY, engines=LIGHT_GREY, logo_on_tail=False)
    return Livery(tail=brand, engines=brand)


def _logo_reads_on(logo: Image.Image, background: Color) -> bool:
    """Whether the logo's own colours stand apart from *background*."""

    small = logo.convert("RGBA").resize((24, 24))
    seen = [px[:3] for px in small.getdata() if px[3] > 128]
    if not seen:
        return False
    average = tuple(sum(c[i] for c in seen) / len(seen) for i in range(3))
    distance = math.sqrt(sum((average[i] - background[i]) ** 2 for i in range(3)))
    return distance > 120


def draw_aircraft(
    width: int,
    *,
    designator: Optional[str],
    airline_icao: Optional[str] = None,
    brand: Optional[Color] = None,
    logo: Optional[Image.Image] = None,
) -> Image.Image:
    """An RGBA side view *width* px wide (height follows the type), nose to the right.

    Raises ValueError for types with no illustration (``family_for`` is NONE).
    """

    family = family_for(designator)
    if family not in _SHAPES:
        raise ValueError(f"no illustration for aircraft type {designator!r}")
    shape = _SHAPES[family]
    livery = livery_for(airline_icao, brand)
    tail_color = livery.tail or brand or LIGHT_GREY
    engine_color = livery.engines or tail_color
    left, top, right, bottom = _bounds(shape)
    scale = width * _SUPERSAMPLE / (right - left)
    size = (width * _SUPERSAMPLE, max(1, round((bottom - top) * scale)))
    ox, oy = -left * scale, -top * scale

    def at(points):
        return _scaled(points, scale, ox, oy)

    canvas = Image.new("RGBA", size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(canvas)
    r = shape.radius

    # Far side first: the far wing and stabiliser peek out in shadow.
    if not shape.high_wing:
        far = [(x + 0.03, y - r * 0.55) for x, y in _wing(shape)]
        draw.polygon(at(far), fill=SHADOW + (255,))
    fuselage = at(_fuselage(shape))
    fuselage_mask = _mask(size, [fuselage])
    fin_mask = _mask(size, [at(_fin(shape))])

    # Fin, painted, with stripes / leading-edge band clipped to it.
    _fill(canvas, fin_mask, tail_color)
    fin_top, fin_bottom = (-r - shape.fin) * scale + oy, -r * 0.7 * scale + oy
    if livery.tail_stripes:
        bands = len(livery.tail_stripes)
        for index, color in enumerate(livery.tail_stripes):
            y0 = fin_top + (fin_bottom - fin_top) * index / bands
            y1 = fin_top + (fin_bottom - fin_top) * (index + 1) / bands
            band = Image.new("L", size, 0)
            ImageDraw.Draw(band).rectangle((0, y0, size[0], y1 + 1), fill=255)
            _fill(canvas, band, color, fin_mask)
    if livery.tail_band:
        band = Image.new("L", size, 0)
        front = _fin(shape)
        lead = [front[0], front[1], (front[1][0] + 0.03, front[1][1]), (front[0][0] + 0.035, front[0][1])]
        ImageDraw.Draw(band).polygon(at(lead), fill=255)
        _fill(canvas, band, livery.tail_band, fin_mask)

    # Fuselage: body, belly, cheatline.
    _fill(canvas, fuselage_mask, livery.body)
    if livery.belly:
        band = Image.new("L", size, 0)
        ImageDraw.Draw(band).rectangle((0, livery.belly_from * r * scale + oy, size[0], size[1]), fill=255)
        _fill(canvas, band, livery.belly, fuselage_mask)
    if livery.cheatline:
        band = Image.new("L", size, 0)
        y = -r * 0.05 * scale + oy
        ImageDraw.Draw(band).rectangle((0, y, size[0], y + r * 0.16 * scale), fill=255)
        _fill(canvas, band, livery.cheatline, fuselage_mask)
    _shade(canvas, fuselage_mask, -r * scale + oy, r * scale + oy)

    # Windows: one row (two on an A380), skipping the tail cone; then the cockpit.
    window_r = r * 0.12 * shape.window * scale
    rows = [-r * 0.32] if shape.decks == 1 else [-r * 0.5, r * 0.05]
    if shape.hump:
        rows.append(-r * 1.4)
    for row, y in enumerate(rows):
        start = shape.tail_cone + 0.03 if not (shape.hump and row == len(rows) - 1) else 1 - shape.nose - shape.hump + 0.08
        end = 1 - shape.nose - 0.02 if not shape.hump or row < len(rows) - 1 else 1 - shape.nose - 0.03
        step = max(r * 0.42, 0.012) * shape.window ** 1.4
        x = start
        while x < end:
            cx, cy = ox + x * scale, oy + y * scale
            draw.ellipse((cx - window_r * 0.8, cy - window_r, cx + window_r * 0.8, cy + window_r), fill=WINDOW + (255,))
            x += step
    nose_x = 1 - shape.nose
    cockpit_y = -r * 0.45 if not shape.hump else -r * 1.35
    cockpit = [(nose_x + shape.nose * 0.35, cockpit_y), (nose_x + shape.nose * 0.62, cockpit_y),
               (nose_x + shape.nose * 0.72, cockpit_y + r * 0.22), (nose_x + shape.nose * 0.38, cockpit_y + r * 0.22)]
    draw.polygon(at(cockpit), fill=WINDOW + (255,))

    # Near wing, stabiliser, engines.
    draw.polygon(at(_stabiliser(shape)), fill=_mix(tail_color, (0, 0, 0), 0.25) + (255,))
    draw.polygon(at(_wing(shape)), fill=WING + (255,))
    for pod in _engines(shape):
        pod_points = at(pod)
        if shape.engines in ("wing", "wing4"):
            xs = [p[0] for p in pod_points]
            mid = (min(xs) + max(xs)) / 2
            pylon_top = oy + r * 0.4 * scale
            pylon = [(mid - (max(xs) - min(xs)) * 0.25, pylon_top), (mid + (max(xs) - min(xs)) * 0.15, pylon_top),
                     (mid + (max(xs) - min(xs)) * 0.1, min(p[1] for p in pod_points) + 2),
                     (mid - (max(xs) - min(xs)) * 0.3, min(p[1] for p in pod_points) + 2)]
            draw.polygon(pylon, fill=WING + (255,))
        draw.polygon(pod_points, fill=engine_color + (255,))
        pod_ys = [p[1] for p in pod_points]
        _shade(canvas, _mask(size, [pod_points]), min(pod_ys), max(pod_ys))
        xs = [p[0] for p in pod_points]
        ys = [p[1] for p in pod_points]
        intake = max(xs)
        draw.ellipse((intake - (max(ys) - min(ys)) * 0.14, min(ys) + 1, intake + (max(ys) - min(ys)) * 0.06,
                      max(ys) - 1), fill=_mix(engine_color, (0, 0, 0), 0.45) + (255,))
        if shape.engines == "prop":
            cy = (min(ys) + max(ys)) / 2
            span = (max(ys) - min(ys)) * 1.8
            draw.ellipse((intake + 1, cy - span, intake + span * 0.08, cy + span), fill=(90, 96, 104, 150))

    # Logo on the fin when it stands out against the paint.
    if logo is not None and livery.logo_on_tail and _logo_reads_on(logo, tail_color):
        fin = at(_fin(shape))
        fin_w = max(p[0] for p in fin) - min(p[0] for p in fin)
        fin_h = max(p[1] for p in fin) - min(p[1] for p in fin)
        box = round(min(fin_w * 0.62, fin_h * 0.55))
        if box > 4:
            mark = logo.convert("RGBA")
            mark.thumbnail((box, box), LANCZOS)
            cx = min(p[0] for p in fin) + fin_w * 0.45
            cy = min(p[1] for p in fin) + fin_h * 0.5
            layer = Image.new("RGBA", size, (0, 0, 0, 0))
            layer.paste(mark, (round(cx - mark.width / 2), round(cy - mark.height / 2)), mark)
            alpha = ImageChops.multiply(layer.getchannel("A"), fin_mask)
            layer.putalpha(alpha)
            canvas.alpha_composite(layer)

    return canvas.resize((width, max(1, round(size[1] / _SUPERSAMPLE))), LANCZOS)


def _siblings(designator: str) -> list[str]:
    for series in _SERIES:
        if designator in series:
            i = series.index(designator)
            return sorted((t for t in series if t != designator), key=lambda t: abs(series.index(t) - i))
    return []


def asset_path(designator: Optional[str], airline_icao: Optional[str], asset_dir: str = ASSET_DIR) -> Optional[str]:
    """The delivered illustration for this airline and type, or None to draw one.

    Order: ``{AIRLINE}/{TYPE}.png``, then a sibling type in the airline's folder, then ``_generic/{TYPE}.png``,
    then a sibling type in ``_generic``.
    """

    code = (designator or "").strip().upper()
    if not re.fullmatch(r"[A-Z0-9]{1,8}", code):
        return None
    airline = (airline_icao or "").strip().upper()
    if not re.fullmatch(r"[A-Z]{3}", airline):
        airline = ""
    types = (code, *_siblings(code))
    candidates = []
    if airline:
        candidates += [os.path.join(asset_dir, airline, f"{t}.png") for t in types]
    candidates += [os.path.join(asset_dir, GENERIC, f"{t}.png") for t in types]
    return next((path for path in candidates if os.path.isfile(path)), None)


@lru_cache(maxsize=32)
def _cached_asset(width: int, path: str, mtime: float) -> Optional[Image.Image]:
    try:
        with Image.open(path) as raw:
            image = raw.convert("RGBA")
    except OSError:
        return None
    # Files carry a small margin; trim it so the aircraft spans the width like the drawn ones.
    bbox = image.getchannel("A").getbbox()
    if bbox is None:
        return None
    image = image.crop(bbox)
    height = max(1, round(image.height * width / image.width))
    return image.resize((width, height), LANCZOS)


@lru_cache(maxsize=32)
def _cached(width: int, designator: str, airline_icao: str, brand: Optional[Color], logo_path: str,
            logo_mtime: float) -> Image.Image:
    logo = None
    if logo_path:
        try:
            with Image.open(logo_path) as raw:
                logo = raw.convert("RGBA")
        except OSError:
            logo = None
    return draw_aircraft(width, designator=designator, airline_icao=airline_icao, brand=brand, logo=logo)


def aircraft_image(width: int, *, designator: Optional[str], airline_icao: Optional[str], brand: Optional[Color],
                   logo_path: Optional[str] = None) -> Optional[Image.Image]:
    """The delivered illustration (see :func:`asset_path`) scaled to *width*, else :func:`draw_aircraft`.

    Cached per size, type, airline and file; None for types with neither a file nor a drawn family.
    """

    path = asset_path(designator, airline_icao, ASSET_DIR)
    if path is not None:
        try:
            asset = _cached_asset(int(width), path, os.path.getmtime(path))
        except OSError:
            asset = None
        if asset is not None:
            return asset
    if family_for(designator) == NONE:
        return None
    mtime = 0.0
    if logo_path:
        try:
            mtime = os.path.getmtime(logo_path)
        except OSError:
            logo_path = None
    return _cached(int(width), (designator or "").upper(), (airline_icao or "").upper(), brand, logo_path or "",
                   mtime)


__all__ = [
    "LIVERIES",
    "Livery",
    "aircraft_image",
    "asset_path",
    "draw_aircraft",
    "family_for",
    "livery_for",
]
