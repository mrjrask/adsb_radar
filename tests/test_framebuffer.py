import io
import json

import pytest
from PIL import Image

from adsb_radar import display, framebuffer, outputs
from adsb_radar.config import DEFAULTS
from adsb_radar.framebuffer import Framebuffer, pack_565


class Device(io.BytesIO):
    """A framebuffer file that keeps its bytes after close()."""

    def close(self):
        self.final = self.getvalue()


def decode_565(data, size):
    pixels = []
    for index in range(0, len(data), 2):
        value = data[index] | data[index + 1] << 8
        r, g, b = value >> 11, value >> 5 & 0x3F, value & 0x1F
        pixels.append((r << 3 | r >> 2, g << 2 | g >> 4, b << 3 | b >> 2))
    image = Image.new("RGB", size)
    image.putdata(pixels)
    return image


@pytest.mark.parametrize("color,expected", [
    ((255, 0, 0), b"\x00\xf8"), ((0, 255, 0), b"\xe0\x07"), ((0, 0, 255), b"\x1f\x00"),
    ((255, 255, 255), b"\xff\xff"), ((0, 0, 0), b"\x00\x00"),
])
def test_rgb565_matches_the_kernel_bitfields(color, expected):
    assert pack_565(Image.new("RGB", (1, 1), color)) == expected


def test_bgr565_swaps_red_and_blue():
    assert pack_565(Image.new("RGB", (1, 1), (255, 0, 0)), red_first=False) == b"\x1f\x00"


@pytest.mark.parametrize("red_offset,expected", [(16, b"\x00\x00\xff"), (0, b"\xff\x00\x00")])
def test_32bpp_byte_order_follows_red_offset(red_offset, expected):
    fb = Framebuffer(Device(), 1, 1, 32, 4, red_offset)
    fb.show(Image.new("RGB", (1, 1), (255, 0, 0)))
    # The fourth (padding) byte is ignored by the display hardware.
    assert fb.stream.getvalue()[:3] == expected and len(fb.stream.getvalue()) == 4


def test_padded_rows_respect_the_stride():
    fb = Framebuffer(Device(), 2, 2, 16, 8, 11)
    fb.show(Image.new("RGB", (2, 2), (255, 0, 0)))
    row = b"\x00\xf8" * 2 + b"\0" * 4
    assert fb.stream.getvalue() == row * 2


def test_unsupported_depth_and_wrong_frame_size_are_rejected():
    with pytest.raises(ValueError, match="depth"):
        Framebuffer(Device(), 2, 2, 8, 2, 0)
    fb = Framebuffer(Device(), 2, 2, 16, 4, 11)
    with pytest.raises(ValueError, match="Frame is"):
        fb.show(Image.new("RGB", (3, 2)))


@pytest.fixture
def fake_fb(monkeypatch):
    devices = []

    def fake_open(cls, path=framebuffer.DEVICE):
        fb = cls(Device(), 848, 480, 16, 848 * 2, 11, name="vc4drmfb")
        devices.append(fb)
        return fb

    monkeypatch.setattr(Framebuffer, "open", classmethod(fake_open))
    monkeypatch.setattr(Framebuffer, "take_console", lambda self: False)
    return devices


def test_fixed_profile_that_is_not_the_console_mode_explains_the_fix(fake_fb):
    out = outputs.FramebufferOutput("/dev/fb0")
    assert out.set_resolution("auto") == out.set_resolution("848x480") == (848, 480)
    with pytest.raises(ValueError, match="video=HDMI-A-1:1920x1080@60"):
        out.set_resolution("1080p")


def test_rotated_frames_are_letterboxed_on_the_framebuffer(fake_fb):
    out = outputs.FramebufferOutput("/dev/fb0")
    frame = Image.new("RGB", (848, 480), (255, 255, 255))
    out.present(frame, rotation=90)
    shown = decode_565(out.fb.stream.getvalue(), (848, 480))
    x, _y, width, _height = outputs.viewport((480, 848), (848, 480))
    assert shown.getpixel((x - 1, 240)) == (0, 0, 0)
    assert shown.getpixel((x + width // 2, 240)) == (255, 255, 255)


def test_brightness_dims_framebuffer_frames(fake_fb):
    out = outputs.FramebufferOutput("/dev/fb0")
    out.present(Image.new("RGB", (848, 480), (200, 200, 200)), level=0.5)
    assert decode_565(out.fb.stream.getvalue()[:2], (1, 1)).getpixel((0, 0))[1] == pytest.approx(100, abs=4)


def test_auto_output_prefers_an_existing_framebuffer(fake_fb, monkeypatch, tmp_path):
    device = tmp_path / "fb0"
    device.touch()
    monkeypatch.setenv("ADSB_RADAR_FBDEV", str(device))
    assert isinstance(outputs.open_output("auto"), outputs.FramebufferOutput)
    with pytest.raises(ValueError):
        outputs.open_output("vga")


@pytest.mark.parametrize("mode", ["flight", "radar"])
def test_demo_frames_reach_the_framebuffer(fake_fb, tmp_path, mode):
    config = {**DEFAULTS, "LATITUDE": 41.88, "LONGITUDE": -87.63}
    display.run(config, tmp_path, demo=mode, frames=2, output="fbdev")
    status = json.loads((tmp_path / "status.json").read_text())
    assert status["state"] == "stopped" and status["driver"].startswith("fbdev (vc4drmfb, 16bpp)")
    assert status["hdmi_size"] == status["render_size"] == [848, 480]
    fb = fake_fb[0]
    # The device is cleared on shutdown, so inspect the last frame written before close.
    assert fb.stream.final == b"\0" * (848 * 2 * 480)


def test_last_demo_frame_is_not_black(fake_fb, tmp_path, monkeypatch):
    frames = []
    original = Framebuffer.show

    def capture(self, image):
        frames.append(image.copy())
        original(self, image)

    monkeypatch.setattr(Framebuffer, "show", capture)
    config = {**DEFAULTS, "LATITUDE": 41.88, "LONGITUDE": -87.63}
    display.run(config, tmp_path, demo="radar", frames=2, output="fbdev")
    shown = decode_565(pack_565(frames[-1]), (848, 480))
    assert shown.getbbox() is not None
    shown.save(tmp_path / "fb.png")
