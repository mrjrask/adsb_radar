"""Native HDMI profiles and display-mode selection, separate from drawing."""

PROFILES = {"4k": (3840, 2160), "1080p": (1920, 1080), "848x480": (848, 480)}


def open_display(pygame, resolution, windowed=False):
    """Return (screen, native_render_size). Never silently substitute a fixed mode."""
    requested = PROFILES.get(resolution)
    if windowed:
        render_size = requested or PROFILES["1080p"]
        scale = min(1, 1280 / render_size[0], 720 / render_size[1])
        window_size = tuple(round(dimension * scale) for dimension in render_size)
        return pygame.display.set_mode(window_size), render_size
    if requested:
        available = pygame.display.list_modes(flags=pygame.FULLSCREEN)
        if available != -1 and requested not in available:
            raise ValueError(f"HDMI does not advertise {requested[0]}×{requested[1]}; select auto or check EDID/mode settings")
    screen = pygame.display.set_mode(requested or (0, 0), pygame.FULLSCREEN)
    if requested and screen.get_size() != requested:
        raise ValueError("HDMI returned a different mode from the selected resolution")
    return screen, screen.get_size()
