"""High resolution HDMI flight board and radar, directly from a Linux console."""

import argparse
import io
import logging
import os
import queue
import signal
import time
from pathlib import Path

from PIL import ImageEnhance

from . import __version__
from .config import CONFIG_PATH, DEFAULTS, STATE_PATH, atomic_bytes, display_settings, load_config, write_json
from .feed import Poller
from .metadata import Metadata, MetadataWorker
from .models import LiveAircraft
from .outputs import CHOICES, open_output, viewport  # noqa: F401  (viewport is re-exported)
from .scene import Scene
from .video import PROFILES

LOG = logging.getLogger(__name__)


def run(config, state, *, windowed=False, demo=None, frames=None, output=None):
    os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")
    out = open_output(output or os.environ.get("ADSB_RADAR_OUTPUT", "auto"), windowed)
    errors = out.errors
    resolution = config["RESOLUTION"]
    resolution_error = None
    try:
        render_size = out.set_resolution(resolution)
    except errors as error:
        resolution_error = str(error)
        LOG.warning("%s; using the native HDMI mode", error)
        render_size = out.set_resolution("auto")
    LOG.info("HDMI driver=%s size=%s", out.name, out.size)
    scene = Scene(render_size)
    began = time.monotonic()
    settings, aircraft, online = config, (), False
    metadata = None if demo else Metadata(state)
    worker = None if demo else MetadataWorker(metadata, config)
    poller = None if demo else Poller(config, state)
    stats = {"version": __version__, "polls": 0, "failures": 0, "healthy_receivers": 0,
             "driver": out.name, "hdmi_size": list(out.size),
             "render_size": list(scene.size), "state": "waiting"}
    if resolution_error:
        stats["resolution_error"] = resolution_error
    stopping = False

    def stop(_signum, _stack):
        nonlocal stopping
        stopping = True

    old_handlers = {sig: signal.signal(sig, stop) for sig in (signal.SIGTERM, signal.SIGINT)}
    for thread in (poller, worker):
        if thread:
            thread.start()
    next_snapshot = next_settings = next_metadata = 0
    count = 0
    try:
        while not stopping:
            now, monotonic = time.time(), time.monotonic()
            if out.quit_requested():
                stopping = True
            if monotonic >= next_settings:
                try:
                    settings = display_settings(config, state)
                    stats.pop("settings_error", None)
                    if settings["RESOLUTION"] != resolution:
                        # Keep the admin available and retain the working output if a
                        # projector/monitor does not advertise the requested mode.
                        resolution = settings["RESOLUTION"]
                        try:
                            render_size = out.set_resolution(resolution)
                            scene = Scene(render_size)
                            stats.update(hdmi_size=list(out.size), render_size=list(render_size))
                            stats.pop("resolution_error", None)
                        except errors as error:
                            stats["resolution_error"] = str(error)
                            LOG.warning("Resolution change failed: %s", error)
                except (OSError, ValueError):
                    stats["settings_error"] = "Invalid saved settings; retaining the last valid configuration"
                next_settings = monotonic + 0.5
            if demo:
                online = True
                stats["healthy_receivers"] = 1
                distance = 1.5 if demo == "flight" else settings["RADIUS"] + 2
                aircraft = (LiveAircraft("a12345", "DAL123", "B738", settings["LATITUDE"], settings["LONGITUDE"],
                                         6500, 65, 230, -500, now, "demo", distance, 45),)
            if poller:
                try:
                    result = poller.results.get_nowait()
                except queue.Empty:
                    result = None
                if result:
                    stats.update({k: v for k, v in result.items() if k != "aircraft"})
                    stats["polls"] += 1
                    if result["healthy_receivers"]:
                        # Look up cached types before this poll is drawn, so the flight board never
                        # shows the generic aircraft for a frame while the type is still unknown.
                        aircraft = metadata.enrich(result["aircraft"])
                        next_metadata = monotonic + 1
                        stats["last_success"] = now
                        online = True
                        worker.submit(aircraft)
                    elif result["failures"] >= 2 or not aircraft:
                        online = False
            # A stalled poll must never leave a stale flight board on screen.
            if not demo and now - stats.get("last_success", 0) > max(30, settings["POLL_SECONDS"] * 2 + 10):
                online = False
            if metadata and monotonic >= next_metadata:
                aircraft = metadata.enrich(aircraft)
                next_metadata = monotonic + 1
            image = scene.render(aircraft, settings, metadata, online=online, now=now)
            level = settings.get("BRIGHTNESS") or 1.0
            out.present(image, config["ROTATION"], level)
            if monotonic >= next_snapshot:
                stats.update(state="demo" if demo else "online" if online else "offline",
                             heartbeat=now, uptime_seconds=int(monotonic - began), brightness=level,
                             effective={k: settings.get(k) for k in ("RADAR_RANGE", "RADIUS", "MIN_ELEVATION",
                                        "HORIZON", "HOME_ELEVATION_FT", "MAX_RANGE")})
                stats["effective"]["RADAR_RANGE"] = max(settings["RADIUS"], settings["RADAR_RANGE"])
                stats["effective"]["unit"] = settings["DISTANCE_UNIT"]
                write_json(Path(state) / "status.json", stats)
                preview = ImageEnhance.Brightness(image).enhance(level) if level < 1 else image.copy()
                preview.thumbnail((960, 540))
                output = io.BytesIO()
                preview.save(output, format="PNG")
                atomic_bytes(Path(state) / "preview.png", output.getvalue())
                next_snapshot = monotonic + 1
            count += 1
            if frames and count >= frames:
                stopping = True
            out.tick(config["FPS"])
    finally:
        for thread in (poller, worker):
            if thread:
                thread.stopping.set()
                thread.join(timeout=1)
        stats.update(state="stopped", heartbeat=time.time())
        write_json(Path(state) / "status.json", stats)
        out.close()
        for sig, handler in old_handlers.items():
            signal.signal(sig, handler)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=CONFIG_PATH)
    parser.add_argument("--state-dir", type=Path, default=STATE_PATH)
    parser.add_argument("--windowed", action="store_true", help="desktop development only")
    parser.add_argument("--demo", choices=("flight", "radar"), help="generated demo; no receiver or images needed")
    parser.add_argument("--resolution", choices=("auto", *PROFILES), help="override the configured output profile")
    parser.add_argument("--output", choices=CHOICES,
                        help="fbdev writes /dev/fb0; kms uses SDL2 KMS/DRM; auto (default) prefers fbdev. "
                             "Also settable with ADSB_RADAR_OUTPUT")
    parser.add_argument("--frames", type=int, help="exit after N frames for smoke testing")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    config = {**DEFAULTS, "LATITUDE": 41.88, "LONGITUDE": -87.63} if args.demo else load_config(args.config)
    if args.resolution:
        config["RESOLUTION"] = args.resolution
    try:
        run(config, args.state_dir, windowed=args.windowed, demo=args.demo, frames=args.frames, output=args.output)
    except Exception:
        LOG.exception("Display stopped. Check HDMI, /dev/fb0 or KMS device permissions and tty1 in docs/SETUP.md.")
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
