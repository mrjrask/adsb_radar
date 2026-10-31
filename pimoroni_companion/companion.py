"""Three-screen flight deck. Hardware imports are deferred for desktop tests."""

import argparse
import json
import logging
import math
import signal
import threading
import time
from datetime import datetime
from functools import lru_cache
from pathlib import Path

from PIL import Image, ImageDraw, ImageEnhance, ImageFont

LOG = logging.getLogger(__name__)


@lru_cache(maxsize=24)
def font(size):
    try:
        return ImageFont.truetype("DejaVuSansMono.ttf", size)
    except OSError:
        return ImageFont.load_default(size=size)


def label(draw, xy, value, size=12, color="white", anchor=None):
    text = str(value)
    while size > 8 and draw.textlength(text, font=font(size)) > (220 if anchor else 118):
        size -= 1
    draw.text(xy, text, font=font(size), fill=color, anchor=anchor)


def live_snapshot(data, now):
    """Discard stopped HDMI, offline receiver and individually stale positions."""
    if not 0 <= now - data.get("heartbeat", 0) <= 5 or not data.get("online"):
        return {"online": False, "aircraft": [], "unit": data.get("unit", "nm")}
    return {**data, "aircraft": [a for a in data.get("aircraft", [])
                                if 0 <= now - a["seen_at"] <= 30]}


