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
from .scene import Scene
from .video import PROFILES, open_display

LOG = logging.getLogger(__name__)


def viewport(source, target):
    sw, sh = source
    tw, th = target
    scale = min(tw / sw, th / sh)
    width, height = max(1, round(sw * scale)), max(1, round(sh * scale))
    return (tw - width) // 2, (th - height) // 2, width, height


def run(config, state, *, windowed=False, demo=None, frames=None):
    os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")
    if not windowed:
        os.environ.setdefault("SDL_VIDEODRIVER", "KMSDRM")
    import pygame

    pygame.display.init()
    resolution = config["RESOLUTION"]
    resolution_error = None
    try:
        screen, render_size = open_display(pygame, resolution, windowed)
    except (ValueError, pygame.error) as error:
        resolution_error = str(error)
        LOG.warning("%s; using the native HDMI mode", error)
        screen, render_size = open_display(pygame, "auto", windowed)
    pygame.mouse.set_visible(False)
    LOG.info("HDMI driver=%s size=%s", pygame.display.get_driver(), screen.get_size())
    scene = Scene(render_size)
    clock = pygame.time.Clock()
    began = time.monotonic()
    settings, aircraft, online = config, (), False
    metadata = None if demo else Metadata(state)
    worker = None if demo else MetadataWorker(metadata, config)
    poller = None if demo else Poller(config, state)
    stats = {"version": __version__, "polls": 0, "failures": 0, "healthy_receivers": 0,
             "driver": pygame.display.get_driver(), "hdmi_size": list(screen.get_size()),
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
            for event in pygame.event.get():
                if event.type == pygame.QUIT or (event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE):
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
                            screen, render_size = open_display(pygame, resolution, windowed)
                            scene = Scene(render_size)
                            stats.update(hdmi_size=list(screen.get_size()), render_size=list(render_size))
                            stats.pop("resolution_error", None)
                        except (ValueError, pygame.error) as error:
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
                        aircraft = result["aircraft"]
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
            image = scene.render(aircraft, settings, metadata, online=online, now=now,
                                 health="Demo receiver" if demo else f'{stats["healthy_receivers"]}/{len(config["RECEIVER_URLS"])} receivers online')
            surface = pygame.image.fromstring(image.tobytes(), image.size, "RGB")
            level = settings.get("BRIGHTNESS") or 1.0
            if level < 1:
                surface.set_alpha(round(level * 255))
            if config["ROTATION"]:
                surface = pygame.transform.rotate(surface, -config["ROTATION"])
            x, y, width, height = viewport(surface.get_size(), screen.get_size())
            screen.fill((0, 0, 0))
            if (width, height) != surface.get_size():
                surface = pygame.transform.smoothscale(surface, (width, height))
            screen.blit(surface, (x, y))
            pygame.display.flip()
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
            clock.tick(config["FPS"])
    finally:
        for thread in (poller, worker):
            if thread:
                thread.stopping.set()
                thread.join(timeout=1)
        stats.update(state="stopped", heartbeat=time.time())
        write_json(Path(state) / "status.json", stats)
        pygame.quit()
        for sig, handler in old_handlers.items():
            signal.signal(sig, handler)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=CONFIG_PATH)
    parser.add_argument("--state-dir", type=Path, default=STATE_PATH)
    parser.add_argument("--windowed", action="store_true", help="desktop development only")
    parser.add_argument("--demo", choices=("flight", "radar"), help="generated demo; no receiver or images needed")
    parser.add_argument("--resolution", choices=("auto", *PROFILES), help="override the configured output profile")
    parser.add_argument("--frames", type=int, help="exit after N frames for smoke testing")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    config = {**DEFAULTS, "LATITUDE": 41.88, "LONGITUDE": -87.63} if args.demo else load_config(args.config)
    if args.resolution:
        config["RESOLUTION"] = args.resolution
    try:
        run(config, args.state_dir, windowed=args.windowed, demo=args.demo, frames=args.frames)
    except Exception:
        LOG.exception("Display stopped. Check KMS/HDMI, device permissions and tty1 in docs/SETUP.md.")
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
