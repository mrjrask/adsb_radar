"""Native-resolution radar animation, idle screens and the flight board."""

import time
from datetime import datetime

from PIL import Image, ImageDraw

from . import airline_directory, flight_layout, fonts, radar
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
    airline, codeshares = airlines_for(plane, route)
    return flight_layout.OverheadFlight(plane, route, airline, len(eligible), tuple(aircraft), codeshares)


def airlines_for(plane, route):
    """The operating airline, and (airline, callsign) for each codeshare the flight is sold as."""

    code = route.airline_icao if route and route.airline_icao else airline_directory.airline_code(plane.callsign)
    airline = airline_directory.airline_for(code, name=route.airline_name if route else "",
                                          iata=route.airline_iata if route else "")
    codeshares = tuple((airline_directory.airline_for(c[:3]), c) for c in (route.codeshares if route else ()))
    return airline, codeshares


class Scene:
    def __init__(self, size):
        self.size = size
        self.background_key = None
        self.background = None
        self.flight_key = None
        self.flight_image = None
        self.keep = None
        self.flight_box = None
        self.headers = self.header_box = None
        self.routes = {}
        self.list_key = self.list_image = self.list_box = None
        self.panels = {}

    def text(self, draw, position, text, size, color=(225, 235, 240), bold=False, anchor=None, role=None):
        # Projector labels stay at least 12px high rather than shrinking in
        # proportion to the 4K/1080p designs.
        size = max(16, round(size))
        draw.text(position, text, font=fonts.load(role or ("heading" if bold else "body"), size, bold),
                  fill=color, anchor=anchor)

    def route(self, plane, metadata, now):
        """The cached route for *plane*; the database is read at most every few seconds per callsign."""

        if metadata is None or not plane.callsign:
            return None
        hit = self.routes.get(plane.callsign)
        if hit is None or now - hit[0] > 10:
            if len(self.routes) > 300:
                self.routes.clear()
            hit = self.routes[plane.callsign] = (now, metadata.route(plane))
        return hit[1]

    def altitude_key(self, image, left, top, width, colors, scale):
        """A segmented altitude bar with the band boundaries marked underneath."""

        draw = ImageDraw.Draw(image)
        muted = (150, 165, 175)
        self.text(draw, (left, top), "ALTITUDE (FT)", 17 * scale, muted)
        bar_top = top + max(22, 34 * scale)
        bar_h = max(6, round(12 * scale))
        gap = max(2, round(4 * scale))
        segment = (width - gap * 4) / 5
        for index in range(5):
            x0 = left + index * (segment + gap)
            draw.rounded_rectangle((x0, bar_top, x0 + segment, bar_top + bar_h), radius=bar_h / 2,
                                   fill=colors[f"RADAR_ALT_{index + 1}"])
        for index, label in enumerate(("4k", "10k", "20k", "30k"), 1):
            x = left + index * (segment + gap) - gap / 2
            self.text(draw, (x, bar_top + bar_h + max(4, 6 * scale)), label, 17 * scale, muted, anchor="mt",
                      role="mono")

    def radar(self, aircraft, settings, now, metadata=None):
        width, height = self.size
        scale = min(width / 1920, height / 1080)
        colors = radar.colors_for(settings)
        radius = settings["RADIUS"]
        reach = max(radius, settings.get("RADAR_RANGE") or radius * 4)
        unit = settings["DISTANCE_UNIT"]
        side = min(height * 0.86, width * 0.57)
        cx, cy, outer = width * 0.30, height * 0.51, side / 2
        line = max(1, 2 * scale)
        key = (self.size, tuple(colors.items()), radius, reach, unit)
        if key != self.background_key:
            self.background_key = key
            background = Image.new("RGB", self.size, colors["RADAR_BACKGROUND"])
            draw = ImageDraw.Draw(background)
            self.text(draw, (40 * scale, 24 * scale), "ADS-B RADAR", 36 * scale,
                      colors["RADAR_COUNT"], bold=True)
            radar.draw_scope(background, cx, cy, outer, colors, radius=radius, reach=reach, line=line)
            self.text(draw, (cx, cy - outer - 12 * scale), "N", 28 * scale, colors["RADAR_NORTH"], anchor="mb")
            self.text(draw, (cx, cy + outer + 16 * scale), f"{reach:g} {unit}", 28 * scale,
                      colors["RADAR_RANGE_COLOR"], anchor="mt")
            left = width * 0.62
            self.altitude_key(background, left, height * 0.83,
                              min(width - 40 * scale - left, max(280, 460 * scale)), colors, scale)
            self.background = background
        image = self.background.copy()
        draw = ImageDraw.Draw(image)
        if settings.get("RADAR_SWEEP", True) is not False:
            radar.draw_sweep(image, cx, cy, outer, now, colors, line)
        radar.draw_home(image, cx, cy, colors, 4 * scale)
        planes = radar.in_motion(aircraft, settings, now, unit)
        planes = sorted((a for a in planes if a.distance is not None and a.distance <= reach), key=lambda a: a.distance)
        radar.draw_traffic(image, planes, cx=cx, cy=cy, outer=outer, reach=reach, colors=colors, settings=settings,
                           now=now, icon=max(18, 30 * scale), trail_step=4 * scale)
        left = width * 0.62
        self.text(draw, (left, height * 0.08), datetime.fromtimestamp(now).strftime(
            "%H:%M:%S" if settings.get("CLOCK_24H") else "%I:%M:%S %p").lstrip("0"), 58 * scale, colors["RADAR_COUNT"], role="mono")
        rows = 5 if height <= 600 else 7 if height <= 1080 else 10
        listed = []
        for plane in planes[:rows]:
            route = self.route(plane, metadata, now)
            airline, codeshares = airlines_for(plane, route)
            listed.append((((airline, plane.callsign or plane.hex.upper()),) + codeshares,
                           (plane.aircraft_type or "").strip().upper(), radar.altitude_color(colors, plane.altitude_ft),
                           f"{route.origin.code} → {route.destination.code}" if route and route.origin and route.destination
                           else "",
                           f"{plane.altitude_ft:,} ft · {plane.distance:.1f} {unit}" if plane.altitude_ft is not None
                           else f"Altitude unknown · {plane.distance:.1f} {unit}"))
        # Text is the slow part of a frame, so the list is redrawn only when a line changes
        # (or a codeshare flight moves on to its next airline).
        key = (self.background_key, len(planes), tuple(listed))
        if key != self.list_key:
            self.list_key, self.panels = key, {}
            self.list_box = (round(left), round(height * 0.15), width, round(height * 0.81))

        def panel(step):
            if step not in self.panels:
                if len(self.panels) > 6:
                    self.panels.clear()
                image = self.background.crop(self.list_box)
                self.aircraft_list(image, -self.list_box[0], -self.list_box[1], listed, len(planes), reach, unit,
                                   colors, scale, step)
                self.panels[step] = image
            return self.panels[step]

        step, fade = flight_layout.codeshare_phase(now)
        if all(len(row[0]) == 1 for row in listed):
            step, fade = 0, 0.0
        self.list_image = flight_layout.crossfade(panel(step), panel(None) if fade else None, panel(step + 1)
                                                  if fade else None, fade)
        image.paste(self.list_image, self.list_box[:2])
        return image

    def aircraft_list(self, image, dx, dy, listed, count, reach, unit, colors, scale, step=0):
        """The aircraft count and the nearest flights (logo, callsign, route, type, altitude and distance).

        A codeshare flight shows its airline ``step % count``; with *step* None its logo and
        callsign are left out (the midpoint of a fade). The type and route stay put either way.
        """

        width, height = self.size
        draw = ImageDraw.Draw(image)
        left = width * 0.62 + dx
        self.text(draw, (left, height * 0.17 + dy), f"{count} aircraft · {reach:g} {unit}", 27 * scale,
                  colors["RADAR_COUNT"])
        rows = 5 if height <= 600 else 7 if height <= 1080 else 10
        spacing = height * 0.53 / rows
        tile = round(spacing * 0.78)
        name_size = max(16, round(25 * scale))
        gap = max(8, 14 * scale)
        for index, (brands, aircraft_type, band, route, detail) in enumerate(listed):
            y = height * 0.26 + index * spacing + dy
            x = left + tile + max(8, 14 * scale)
            name_font = fonts.load("heading", max(16, name_size), True)
            if step is not None or len(brands) == 1:
                airline, name = brands[(step or 0) % len(brands)]
                badge = flight_layout.logo_tile(airline, tile, name)
                image.paste(badge, (round(left), round(y)), badge)
                self.text(draw, (x, y), name, name_size, bold=True)
            # After the widest of the flight's numbers, so nothing moves as they change.
            after = x + max(draw.textlength(name, font=name_font) for _airline, name in brands) + gap
            if aircraft_type:
                _left, cap_top, _right, cap_bottom = draw.textbbox((x, y), "H", font=name_font)
                after = self.type_badge(draw, after, (cap_top + cap_bottom) / 2, aircraft_type, band, name_size) + gap
            if route:
                self.text(draw, (after, y + name_size * 0.1), route, 21 * scale, colors["RADAR_COUNT"])
            self.text(draw, (x, y + max(18, 32 * scale)), detail, 19 * scale, (150, 165, 175), role="mono")

    def type_badge(self, draw, left, middle, code, color, height):
        """The ICAO type designator (B738, A21N) in a pill of the plane's altitude colour; returns its right edge."""

        font = fonts.load("mono_bold", max(16, round(height * 0.72)))
        pad = max(5, round(height * 0.3))
        right = left + draw.textlength(code, font=font) + pad * 2
        half = max(10, height * 0.5)
        draw.rounded_rectangle((left, middle - half, right, middle + half), radius=half, fill=color)
        draw.text(((left + right) / 2, middle), code, font=font, fill=flight_layout._contrast_text(color), anchor="mm")
        return right

    def render(self, aircraft, settings, metadata=None, *, online=True, now=None):
        now = time.time() if now is None else now
        home = settings["LATITUDE"], settings["LONGITUDE"]
        # Age out old positions even if a poll is delayed or the receiver goes away.
        aircraft = tuple(a for a in aircraft if now - a.seen_at <= 30)
        flight = select_flight(aircraft, settings, metadata, self.keep) if online else None
        self.keep = flight.aircraft.hex if flight else None
        if flight:
            colors = radar.colors_for(settings)
            key = (flight, home, settings["DISTANCE_UNIT"], settings["RADIUS"], settings["RADAR_RANGE"],
                   tuple(colors.items()))
            if key != self.flight_key:
                self.flight_key = key
                # The board is drawn once per update; the sky map's sweep, planes and lights every frame.
                self.flight_image = flight_layout.compose_overhead_image(
                    flight, width=self.size[0], height=self.size[1], home=home,
                    unit=settings["DISTANCE_UNIT"], radius=settings["RADIUS"], radar_range=settings["RADAR_RANGE"],
                    settings=settings, traffic=False)
                self.flight_box = flight_layout.radar_box(*self.size)
                self.headers, self.header_box = {}, flight_layout.header_box(*self.size)
            brands = len(flight_layout.identities(flight))
            step, fade = flight_layout.codeshare_phase(now)
            if self.flight_box is None and brands == 1:
                return self.flight_image
            image = self.flight_image.copy()
            if brands > 1:
                def header(brand):
                    if brand not in self.headers:
                        self.headers[brand] = flight_layout.compose_header(flight, *self.size, brand)
                    return self.headers[brand]

                shown = flight_layout.crossfade(header(step % brands), header(None) if fade else None,
                                                header((step + 1) % brands) if fade else None, fade)
                image.paste(shown, self.header_box[:2])
            if self.flight_box is None:
                return image
            flight_layout.draw_sky_traffic(image, self.flight_box, flight, settings, now,
                                           radius=settings["RADIUS"], unit=settings["DISTANCE_UNIT"],
                                           reach=settings["RADAR_RANGE"])
            return image
        modes = (settings.get("IDLE") or "radar").split(",")
        mode = modes[int(now // (settings.get("IDLE_SECONDS") or 30)) % len(modes)]
        if not online:
            mode = "clock"
        if mode == "radar":
            return self.radar(aircraft, settings, now, metadata)
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
