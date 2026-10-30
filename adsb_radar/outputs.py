"""Where finished frames go: the Linux framebuffer, or an SDL window/KMS screen."""

import logging
import os
import time

from PIL import Image, ImageEnhance

from .video import PROFILES, open_display

LOG = logging.getLogger(__name__)
CHOICES = ("auto", "fbdev", "kms")


def viewport(source, target):
    sw, sh = source
    tw, th = target
    scale = min(tw / sw, th / sh)
    width, height = max(1, round(sw * scale)), max(1, round(sh * scale))
    return (tw - width) // 2, (th - height) // 2, width, height


class FramebufferOutput:
    """Software frames copied to /dev/fb0. Needs no SDL, EGL or GPU driver."""

    errors = (ValueError, OSError)

    def __init__(self, device=None):
        from . import framebuffer

        self.fb = framebuffer.Framebuffer.open(device or os.environ.get("ADSB_RADAR_FBDEV", framebuffer.DEVICE))
        self.name = f"fbdev ({self.fb.name}, {self.fb.bits_per_pixel}bpp)"
        self.size = self.fb.size
        self.fb.take_console()
        self.next_frame = time.monotonic()

    def set_resolution(self, resolution):
        requested = PROFILES.get(resolution)
        if requested and requested != self.size:
            raise ValueError(
                f"The console framebuffer is {self.size[0]}×{self.size[1]}; set "
                f"video=HDMI-A-1:{requested[0]}x{requested[1]}@60 in /boot/firmware/cmdline.txt "
                "and reboot to use that mode, or select auto")
        return self.size

    def present(self, image, rotation=0, level=1.0):
        if level < 1:
            image = ImageEnhance.Brightness(image).enhance(level)
        if rotation:
            image = image.rotate(-rotation, expand=True)
        x, y, width, height = viewport(image.size, self.size)
        if (width, height) != image.size:
            image = image.resize((width, height), Image.BILINEAR)
        if image.size != self.size:
            canvas = Image.new("RGB", self.size)
            canvas.paste(image, (x, y))
            image = canvas
        self.fb.show(image)

    def quit_requested(self):
        return False

    def tick(self, fps):
        self.next_frame = max(self.next_frame + 1 / fps, time.monotonic())
        time.sleep(max(0.0, self.next_frame - time.monotonic()))

    def close(self):
        self.fb.close()


class SdlOutput:
    """An SDL2 KMS/DRM screen on the Pi, or a window for desktop development."""

    def __init__(self, windowed=False):
        if not windowed:
            os.environ.setdefault("SDL_VIDEODRIVER", "KMSDRM")
        import pygame

        self.pygame = pygame
        self.errors = (ValueError, OSError, pygame.error)
        self.windowed = windowed
        pygame.display.init()
        self.screen = None
        self.clock = pygame.time.Clock()

    @property
    def name(self):
        return self.pygame.display.get_driver()

    @property
    def size(self):
        return self.screen.get_size()

    def set_resolution(self, resolution):
        screen, render_size = open_display(self.pygame, resolution, self.windowed)
        self.screen = screen
        self.pygame.mouse.set_visible(False)
        return render_size

    def present(self, image, rotation=0, level=1.0):
        pygame = self.pygame
        surface = pygame.image.fromstring(image.tobytes(), image.size, "RGB")
        if level < 1:
            surface.set_alpha(round(level * 255))
        if rotation:
            surface = pygame.transform.rotate(surface, -rotation)
        x, y, width, height = viewport(surface.get_size(), self.screen.get_size())
        self.screen.fill((0, 0, 0))
        if (width, height) != surface.get_size():
            surface = pygame.transform.smoothscale(surface, (width, height))
        self.screen.blit(surface, (x, y))
        pygame.display.flip()

    def quit_requested(self):
        pygame = self.pygame
        return any(event.type == pygame.QUIT or (event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE)
                   for event in pygame.event.get())

    def tick(self, fps):
        self.clock.tick(fps)

    def close(self):
        self.pygame.quit()


def open_output(choice="auto", windowed=False):
    """Pick the output. auto prefers the framebuffer on the Pi console.

    SDL2's KMS/DRM backend presents frames through EGL/GLES. With some Mesa
    releases it takes over the screen but shows only black, while the plain
    framebuffer keeps working, so the framebuffer is the default when present.
    """
    choice = (choice or "auto").lower()
    if choice not in CHOICES:
        raise ValueError(f"Output must be one of {', '.join(CHOICES)}")
    if windowed or choice == "kms":
        return SdlOutput(windowed)
    device = os.environ.get("ADSB_RADAR_FBDEV", "/dev/fb0")
    if choice == "fbdev":
        return FramebufferOutput(device)
    if os.path.exists(device):
        try:
            return FramebufferOutput(device)
        except (OSError, ValueError) as error:
            LOG.warning("Framebuffer %s unusable (%s); trying SDL KMS/DRM", device, error)
    return SdlOutput(windowed)
