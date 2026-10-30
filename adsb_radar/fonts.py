"""Installed aviation-display typography with no runtime font downloads."""

import os
from functools import lru_cache
from pathlib import Path

from PIL import ImageFont

FONT_FILES = {
    "heading": "/usr/share/fonts/opentype/bebas-neue/BebasNeue-Bold.otf",
    "flap": "/usr/share/fonts/opentype/bebas-neue/BebasNeue-Bold.otf",
    "mono": "/usr/share/fonts/truetype/jetbrains-mono/JetBrainsMono-Regular.ttf",
    "mono_bold": "/usr/share/fonts/truetype/jetbrains-mono/JetBrainsMono-Bold.ttf",
    "body": "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "body_bold": "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
}


def font_path(role="body", bold=False):
    key = role + "_bold" if bold and role + "_bold" in FONT_FILES else role
    path = Path(FONT_FILES[key])
    # Optional flat font folder for development on macOS/Windows.
    if os.environ.get("ADSB_RADAR_FONT_ROOT"):
        candidate = Path(os.environ["ADSB_RADAR_FONT_ROOT"]) / path.name
        if candidate.is_file():
            return candidate
    if path.is_file():
        return path
    fallback = Path(os.environ.get("ADSB_RADAR_FONTS", "/usr/share/fonts/truetype/dejavu"))
    candidate = fallback / ("DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf")
    if candidate.is_file():
        return candidate
    raise OSError("Display fonts are missing. Run install.sh, which installs Bebas Neue, JetBrains Mono and DejaVu.")


@lru_cache(maxsize=256)
def load(role, size, bold=False):
    return ImageFont.truetype(str(font_path(role, bold)), max(6, int(size)))
