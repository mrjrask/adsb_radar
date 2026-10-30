# ADS-B Radar

A standalone **Raspberry Pi 4 HDMI flight board and animated radar**, designed
for **Raspberry Pi OS Trixie Lite**. It runs straight from the Linux console
with SDL2 KMS/DRM. No desktop, browser kiosk, X11, or Wayland session is needed.

It reads your existing dump1090/readsb/PiAware/tar1090 receiver over the network.
It does **not** require a Desk Display server. The high resolution flight
layout, aircraft illustration fallback, airline directory, and visibility
cone are adapted from [desk_display](https://github.com/mrjrask/desk_display).

## Display

| Profile | Native render and HDMI size | Layout |
| --- | --- | --- |
| `4k` | **3840 × 2160** | Large split-flap route, aircraft illustration, sky map, flight metrics; radar lists up to 10 aircraft. |
| `1080p` | **1920 × 1080** | The full flight layout; radar lists up to 7 aircraft. |
| `848x480` | **848 × 480** | Projector layout with fitted route tiles, artwork, radar, and metrics; readable minimum radar labels and up to 5 nearby flights. |
| `auto` | The connected display's current native HDMI mode | Default; adapts the layout to the detected size. |

These are full-resolution drawings, independent of the 64×64 LED protocol.
Airport codes use shaded split-flap tiles and **Bebas Neue** lettering;
clocks and numerical readouts use **JetBrains Mono**; descriptive text uses
**DejaVu Sans**. The installer installs all three font families through apt.

When a plane enters your flight radius, its airline, type, artwork, route
(when available), altitude, speed, distance, and local traffic appear. With
nothing overhead, choose radar, clock, clear-skies message, blank, or a
rotation of idle views. The radar has a sweep, moving aircraft, trails,
altitude colors, and beacon/strobe lights. Optional visibility cutoffs filter
planes hidden by trees or buildings.

## Install

Start with a network-connected Pi 4 running **Raspberry Pi OS Trixie Lite**
(64-bit recommended), with SSH enabled and the HDMI display attached and on.
Have your receiver's URL and the display's latitude/longitude ready.

```sh
sudo apt-get update
sudo apt-get install -y git
git clone https://github.com/mrjrask/adsb_radar.git
cd adsb_radar
sudo ./install.sh
```

The installer asks for receiver URL(s), location, output resolution, and an
admin password (or generates one). It installs every runtime dependency,
creates an unprivileged service account, installs the app in
`/opt/adsb-radar`, and enables separate display and web services at boot.
It reserves `tty1` for HDMI and records its previous login-console state.
SSH and other virtual consoles stay available. It does not change boot
configuration, the system hostname, Wi-Fi settings, or the default boot target.

Open **`http://<Pi-IP>:8080/`**, using user **`admin`** and the password chosen
or printed during installation. The page changes display settings, resolution,
radar colors/presets, range, idle views, brightness, polling, and the visibility
cone. It also shows a live snapshot and renderer diagnostics. It stays
available if the HDMI process fails. Use this HTTP page on your trusted LAN;
for access across untrusted networks, use an SSH tunnel or a TLS reverse proxy.

For unattended installation, edit a private copy of `config.example.json`
and run `sudo ./install.sh --config /path/to/config.json`. A missing password
is generated. The seed file only applies on first installation. See
[the setup guide](docs/SETUP.md) for configuration, projector mode selection,
troubleshooting, and password resets.

## Upload the artwork manually

**No image assets are bundled or downloaded by this project.** Empty tracked
folders are ready for your uploads:

```text
images/air/DAL.png                    airline logo (ICAO code)
images/aircraft/DAL/B738.png           aircraft in airline livery
images/aircraft/_generic/B738.png      generic type fallback
```

Upload your Desk Display files to the same paths in this repository, then
`git pull` on the Pi and rerun `sudo ./install.sh`. The installer copies the
artwork you supplied into `/var/lib/adsb-radar/images`. Existing local artwork
is preserved during updates. [The asset guide](docs/ASSETS.md) lists the
folders and exact filenames from the source project.

The app works without artwork: it draws airline badges and procedural aircraft
illustrations. Once a type-specific file is supplied, that image takes priority.

## Update and remove

```sh
# Update code/dependencies and install newly uploaded artwork; keep settings.
git pull --ff-only
sudo ./install.sh

# Uninstall the app/services and restore the original tty1 login state.
# Keep credentials, configuration, palettes, cache, and installed artwork.
sudo /opt/adsb-radar/uninstall.sh

# Alternatively, remove those application data files and the service account too.
sudo /opt/adsb-radar/uninstall.sh --purge
```

Both uninstall modes keep the source checkout and shared apt packages.
If you already ran the first command, run `sudo ./uninstall.sh --purge`
from your source checkout for a later purge.

## Data and operation

Receiver polling and optional internet metadata lookups run outside the
render loop. Multiple receivers are deduplicated by aircraft hex ID using
the freshest position. Data older than 30 seconds is discarded. Receiver
outages switch to an offline clock; a recovered receiver restores the board.
The clock follows the Pi's system timezone.

When enabled, a separate worker caches routes from adsbdb and aircraft types
from tar1090-db, so receivers without a `t` field can still select the right
artwork. Internet failures leave the core receiver display working. Missing
or geometrically inconsistent routes are shown as unavailable. No radio/SDR
decoder is installed; supply an existing receiver's HTTP feed.

```sh
systemctl status adsb-radar-display adsb-radar-admin
journalctl -u adsb-radar-display -n 80
journalctl -u adsb-radar-admin -n 80
```

## Development and validation

```sh
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements-dev.txt
# On Debian/Ubuntu, install the same fonts used on the Pi:
sudo apt-get install fonts-dejavu-core fonts-bebas-neue fonts-jetbrains-mono
ruff check .
pytest -q

# Desktop demo, no receiver needed:
python -m adsb_radar.display --windowed --demo flight --resolution 1080p --state-dir .demo-state
python -m adsb_radar.display --windowed --demo radar --resolution 848x480 --state-dir .demo-state
# Synthetic native-resolution previews, without copying original images:
python scripts/render-previews.py /tmp/adsb-radar-previews
```

On macOS/Windows, put the installed font files in a flat directory and set
`ADSB_RADAR_FONT_ROOT` to that directory. See `adsb_radar/fonts.py` for the
filenames. Debian's KMS-enabled pygame package is required for Pi deployment;
desktop PyPI wheels are for development.

GitHub Actions checks Python 3.11/3.13, shell and JavaScript syntax, all three
native render sizes, receiver polling, settings, palettes, authentication,
and offline behavior. Disposable **x86_64 and ARM64 Debian Trixie** jobs run
the real apt installer twice, verify systemd units and permissions, start the
packaged admin, render with SDL's dummy driver, then exercise uninstall and
purge. Hardware HDMI/EDID behavior and sustained frame rate still need a
physical Pi/projector acceptance check; container tests cannot prove those.

See [NOTICE.md](NOTICE.md) for source provenance and font/data attribution.
