"""Native-resolution radar animation and the Desk Display flight layout."""

import math
import time
from datetime import datetime

from PIL import Image, ImageDraw

from . import airline_directory, flight_layout, fonts
from .forms import RADAR_COLOR_DEFAULTS
from .models import advance
from .sky_cone import Cone


def select_flight(aircraft, settings, metadata, keep=None):
    radius = settings["RADIUS"]
    cone = None
    if settings.get("MIN_ELEVATION") is not None or settings.get("HORIZON"):
        cone = Cone(settings.get("MIN_ELEVATION") or 0, tuple((settings.get("HORIZON") or {}).items()),
                    settings.get("HOME_ELEVATION_FT") or 0, settings.get("MAX_RANGE"), keep)
    eligible = [a for a in aircraft if a.distance <= radius and
                (cone is None or cone.sees(a, radius=radius, unit=settings["DISTANCE_UNIT"]))]
    if not eligible:
        return None
    plane = min(eligible, key=lambda a: cone.rank(a, settings["DISTANCE_UNIT"]) if cone else a.distance)
    route = metadata.route(plane) if metadata else None
    code = route.airline_icao if route and route.airline_icao else airline_directory.airline_code(plane.callsign)
    airline = airline_directory.airline_for(code, name=route.airline_name if route else "",
                                          iata=route.airline_iata if route else "")
    return flight_layout.OverheadFlight(plane, route, airline, len(eligible), tuple(aircraft))


def rgb(text):
    return tuple(int(text[i:i + 2], 16) for i in (1, 3, 5))


