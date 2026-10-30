"""Linux framebuffer (/dev/fb0) output that does not depend on SDL, EGL or the GPU.

The radar is already drawn in software with Pillow, so the only job here is to
copy each finished frame into the console framebuffer in its pixel format.
This works wherever the text console is visible, including systems where the
SDL2 KMS/DRM backend opens the display but its GLES presentation stays black.
"""

import fcntl
import logging
import os
import struct
import sys

from PIL import Image, ImageChops

LOG = logging.getLogger(__name__)

DEVICE = "/dev/fb0"
FBIOGET_VSCREENINFO = 0x4600
FBIOGET_FSCREENINFO = 0x4602
KDSETMODE = 0x4B3A
KD_TEXT, KD_GRAPHICS = 0, 1
# struct fb_var_screeninfo: xres, yres, xres_virtual, yres_virtual, xoffset,
# yoffset, bits_per_pixel, grayscale, then red/green/blue bitfields.
VAR_FORMAT = "8I3I3I3I"
# struct fb_fix_screeninfo up to line_length, with native alignment.
FIX_FORMAT = "@16sL4I3HI"


def _lut(function):
    return [function(value) for value in range(256)]


# Lookup tables turn an 8-bit channel into its RGB565 bit fields.
HIGH_RED = _lut(lambda v: v & 0xF8)
HIGH_GREEN = _lut(lambda v: v >> 5)
LOW_GREEN = _lut(lambda v: (v & 0x1C) << 3)
LOW_BLUE = _lut(lambda v: v >> 3)


def pack_565(image, red_first=True):
    """Return little-endian 16-bit pixels; red in the top bits unless red_first is False."""
    red, green, blue = image.convert("RGB").split()
    if not red_first:
        red, blue = blue, red
    # The fields never overlap, so a saturating add is a bitwise OR.
    high = ImageChops.add(red.point(HIGH_RED), green.point(HIGH_GREEN))
    low = ImageChops.add(green.point(LOW_GREEN), blue.point(LOW_BLUE))
    return Image.merge("LA", (low, high)).tobytes()


class Framebuffer:
    """Write Pillow images to a framebuffer device of known geometry."""

    def __init__(self, stream, width, height, bits_per_pixel, stride, red_offset, name="fbdev"):
        if bits_per_pixel not in (16, 24, 32):
            raise ValueError(f"Unsupported framebuffer depth: {bits_per_pixel} bits per pixel")
        self.stream = stream
        self.size = (width, height)
        self.bits_per_pixel = bits_per_pixel
        self.stride = stride
        self.red_offset = red_offset
        self.name = name
        self.row_bytes = width * bits_per_pixel // 8
        if stride < self.row_bytes:
            raise ValueError("Framebuffer stride is smaller than one row of pixels")
        self.console = None

    @classmethod
    def open(cls, path=DEVICE):
        stream = open(path, "r+b", buffering=0)
        try:
            var = bytearray(160)
            fcntl.ioctl(stream.fileno(), FBIOGET_VSCREENINFO, var)
            fields = struct.unpack_from(VAR_FORMAT, var)
            width, height, bits, red_offset = fields[0], fields[1], fields[6], fields[8]
            fix = bytearray(128)
            fcntl.ioctl(stream.fileno(), FBIOGET_FSCREENINFO, fix)
            name, *_rest, stride = struct.unpack_from(FIX_FORMAT, fix)
            label = name.split(b"\0", 1)[0].decode(errors="replace") or "fbdev"
            return cls(stream, width, height, bits, stride, red_offset, name=label)
        except Exception:
            stream.close()
            raise

    def pixels(self, image):
        if image.size != self.size:
            raise ValueError(f"Frame is {image.size}, framebuffer is {self.size}")
        if self.bits_per_pixel == 16:
            return pack_565(image, red_first=self.red_offset != 0)
        if self.bits_per_pixel == 24:
            return image.convert("RGB").tobytes("raw", "BGR" if self.red_offset else "RGB")
        return image.convert("RGB").tobytes("raw", "BGRX" if self.red_offset else "RGBX")

    def show(self, image):
        data = self.pixels(image)
        if self.stride != self.row_bytes:
            padding = b"\0" * (self.stride - self.row_bytes)
            data = b"".join(data[row:row + self.row_bytes] + padding
                            for row in range(0, len(data), self.row_bytes))
        self.stream.seek(0)
        self.stream.write(data)

    def take_console(self):
        """Stop the text console (and its blinking cursor) drawing over the frames."""
        for candidate in (sys.stdin, None):
            try:
                if candidate is None:
                    fd = os.open("/dev/tty", os.O_RDWR | os.O_NOCTTY)
                elif candidate.isatty():
                    fd = os.dup(candidate.fileno())
                else:
                    continue
            except (OSError, ValueError, AttributeError):
                continue
            try:
                # Only a real virtual console accepts KDSETMODE; never touch
                # an SSH or desktop terminal.
                fcntl.ioctl(fd, KDSETMODE, KD_GRAPHICS)
                os.write(fd, b"\033[?25l")
                self.console = fd
                return True
            except OSError as error:
                LOG.debug("Console graphics mode unavailable: %s", error)
                os.close(fd)
        LOG.info("Not on a virtual console; the text cursor may show over the display")
        return False

    def close(self):
        # Never leave a frozen flight board behind; returning the console to
        # text mode then lets it redraw itself over the cleared screen.
        try:
            self.stream.seek(0)
            self.stream.write(b"\0" * (self.stride * self.size[1]))
        except OSError:
            pass
        if self.console is not None:
            try:
                fcntl.ioctl(self.console, KDSETMODE, KD_TEXT)
                os.write(self.console, b"\033[?25h")
            except OSError:
                pass
            os.close(self.console)
            self.console = None
        self.stream.close()
