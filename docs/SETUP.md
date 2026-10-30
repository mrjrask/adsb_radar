# Raspberry Pi setup and operation

## Before installing

Use Raspberry Pi OS **Trixie Lite** on a Pi 4. Configure networking, SSH,
the correct timezone, and time synchronization through Raspberry Pi Imager
or the normal OS tools. Plug the monitor/projector into HDMI0 (the micro-HDMI
port closest to USB-C power) and turn it on before booting.

The OS needs the stock `vc4-kms-v3d` graphics driver. The installer does not
add a desktop or change `/boot/firmware/config.txt` or `cmdline.txt`.
If you started from a desktop image, switch to console boot with
`sudo raspi-config` and reboot before installation.

The Pi must reach a source of current aircraft positions. For a combined
**tar1090** instance on another computer (such as a CM5 combining two PiAware
receivers), choose `tar1090` in the installer and enter its normal map address.
A host/IP plus port, such as `192.0.2.10:8080`, is also accepted. Keep the port
and any custom instance path; the app reads the aircraft feed below that map.
The example IP is a placeholder: use the address you open in your browser.

For individual receivers, choose `receivers` instead.
Supply either a base URL (`http://192.168.1.50`) or the complete URL of
`aircraft.json`. The client tries these paths for a base URL, then remembers
the working one:

1. `/data/aircraft.json`
2. `/tar1090/data/aircraft.json`
3. `/skyaware/data/aircraft.json`
4. `/dump1090-fa/data/aircraft.json`

A combined source is one entry in `RECEIVER_URLS` and contains all the traffic
from its upstream receivers. Do not also list the individual PiAware sources
unless you intentionally want to poll them too. The app labels endpoint
counts as feeds, rather than pretending it can see upstream receiver health.

One through eight feed endpoints can be configured. A partial endpoint outage
does not stop another endpoint's data from being displayed.

## Installation choices

Run the commands in the README. Dependencies come from apt, including
`python3-pygame`, Pillow, Flask, Requests, Gunicorn, SDL2/DRM/Mesa, KMS support
libraries, and the **Bebas Neue, JetBrains Mono, and DejaVu** fonts. There is
no pip installation into the OS-managed Python environment. SDL2's `kmsdrm`
backend is only needed for the optional KMS output (see *Output* below).

`sudo ./install.sh --no-start` stages/enables the services without taking
over tty1 during installation. Before starting them, run:

```sh
sudo systemctl disable --now getty@tty1
sudo systemctl start adsb-radar-admin adsb-radar-display
```

A normal install/update keeps `/etc/adsb-radar/config.json`, web settings, custom
palettes, cached metadata, and existing installed images. It installs the
current checkout; fetch changes with `git pull --ff-only` before updating.

## Switch an existing display to the combined feed

After pulling the latest code, run:

```sh
sudo ./install.sh --tar1090 '192.0.2.10:8080'
```

Replace the example with your combined tar1090 map address. This explicitly
replaces `RECEIVER_URLS` with one entry and restarts the services. It preserves
credentials, session key, location, web settings, and installed images.
It does not change the CM5 or the PiAware receivers.

You can also update just the installed configuration:

```sh
sudo python3 /opt/adsb-radar/scripts/configure.py /etc/adsb-radar/config.json --tar1090 '192.0.2.10:8080'
sudo systemctl restart adsb-radar-display adsb-radar-admin
```

The configuration helper preserves the existing file owner/group so the
service account can still read its private configuration. Direct JSON edits
remain supported: `"RECEIVER_URLS": ["http://192.0.2.10:8080"]` selects the same
combined source.

## Native resolution

Choose **HDMI output → Output resolution** on the admin page:

| Value | HDMI mode and native rendering |
| --- | --- |
| `auto` | Use the display's current native HDMI size. |
| `4k` | 3840×2160 UHD. |
| `1080p` | 1920×1080. |
| `848x480` | 848×480 projector. |

The installer also asks for the initial profile. Text, split-flap tiles,
aircraft artwork, rings, and planes are drawn at that size. The radar list
shows 10, 7, or 5 nearby aircraft on 4K, 1080p, or projector layouts. Projector
radar labels use fonts no smaller than 16px.

The physical device must advertise the selected mode through HDMI/EDID.
A projector's native imaging resolution and its accepted HDMI input modes
can differ. If a fixed mode is unavailable, the app reports a resolution
error in the admin diagnostics. Startup falls back to automatic mode; a
rejected live change keeps the working output.

