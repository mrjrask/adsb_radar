from types import SimpleNamespace

import pytest

from adsb_radar import fonts
from adsb_radar.video import PROFILES, open_display


@pytest.mark.parametrize("profile", PROFILES)
def test_native_mode_selection(profile):
    selected = []

    def set_mode(size, flags=0):
        selected.append((size, flags))
        return SimpleNamespace(get_size=lambda: size)

    pygame = SimpleNamespace(FULLSCREEN=1, display=SimpleNamespace(
        list_modes=lambda **_kw: list(PROFILES.values()), set_mode=set_mode))
    screen, render_size = open_display(pygame, profile)
    assert render_size == PROFILES[profile] == screen.get_size()
    assert selected == [(PROFILES[profile], 1)]


def test_unadvertised_projector_mode_does_not_replace_working_screen():
    pygame = SimpleNamespace(FULLSCREEN=1, display=SimpleNamespace(list_modes=lambda **_kw: [(1920, 1080)]))
    with pytest.raises(ValueError, match="does not advertise"):
        open_display(pygame, "848x480")


def test_display_font_families_are_loaded():
    # These packages are installed by install.sh and the Linux CI job.
    assert "Bebas" in fonts.load("flap", 50).getname()[0]
    assert "JetBrains" in fonts.load("mono", 50).getname()[0]
    assert fonts.load("body", 50).getname()[0]