def render(data, now):
    data = live_snapshot(data, now)
    planes = data.get("aircraft", [])
    target = next((a for a in planes if a["hex"] == data.get("selected")), None)
    left, lcd, right = Image.new("1", (128, 128)), Image.new("RGB", (240, 240)), Image.new("1", (128, 128))
    ld, cd, rd = ImageDraw.Draw(left), ImageDraw.Draw(lcd), ImageDraw.Draw(right)
    # Two-pixel slow movement reduces persistent OLED wear without scrolling text.
    shift = int(now // 30) % 3
    label(ld, (5 + shift, 4), "FLIGHT DECK", 12)
    label(rd, (5 + shift, 4), "TELEMETRY", 12)
    for draw in (ld, rd):
        draw.line((5, 23, 121, 23), fill="white")
    if target:
        label(ld, (5 + shift, 31), target.get("callsign") or target["hex"].upper(), 20)
        label(ld, (5 + shift, 60), target.get("aircraft_type") or "TYPE --", 17)
        label(ld, (5 + shift, 86), f'{target["distance"]:.1f} {data["unit"]}', 17)
        label(ld, (5 + shift, 110), f'BRG {target["bearing"]:03.0f} deg', 11)
        alt, speed, rate = (target.get(k) for k in ("altitude_ft", "ground_speed_kt", "vertical_rate_fpm"))
        label(rd, (5 + shift, 30), f'{alt:,} FT' if alt is not None else "ALT --", 18)
        label(rd, (5 + shift, 59), f'{speed:.0f} KT' if speed is not None else "SPD --", 20)
        label(rd, (5 + shift, 89), f'{rate:+,} FPM' if rate is not None else "V/S --", 12)
        # Altitude tape: 0-40,000 feet.
        rd.rectangle((5, 115, 121, 121), outline="white")
        rd.rectangle((6, 116, 6 + int(114 * min(1, max(0, (alt or 0) / 40000))), 120), fill="white")
    else:
        label(ld, (5 + shift, 35), "SCANNING" if data.get("online") else "NO SIGNAL", 17)
        label(ld, (5 + shift, 67), f"{len(planes)} TRACKS", 16)
        label(ld, (5 + shift, 105), "HDMI COMPANION", 10)
        label(rd, (5 + shift, 36), datetime.fromtimestamp(now).strftime("%H:%M:%S"), 20)
        label(rd, (5 + shift, 75), "AIRSPACE LIVE" if data.get("online") else "CHECK HDMI", 12)
        label(rd, (5 + shift, 104), "NORTH UP", 12)
    green, dim, amber = "#53ffb2", "#164936", "#ffcf65"
    label(cd, (120, 3), "LOCAL AIRSPACE", 14, green, "mt")
    cx, cy, radius = 120, 122, 89
    for r in (30, 60, 89):
        cd.ellipse((cx-r, cy-r, cx+r, cy+r), outline=dim)
    cd.line((31, cy, 209, cy), fill=dim)
    cd.line((cx, 33, cx, 211), fill=dim)
    label(cd, (120, 20), "N", 10, green, "mt")
    if data.get("online"):
        sweep = now * math.tau / 8
        cd.line((cx, cy, cx + radius * math.sin(sweep), cy - radius * math.cos(sweep)), fill=green)
        reach = max(0.1, data.get("range", 12))
        for plane in planes:
            distance, bearing = plane.get("distance"), plane.get("bearing")
            if distance is None or bearing is None or distance > reach:
                continue
            angle = math.radians(bearing)
            x, y = cx + radius * distance / reach * math.sin(angle), cy - radius * distance / reach * math.cos(angle)
            selected = plane["hex"] == data.get("selected")
            cd.ellipse((x-3, y-3, x+3, y+3), fill=amber if selected else green)
            if selected:
                cd.rectangle((x-6, y-6, x+6, y+6), outline=amber)
        footer = f'{reach:g} {data["unit"]} | {len(planes)} TRACKS'
    else:
        label(cd, (120, 116), "AWAITING HDMI", 15, amber, "mm")
        footer = "FEED UNAVAILABLE"
    cd.polygon(((120, 117), (116, 127), (124, 127)), fill="white")
    label(cd, (120, 223), footer, 12, green, "mt")
    return left, lcd, right


class Hardware:
    def __init__(self, config):
        import st7789
        from luma.core.interface.serial import i2c
        from luma.oled.device import sh1107

        self.oleds = []
        self.lcd = None
        try:
            for side in ("left", "right"):
                self.oleds.append(sh1107(i2c(port=1, address=int(config[f"{side}_address"], 0)),
                                          width=128, height=128, rotate=config[f"{side}_rotation"]))
            self.lcd = st7789.ST7789(port=0, cs=1, dc=9, backlight=19,
                                     width=240, height=240, rotation=config["lcd_rotation"],
                                     spi_speed_hz=40_000_000)
            self.lcd.begin()
        except Exception:
            self.close()
            raise

    def present(self, images, level):
        left, lcd, right = images
        for device, image in zip(self.oleds, (left, right), strict=True):
            device.contrast(round(255 * level))
            device.display(image)
        self.lcd.display(ImageEnhance.Brightness(lcd).enhance(level))

    def close(self):
        for device in self.oleds:
            try:
                device.cleanup()
            except Exception:
                LOG.exception("OLED cleanup failed")
        if self.lcd:
            try:
                self.lcd.display(Image.new("RGB", (240, 240)))
            except Exception:
                LOG.exception("LCD cleanup failed")
            finally:
                try:
                    self.lcd.set_backlight(0)
                except Exception:
                    LOG.exception("LCD backlight cleanup failed")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=Path("/etc/adsb-radar/companion.json"))
    parser.add_argument("--snapshot", type=Path, default=Path("/var/lib/adsb-radar/companion.json"))
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO)
    config = json.loads(args.config.read_text())
    if {int(config[k], 0) for k in ("left_address", "right_address")} != {0x3c, 0x3d}:
        parser.error("OLED addresses must be distinct: 0x3c and 0x3d")
    if any(config[k] not in range(4) for k in ("left_rotation", "right_rotation")):
        parser.error("OLED rotations must be 0, 1, 2 or 3")
    if config["lcd_rotation"] not in (0, 90, 180, 270):
        parser.error("LCD rotation must be 0, 90, 180 or 270")
    stopping = threading.Event()
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, lambda *_: stopping.set())
    hardware = Hardware(config)
    try:
        while not stopping.is_set():
            started = time.monotonic()
            try:
                data = json.loads(args.snapshot.read_text())
            except (OSError, ValueError):
                data = {}
            images = render(data, time.time())
            level = max(0.01, min(1, data.get("brightness", 0.4)))
            hardware.present(images, level)
            stopping.wait(max(0.01, 0.5 - (time.monotonic() - started)))
    finally:
        hardware.close()


if __name__ == "__main__":
    main()
