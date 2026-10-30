"""A log of airline logos and aircraft illustrations the display lacked.

When a flight shows a brand-colour badge instead of its airline's logo, or a
drawn aircraft instead of a delivered illustration, this records the file
that would have been used, so the imagery can be sourced and dropped into the
images folder (``ADSB_RADAR_ASSETS``, ``/var/lib/adsb-radar/images`` when
installed):

    air/{AIRLINE}.png                logos (by airline ICAO code)
    aircraft/{AIRLINE}/{TYPE}.png    illustrations (by airline and ICAO type designator)
    aircraft/_generic/{TYPE}.png     illustrations for flights with no airline

The display writes ``missing_imagery.log`` in its state folder; the admin page
links to it. It is tab-separated, one row per missing file however often the
flight is seen, with the first sighting's callsign as an example. Rows whose
file has since been added are dropped when the display starts and when it
re-reads the log (every five minutes, on a new entry), so it
lists only what is still missing. Nothing is logged until :func:`configure`.
"""

from __future__ import annotations

import logging
import os
import re
import threading
import time
from datetime import UTC, datetime
from functools import lru_cache
from pathlib import Path
from typing import Optional

from . import airline_directory

FILENAME = "missing_imagery.log"
LOGO = "airline_logo"
AIRCRAFT = "aircraft_image"
COLUMNS = ("first_seen", "kind", "airline", "airline_name", "type", "type_name", "callsign", "missing_file",
           "showing_instead")
_HEADER = "\t".join(COLUMNS)
_AIRLINE_RE = re.compile(r"^[A-Z]{3}$")
_FILE = COLUMNS.index("missing_file")
LOG = logging.getLogger(__name__)

# How often the log is re-read, so rows for files added while running leave it.
REFRESH_SECONDS = 300.0

_lock = threading.Lock()
_path: Optional[Path] = None
_root: Optional[Path] = None
_seen: Optional[set[str]] = None
_loaded_at = 0.0


def configure(path: Optional[Path], asset_root: Optional[str | Path] = None) -> None:
    """Log to *path* (None turns logging off); files are shown relative to *asset_root*."""

    global _path, _root, _seen
    with _lock:
        _path = Path(path) if path is not None else None
        _root = Path(asset_root).resolve() if asset_root is not None else None
        _seen = None
        _display.cache_clear()
        if _path is not None and _path.is_file():
            _refresh(force=True)  # drop rows for artwork installed since the last run


def asset_root() -> Path:
    """The images folder: ``ADSB_RADAR_ASSETS``, else the checkout's ``images/`` (as the renderer uses)."""

    return Path(os.environ.get("ADSB_RADAR_ASSETS", str(Path(__file__).resolve().parents[1] / "images")))


def log_path() -> Optional[Path]:
    return _path


def _clean(value: Optional[str]) -> str:
    return " ".join(str(value or "").split())


@lru_cache(maxsize=1024)
def _display(path: str) -> str:
    """*path* relative to the images folder when it is inside it (``air/UAL.png``)."""

    if _root is not None:
        try:
            return Path(path).resolve().relative_to(_root).as_posix()
        except ValueError:
            pass
    return str(path)


def _resolve(shown: str, root: Optional[Path]) -> Path:
    path = Path(shown)
    return path if path.is_absolute() or root is None else root / path


def pending(path: Path, asset_root: Optional[str | Path]) -> tuple[list[list[str]], bool]:
    """The rows of the log at *path* whose file is still missing, and whether any were left out."""

    root = Path(asset_root).resolve() if asset_root is not None else None
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return [], False
    rows, dropped = [], False
    for line in lines:
        if line == _HEADER or not line.strip():
            continue
        fields = line.split("\t")
        if len(fields) != len(COLUMNS) or _resolve(fields[_FILE], root).is_file():
            dropped = True
            continue
        rows.append(fields)
    return rows, dropped


def render(rows: list[list[str]]) -> str:
    return "\n".join([_HEADER, *("\t".join(r) for r in rows)]) + "\n"


def _refresh(*, force: bool) -> set[str]:
    """What the log lists, re-read (dropping rows whose file now exists) when stale or *force*d."""

    global _seen, _loaded_at
    if _seen is None or force or time.monotonic() - _loaded_at >= REFRESH_SECONDS:
        try:
            _seen = _load(_path)
        except OSError as error:
            LOG.warning("Cannot read missing imagery log %s: %s", _path, error)
            _seen = set()
        _loaded_at = time.monotonic()
    return _seen


def _load(path: Path) -> set[str]:
    """Missing files already logged, rewriting the log without the ones since added."""

    rows, dropped = pending(path, _root)
    if dropped:
        path.write_text(render(rows), encoding="utf-8")
    return {r[_FILE] for r in rows}


def _record(kind: str, missing_file: str, *, airline: str = "", airline_name: str = "", type_: str = "",
            type_name: str = "", callsign: str = "", showing_instead: str = "") -> bool:
    if _path is None or not missing_file:
        return False
    shown = _display(missing_file)
    with _lock:
        seen = _refresh(force=False)
        if shown in seen:
            return False
        seen.add(shown)
        now = datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S UTC")
        row = [now, kind, airline, airline_name, type_, type_name, callsign, shown, showing_instead]
        try:
            _path.parent.mkdir(parents=True, exist_ok=True)
            new = not _path.is_file() or _path.stat().st_size == 0
            with _path.open("a", encoding="utf-8") as log:
                if new:
                    log.write(_HEADER + "\n")
                log.write("\t".join(_clean(v) for v in row) + "\n")
        except OSError as error:
            LOG.warning("Cannot write missing imagery log %s: %s", _path, error)
            return False
    LOG.info("Missing %s %s (logged to %s)", kind.replace("_", " "), shown, _path)
    return True


def record_logo(airline_icao: Optional[str], directory: str | Path, *, airline_name: str = "",
                callsign: Optional[str] = None, showing_instead: str = "badge") -> bool:
    """Log that airline *airline_icao* has no logo in *directory*; True when this is a new entry."""

    icao = _clean(airline_icao).upper()
    if not _AIRLINE_RE.match(icao) or not directory:  # tail numbers and IATA codes name no logo file
        return False
    if not airline_name:
        airline_name = airline_directory.AIRLINES.get(icao, ("",))[0]
    return _record(LOGO, os.path.join(directory, f"{icao}.png"), airline=icao, airline_name=_clean(airline_name),
                   callsign=_clean(callsign).upper(), showing_instead=showing_instead)


def record_aircraft(designator: Optional[str], airline_icao: Optional[str], asset_dir: str | Path, *,
                    airline_name: str = "", type_name: str = "", callsign: Optional[str] = None,
                    showing_instead: str = "drawn") -> bool:
    """Log that no illustration of *designator* in *airline_icao*'s livery exists; True when new."""

    code = _clean(designator).upper()
    if not code or not asset_dir:
        return False
    airline = _clean(airline_icao).upper()
    return _record(AIRCRAFT, os.path.join(asset_dir, airline or "_generic", f"{code}.png"), airline=airline,
                   airline_name=_clean(airline_name), type_=code, type_name=_clean(type_name),
                   callsign=_clean(callsign).upper(), showing_instead=showing_instead)


__all__ = ["AIRCRAFT", "COLUMNS", "FILENAME", "LOGO", "asset_root", "configure", "log_path", "pending", "record_aircraft",
           "record_logo", "render"]