To inspect advertised modes and connector names:

```sh
ls /sys/class/drm/
cat /sys/class/drm/card*-HDMI-A-*/status
cat /sys/class/drm/card*-HDMI-A-*/modes
```

If the projector does not advertise 848×480, first confirm in its manual
that it accepts that HDMI timing. Raspberry Pi OS supports a kernel command
line override such as `video=HDMI-A-1:848x480M@60D`, using the actual connector
name. Add it to the existing **single line** in
`/boot/firmware/cmdline.txt`, then reboot. Use this only for a compatible
input timing; the app cannot add a hardware mode that the display rejects.
For a projector that accepts only 1080p input, choose 1080p and let the
projector perform its internal downscaling.

Pi 4 supports 4K output; refresh-rate capability depends on the connector
and display configuration. A 4K HDMI mode at 30 Hz is sufficient for this
dashboard. `FPS` is the app's animation cap (default 15), independent of HDMI
refresh. Lower it to 8–10 if full 4K rendering is too costly on your Pi.
See Raspberry Pi's [display configuration documentation](https://www.raspberrypi.com/documentation/computers/configuration.html)
and [KMS HDMI troubleshooting guide](https://pip-assets.raspberrypi.com/categories/1259-audio-camera-and-display/documents/RP-004341-WP/Troubleshooting-KMS-HDMI-output).

## Output: framebuffer or SDL KMS/DRM

Frames are drawn in software with Pillow, then copied to the screen. By
default (`auto`) the display service writes them straight to the console
framebuffer, `/dev/fb0`, which works anywhere the text console is visible
and needs no SDL, EGL, or GPU driver. With SDL2 2.32 and the Mesa 26 packages
on Raspberry Pi OS Trixie, SDL's KMS/DRM backend can take over the screen yet
show only black (sometimes with a mouse pointer), so it is no longer the default.

The framebuffer runs at the console's HDMI mode. `auto` uses whatever that
is. To use a different fixed mode, choose it on the kernel command line: add
`video=HDMI-A-1:1920x1080@60` (for example) to the single line in
`/boot/firmware/cmdline.txt` and reboot. Selecting a profile that differs from
the console mode shows that instruction as a resolution error in the admin.

To use SDL's KMS/DRM output instead, put `ADSB_RADAR_OUTPUT=kms` in
`/etc/adsb-radar/display.env` and restart the display service. `fbdev` forces
the framebuffer; `ADSB_RADAR_FBDEV=/dev/fb1` selects another device. The same
choices are available as `--output auto|fbdev|kms` when running by hand.

## Configuration and credentials

The installer creates `/etc/adsb-radar/config.json` as `root:adsb-radar`, mode
`0640`. It contains a password hash and session signing key. Do not commit it.
`config.example.json` is safe to copy and edit for an initial installation.
The sample location is an example; enter your actual display location.

For unattended installs, the seed may include `ADMIN_PASSWORD` (at least 12
characters). The installer hashes it and omits the plaintext from the saved
configuration. Alternatively supply `ADMIN_PASSWORD_HASH` from Werkzeug.
An omitted password is generated and printed once. Keep seed files private.

Important settings:

| Setting | Purpose |
| --- | --- |
| `RECEIVER_URLS` | One combined tar1090 map/base address, or 1–8 receiver/feed URLs. |
| `LATITUDE`, `LONGITUDE` | Where overhead is; enter both. Editable in the admin page. |
| `DISTANCE_UNIT` | `nm`, `mi`, or `km`; all ranges use this unit. |
| `RADIUS` | Ground-distance threshold for the flight board, default 3. |
| `RADAR_RANGE` | Radar outer-ring range, default 12; never smaller than the radius. |
| `MIN_ELEVATION`, `HORIZON` | Optional visibility cutoffs in degrees. |
| `HOME_ELEVATION_FT`, `MAX_RANGE` | Optional ground elevation and straight-line eyesight limit. |
| `IDLE` | `radar`, `clock`, `message`, `blank`, or comma-separated rotation. |
| `IDLE_SECONDS` | Seconds per idle view, default 30. |
| `RESOLUTION` | `auto`, `4k`, `1080p`, `848x480`. |
| `FPS` | Animation cap, 5–60; default 15. Actual performance depends on hardware. |
| `ROTATION` | Clockwise rotation: 0, 90, 180, or 270. |
| `BRIGHTNESS` | Rendered image brightness, 0.001–1. Does not change monitor backlight. |
| `CLOCK_24H` | 24-hour or 12-hour clock. Timezone comes from the Pi OS. |
| `POLL_SECONDS` | Receiver polling interval, 2–30 seconds; default 5. |
| `ADMIN_BIND`, `ADMIN_PORT` | Admin address/port; defaults `0.0.0.0:8080`. |
| `ADMIN_USERNAME` | Default `admin`. |
| `ROUTE_LOOKUP` | Enable cached adsbdb route queries, default true. |
| `TYPE_LOOKUP` | Enable cached tar1090-db aircraft types, default true. |

Settings saved on the admin page live in `/var/lib/adsb-radar/settings.json`
and override config.json. Blank form fields inherit config.json/defaults.
Changes apply while running; a resolution change is attempted immediately.
Reset clears web overrides and retains custom palettes.

Receiver/port/credential/FPS changes made directly to config.json require:

```sh
sudo python3 /opt/adsb-radar/scripts/configure.py /etc/adsb-radar/config.json --check
sudo systemctl restart adsb-radar-admin adsb-radar-display
```

Reset the password and invalidate existing login sessions:

```sh
sudo python3 /opt/adsb-radar/scripts/configure.py /etc/adsb-radar/config.json --reset-password
sudo chown root:adsb-radar /etc/adsb-radar/config.json
sudo chmod 0640 /etc/adsb-radar/config.json
sudo systemctl restart adsb-radar-admin adsb-radar-display
```

## Diagnostics

The admin's `/status.json` and `/preview.png` require login. `/healthz` only
reports whether the admin is up; it does not claim HDMI is working. Admin
diagnostics include a separate renderer heartbeat, selected/actual output
sizes, receiver errors, and effective range/cone settings.

**Admin works, HDMI is blank:** inspect
`journalctl -u adsb-radar-display -n 100`. The `HDMI driver=` line shows the
output in use; it should start with `fbdev`. If it says `KMSDRM`, remove any
`ADSB_RADAR_OUTPUT=kms` override (see *Output* above). Check that the display is on,
the connector says `connected`, no desktop owns DRM, and `/dev/dri/` exists.
`id adsb-radar` should show video, render, input, and tty groups. Start the
systemd service to get a real tty1; launching a KMS app directly over SSH is
not equivalent. Reattach a disconnected display and restart the display
service; the admin remains independent.

**Wrong DRM card (KMS output only):** put `SDL_KMSDRM_DEVICE_INDEX=<card number>` in
`/etc/adsb-radar/display.env`, then restart the display service. Use the card
with the connected HDMI connector. Additional SDL environment overrides can
go in this file.

**No flights:** use the receiver's web UI to confirm current traffic. The
receiver must return positions, not just Mode-S messages. Check URL paths,
latitude/longitude, units, range, cutoff angles, and time synchronization.
Ground aircraft and positions older than 30 seconds are filtered. Missing
route/type metadata does not mean the receiver is offline.

**Unknown aircraft type or route:** the first metadata download/lookup can
take time. Check internet/DNS access. Cached data is in
`/var/lib/adsb-radar/metadata.db`. Set lookup options false to run using only
receiver data. Missing type artwork still uses a generic illustration when
a family is known; missing routes display a heading and callsign.

**Admin port conflict:** change `ADMIN_PORT` to an unused port (1024–65535),
especially if the receiver itself runs on this Pi and already uses 8080.
The installer does not alter firewall settings. Allow the chosen admin port
on your LAN if you manage a firewall.

**Return to the HDMI login console:** run the uninstaller, or stop the
display service and start `getty@tty1`. Uninstall restores the saved
enabled/active state rather than enabling a console that was previously off.

## Device acceptance check

Before relying on the installation, check it on the actual Pi and projector:

1. Boot with HDMI attached; the radar should start automatically.
2. Confirm 848×480 in admin diagnostics and the projector's input information.
3. Check split-flap route text, airline art, metrics, radar labels, and colors.
4. Disconnect the receiver: the offline clock should appear after repeated
   failures; reconnect it and confirm recovery.
5. Change a palette/resolution and reboot; settings should persist.
6. If available, repeat native-output checks on 1080p and 4K displays.
7. Test uninstall, confirm tty1 is restored, then reinstall.
