"""Validated JSON configuration and atomic, process-safe local storage."""

import json
import math
import os
import tempfile
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

from .forms import FIELDS, SECTORS

CONFIG_PATH = Path(os.environ.get("ADSB_RADAR_CONFIG", "/etc/adsb-radar/config.json"))
STATE_PATH = Path(os.environ.get("ADSB_RADAR_STATE", "/var/lib/adsb-radar"))
DEFAULTS = {
    "RECEIVER_URLS": [], "LATITUDE": None, "LONGITUDE": None,
    "ADMIN_USERNAME": "admin", "ADMIN_PASSWORD_HASH": "",
    "SECRET_KEY": "", "ADMIN_BIND": "0.0.0.0", "ADMIN_PORT": 8080,
    "POLL_SECONDS": 5, "FPS": 15, "ROTATION": 0, "RESOLUTION": "auto",
    "BRIGHTNESS": 1.0, "CLOCK_24H": False, "DISTANCE_UNIT": "nm",
    "RADIUS": 3, "RADAR_RANGE": 12, "IDLE": "radar", "IDLE_SECONDS": 30,
    "ROUTE_LOOKUP": True, "TYPE_LOOKUP": True,
}


def tar1090_address(address):
    """Accept a host:port or map address; retain the instance path and port.

    Viewport queries/fragments and index.html belong to the map UI, not the
    aircraft feed. Receiver discovers data/aircraft.json below this base.
    """
    address = address.strip()
    if not address:
        raise ValueError("Enter the tar1090 hostname or map address")
    if "://" not in address:
        address = "http://" + address
    url = urlsplit(address)
    if (url.scheme not in ("http", "https") or not url.hostname or url.username or url.password
            or any(ord(c) <= 32 for c in address)):
        raise ValueError("Use a tar1090 http(s) address without credentials or spaces")
    # Accessing port validates malformed/non-numeric/out-of-range port values.
    _port = url.port
    path = url.path.rstrip("/")
    if path.rsplit("/", 1)[-1] in ("index.html", "index.htm"):
        path = path.rsplit("/", 1)[0]
    return urlunsplit((url.scheme, url.netloc, path, "", ""))


def read_json(path, default=None):
    try:
        with Path(path).open(encoding="utf-8") as stream:
            value = json.load(stream)
    except FileNotFoundError:
        return {} if default is None else default
    if not isinstance(value, dict):
        raise ValueError(f"{path}: expected a JSON object")
    return value


def atomic_bytes(path, data, mode=0o640):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix="." + path.name + "-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            os.fchmod(stream.fileno(), mode)
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def write_json(path, value):
    atomic_bytes(path, (json.dumps(value, indent=2, allow_nan=False) + "\n").encode())


def check_settings(values):
    unknown = set(values) - set(FIELDS)
    if unknown:
        raise ValueError("Unknown display settings: " + ", ".join(sorted(unknown)))
    for key, value in values.items():
        if value is None:
            continue
        _key, _label, kind, spec, _help = FIELDS[key]
        valid = False
        if kind == "number":
            valid = (type(value) in (int, float) and math.isfinite(value) and spec[0] <= value <= spec[1])
        elif kind == "choice":
            valid = any(type(value) is type(stored) and value == stored for _v, _l, stored in spec)
        elif kind == "hex":
            valid = (isinstance(value, str) and len(value) == 7 and value[0] == "#"
                     and all(c in "0123456789abcdefABCDEF" for c in value[1:]))
        elif kind == "brightness":
            valid = type(value) in (int, float) and math.isfinite(value) and 0.001 <= value <= 1
        elif kind == "idles":
            valid = isinstance(value, str) and all(v in {s[0] for s in spec} - {"default"}
                                                  for v in value.split(","))
        elif kind == "horizon":
            valid = isinstance(value, dict) and all(
                k in SECTORS and type(v) in (int, float) and math.isfinite(v) and 0 <= v <= 89
                for k, v in value.items())
        if not valid:
            raise ValueError(f"Invalid value for {key}")
    if (values.get("LATITUDE") is None) != (values.get("LONGITUDE") is None):
        raise ValueError("Set both LATITUDE and LONGITUDE, or neither")
    return values


def load_config(path=CONFIG_PATH):
    if not Path(path).is_file():
        raise ValueError(f"Configuration missing: {path}; run install.sh first")
    raw = read_json(path)
    unknown = set(raw) - set(DEFAULTS) - set(FIELDS)
    if unknown:
        raise ValueError("Unknown configuration keys: " + ", ".join(sorted(unknown)))
    result = {**DEFAULTS, **raw}
    check_settings({k: v for k, v in result.items() if k in FIELDS})
    urls = result["RECEIVER_URLS"]
    if not isinstance(urls, list) or not 1 <= len(urls) <= 8:
        raise ValueError("RECEIVER_URLS must contain 1-8 receiver URLs")
    for value in urls:
        if not isinstance(value, str):
            raise ValueError("Receiver URLs must be strings")
        url = urlsplit(value)
        if (url.scheme not in ("http", "https") or not url.hostname or url.username or url.password
                or url.query or url.fragment or any(ord(c) < 32 for c in value)):
            raise ValueError("Receiver URLs must use http(s), without credentials, query or fragment")
    if result["LATITUDE"] is None or result["LONGITUDE"] is None:
        raise ValueError("Set LATITUDE and LONGITUDE to your display location")
    for key in ("SECRET_KEY", "ADMIN_USERNAME", "ADMIN_PASSWORD_HASH", "ADMIN_BIND"):
        if not isinstance(result[key], str) or not result[key] or any(ord(c) < 32 for c in result[key]):
            raise ValueError(f"{key} must be a nonempty string without control characters")
    if len(result["SECRET_KEY"]) < 32:
        raise ValueError("SECRET_KEY must contain at least 32 characters")
    if not result["ADMIN_PASSWORD_HASH"].startswith(("scrypt:", "pbkdf2:")):
        raise ValueError("ADMIN_PASSWORD_HASH must be a Werkzeug password hash")
    for key, low, high in (("ADMIN_PORT", 1024, 65535), ("FPS", 5, 60)):
        if type(result[key]) is not int or not low <= result[key] <= high:
            raise ValueError(f"{key} must be an integer from {low} to {high}")
    if result["DISTANCE_UNIT"] not in ("nm", "mi", "km"):
        raise ValueError("DISTANCE_UNIT must be nm, mi or km")
    if result["RESOLUTION"] not in ("auto", "4k", "1080p", "848x480"):
        raise ValueError("RESOLUTION must be auto, 4k, 1080p or 848x480")
    for key in ("ROUTE_LOOKUP", "TYPE_LOOKUP"):
        if type(result[key]) is not bool:
            raise ValueError(f"{key} must be true or false")
    if type(result["ROTATION"]) is not int or result["ROTATION"] not in (0, 90, 180, 270):
        raise ValueError("ROTATION must be 0, 90, 180 or 270")
    return result


def display_settings(config, state=STATE_PATH):
    saved = check_settings(read_json(Path(state) / "settings.json"))
    combined = {**config, **saved}
    check_settings({k: v for k, v in combined.items() if k in FIELDS})
    for key in ("LATITUDE", "LONGITUDE", "BRIGHTNESS", "POLL_SECONDS", "CLOCK_24H", "RADIUS", "RADAR_RANGE", "IDLE", "IDLE_SECONDS", "RESOLUTION"):
        if combined.get(key) is None:
            combined[key] = config.get(key) if config.get(key) is not None else DEFAULTS[key]
    return combined