class Scene:
    def __init__(self, size):
        self.size = size
        self.background_key = None
        self.background = None
        self.flight_key = None
        self.flight_image = None
        self.keep = None

    def text(self, draw, position, text, size, color=(225, 235, 240), bold=False, anchor=None, role=None):
        # Projector labels stay at least 12px high rather than shrinking in
        # proportion to the 4K/1080p designs.
        size = max(16, round(size))
        draw.text(position, text, font=fonts.load(role or ("heading" if bold else "body"), size, bold),
                  fill=color, anchor=anchor)

    def radar(self, aircraft, settings, now, health):
        width, height = self.size
        scale = min(width / 1920, height / 1080)
        colors = {key: rgb(settings.get(key) or value) for key, value in RADAR_COLOR_DEFAULTS.items()}
        radius = settings["RADIUS"]
        reach = max(radius, settings.get("RADAR_RANGE") or radius * 4)
        unit = settings["DISTANCE_UNIT"]
        side = min(height * 0.86, width * 0.57)
        cx, cy, outer = width * 0.30, height * 0.51, side / 2
        key = (self.size, tuple(colors.items()), radius, reach, unit)
        if key != self.background_key:
            self.background_key = key
            background = Image.new("RGB", self.size, colors["RADAR_BACKGROUND"])
            draw = ImageDraw.Draw(background)
            self.text(draw, (40 * scale, 24 * scale), "ADS-B RADAR", 36 * scale,
                      colors["RADAR_COUNT"], bold=True)
            for factor in (0.25, 0.5, 0.75, 1):
                r = outer * factor
                draw.ellipse((cx - r, cy - r, cx + r, cy + r),
                             outline=colors["RADAR_RING" if factor == 1 else "RADAR_RING_DIM"], width=max(1, round(2 * scale)))
            r = outer * radius / reach
            draw.ellipse((cx - r, cy - r, cx + r, cy + r), outline=colors["RADAR_HOME_RING"], width=max(1, round(2 * scale)))
            draw.line((cx - outer, cy, cx + outer, cy), fill=colors["RADAR_RING_DIM"])
            draw.line((cx, cy - outer, cx, cy + outer), fill=colors["RADAR_RING_DIM"])
            draw.ellipse((cx - 4 * scale, cy - 4 * scale, cx + 4 * scale, cy + 4 * scale), fill=colors["RADAR_NORTH"])
            self.text(draw, (cx, cy - outer - 12 * scale), "N", 28 * scale, colors["RADAR_NORTH"], anchor="mb")
            self.text(draw, (cx, cy + outer + 16 * scale), f"{reach:g} {unit}", 28 * scale,
                      colors["RADAR_RANGE_COLOR"], anchor="mt")
            self.background = background
        image = self.background.copy()
        draw = ImageDraw.Draw(image)
        if settings.get("RADAR_SWEEP", True) is not False:
            angle = now % 3.6 / 3.6 * math.tau
            sweep, base = colors["RADAR_SWEEP_COLOR"], colors["RADAR_BACKGROUND"]
            for step in range(32, -1, -1):
                theta = angle - step * 0.014
                amount = (1 - step / 34) * 0.7
                color = tuple(round(base[i] * (1 - amount) + sweep[i] * amount) for i in range(3))
                draw.line((cx, cy, cx + math.sin(theta) * outer, cy - math.cos(theta) * outer),
                          fill=color, width=max(1, round(2 * scale)))
        moving = settings.get("RADAR_MOTION", True) is not False
        planes = [advance(a, now, unit=unit) if moving else a for a in aircraft]
        planes = sorted((a for a in planes if a.distance <= reach), key=lambda a: a.distance)
        for plane in reversed(planes):
            r, b = plane.distance / reach * outer, math.radians(plane.bearing)
            x, y = cx + r * math.sin(b), cy - r * math.cos(b)
            altitude = plane.altitude_ft or 0
            band = next((i for i, ceiling in enumerate((4000, 10000, 20000, 30000), 1) if altitude < ceiling), 5)
            color = colors[f"RADAR_ALT_{band}"]
            heading = math.radians(plane.track or 0)
            trail = settings.get("RADAR_TRAIL")
            trail = 6 if trail is None else trail
            if trail:
                end = x - math.sin(heading) * trail * 4 * scale, y + math.cos(heading) * trail * 4 * scale
                draw.line((x, y, *end), fill=tuple(c // 3 for c in color), width=max(1, round(2 * scale)))
            draw.polygon(flight_layout._plane_points(x, y, max(5, 22 * scale), plane.track or 0), fill=color)
            if settings.get("RADAR_LIGHTS", True) is not False:
                phase = (now + int(plane.hex.lstrip("~"), 16) % 31 / 31) % 1.6
                light = (255, 70, 70) if phase < 0.1 else (255, 255, 255) if 0.5 < phase < 0.56 or 0.65 < phase < 0.71 else None
                if light:
                    dot = max(1, round(2 * scale))
                    draw.ellipse((x - dot, y - dot, x + dot, y + dot), fill=light)
        left = width * 0.62
        self.text(draw, (left, height * 0.08), datetime.fromtimestamp(now).strftime(
            "%H:%M:%S" if settings.get("CLOCK_24H") else "%I:%M:%S %p").lstrip("0"), 58 * scale, colors["RADAR_COUNT"], role="mono")
        self.text(draw, (left, height * 0.17), f"{len(planes)} aircraft · {reach:g} {unit}", 27 * scale, colors["RADAR_COUNT"])
        self.text(draw, (left, height * 0.23), health, 20 * scale, (160, 180, 175))
        rows = 5 if height <= 600 else 7 if height <= 1080 else 10
        for index, plane in enumerate(planes[:rows]):
            spacing = height * 0.48 / rows
            y = height * 0.32 + index * spacing
            self.text(draw, (left, y), plane.callsign or plane.hex.upper(), 25 * scale, bold=True)
            self.text(draw, (left, y + max(16, 30 * scale)),
                      f"{plane.altitude_ft:,} ft · {plane.distance:.1f} {unit}" if plane.altitude_ft is not None
                      else f"Altitude unknown · {plane.distance:.1f} {unit}", 19 * scale, (150, 165, 175), role="mono")
        for index, label in enumerate(("<4k", "4–10k", "10–20k", "20–30k", "30k+ ft"), 1):
            self.text(draw, (left + ((index - 1) % 3) * 160 * scale,
                             height * 0.82 + ((index - 1) // 3) * 40 * scale), label, 19 * scale,
                      colors[f"RADAR_ALT_{index}"])
        return image

    def render(self, aircraft, settings, metadata=None, *, online=True, now=None, health="Receivers online"):
        now = time.time() if now is None else now
        home = settings["LATITUDE"], settings["LONGITUDE"]
        # Age out old positions even if a poll is delayed or the receiver goes away.
        aircraft = tuple(a for a in aircraft if now - a.seen_at <= 30)
        flight = select_flight(aircraft, settings, metadata, self.keep) if online else None
        self.keep = flight.aircraft.hex if flight else None
        if flight:
            key = (flight, home, settings["DISTANCE_UNIT"], settings["RADIUS"], settings["RADAR_RANGE"])
            if key != self.flight_key:
                self.flight_key = key
                self.flight_image = flight_layout.compose_overhead_image(
                    flight, width=self.size[0], height=self.size[1], home=home,
                    unit=settings["DISTANCE_UNIT"], radius=settings["RADIUS"], radar_range=settings["RADAR_RANGE"])
            return self.flight_image
        modes = (settings.get("IDLE") or "radar").split(",")
        mode = modes[int(now // (settings.get("IDLE_SECONDS") or 30)) % len(modes)]
        if not online:
            mode = "clock"
        if mode == "radar":
            return self.radar(aircraft, settings, now, health)
        image = Image.new("RGB", self.size)
        draw = ImageDraw.Draw(image)
        width, height = self.size
        if mode == "blank":
            return image
        if mode == "clock":
            stamp = datetime.fromtimestamp(now)
            self.text(draw, (width / 2, height * 0.42), stamp.strftime(
                "%H:%M" if settings.get("CLOCK_24H") else "%I:%M %p").lstrip("0"), height * 0.16, anchor="mm", role="mono")
            self.text(draw, (width / 2, height * 0.58), stamp.strftime("%A, %B %d"), height * 0.045, anchor="mm")
            self.text(draw, (width / 2, height * 0.72), "Receiver offline — retrying" if not online else "Clear skies overhead",
                      height * 0.03, color=(220, 155, 90) if not online else (150, 170, 185), anchor="mm")
        else:
            self.text(draw, (width / 2, height * 0.45), "Clear skies overhead", height * 0.075, anchor="mm")
            self.text(draw, (width / 2, height * 0.58), f'No aircraft in view within {settings["RADIUS"]:g} {settings["DISTANCE_UNIT"]}',
                      height * 0.035, anchor="mm")
        return image
