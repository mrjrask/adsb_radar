# Pimoroni companion flight deck

Independent optional add-on for **OLED — LCD — OLED**, with the center LCD
forward of the two monochrome instrument panels. Panels use independent layouts
so the physical setback does not break a continuous image.

| Panel | In-flight | Between overhead flights |
| --- | --- | --- |
| Left PIM374 | HDMI-selected callsign, type, distance and bearing | Traffic count and scanning status |
| Center PIM576 | North-up radar, eight-second sweep, amber selected target | Live local radar |
| Right PIM374 | Altitude tape, groundspeed, climb/descent rate | Clock and feed status |

The HDMI process publishes an atomic snapshot once a second. This service reads
it at two frames per second, makes no network requests and never takes over HDMI.
It shares the HDMI radar range, distance units and brightness. Positions expire
after 30 seconds; a missing/old HDMI heartbeat or offline feed shows NO SIGNAL.
The default OLED layout reserves the inner 32 columns on each panel for the
center LCD overlap: x=96–127 on the left and x=0–31 on the right. Text fits the
remaining 96-column area. The innermost 24 columns alternate complementary
checkerboards once a second; eight columns remain dark as a viewing-angle margin.
This gives each patterned pixel 50% on-time, but does not match the variable wear
of visible content or repair burn-in. Adjust `left_hidden_columns` and
`right_hidden_columns` independently (0–48, default 32) in companion.json; use 0
for an unobstructed panel. These coordinates follow the configured OLED rotation.

OLED text shifts slowly by two pixels to reduce persistent wear; it does not
eliminate burn-in. Stop the service when the displays are not needed.

## Hardware preparation

Power off the Pi before fitting/removing breakouts. Match connector labels.
The 2x I2C + 1x SPI board is the Breakout Garden Mini (PIM478).

**Both OLEDs ship at 0x3C. Cut the address-selection trace on the right OLED,
as described by Pimoroni, to make it 0x3D.** Slots share the same I2C bus;
separate slots do not solve an address collision. This cannot be done in software.
The installer cannot verify two separate displays while they share an address.

Default wiring: I2C bus 1, OLED addresses 0x3C/0x3D; LCD SPI0 CE1 (BCM7),
DC BCM9, backlight BCM19, clock BCM11 and MOSI BCM10. These are the Mini's
fixed SPI slot connections. Pins must not be occupied by another HAT/function.
Uses luma.oled SH1107 and Pimoroni's st7789 driver, with rpi-lgpio for
GPIO compatibility on modern Raspberry Pi models.

## Install and update

From this repository checkout on Raspberry Pi OS, first install/update the main
application so it publishes the companion snapshot, then install the add-on:

```bash
sudo ./install.sh
sudo ./pimoroni_companion/install.sh
sudo reboot
```

The add-on installer installs dependencies, enables I2C/SPI with raspi-config,
creates `/opt/adsb-radar-companion/venv`, and enables
`adsb-radar-companion.service` as the existing unprivileged adsb-radar user.
It does not run Pimoroni's whole-garden automatic installer or install drivers
for unrelated breakouts. Use `--no-start` to install without starting the service.
Run the same add-on installer after pulling updates. Existing settings survive.

Edit `/etc/adsb-radar/companion.json` to swap left/right addresses or change
mounting rotation. OLED rotations are quarter-turns (0–3), LCD rotations are
0/90/180/270 degrees; default LCD rotation is 90. Restart after editing:

```bash
sudo systemctl restart adsb-radar-companion
systemctl status adsb-radar-companion
journalctl -u adsb-radar-companion -n 60
sudo i2cdetect -y 1
ls -l /dev/i2c-1 /dev/spidev0.1 /dev/gpiochip*
```

The scan should show both 3c and 3d. Confirm both displays physically work:
a scan cannot detect two devices colliding at 3c. If hardware initialization or
writing fails, the service logs the error and retries after ten seconds. Hardware
failure stays isolated from HDMI. On orderly shutdown it blanks the OLEDs and
LCD and turns the LCD backlight off. Verify orientation, colors and GPIO access
on the real Pi; desktop tests cannot validate electrical operation.

## Uninstall

```bash
sudo ./pimoroni_companion/uninstall.sh
```

Or use `/opt/adsb-radar-companion/uninstall.sh`. Add `--purge` to remove the
add-on settings as well. Removes only its service, runtime code and private
Python environment. Shared apt packages, group memberships and enabled I2C/SPI
remain because other hardware may depend on them. Main HDMI services and
configuration are unaffected. Uninstall this add-on before removing the main
application, because it uses the main application's service account.

## Sources

- [Pimoroni OLED specifications and address trace](https://shop.pimoroni.com/products/1-12-oled-breakout)
- [Breakout Garden Mini pin assignment](https://shop.pimoroni.com/products/breakout-garden-mini-i2c-spi)
- [PIM576 LCD](https://shop.pimoroni.com/products/1-54-spi-colour-square-lcd-240x240-breakout)
- [Pimoroni ST7789 examples](https://github.com/pimoroni/st7789-python/blob/main/examples/shapes.py)
- [Luma SH1107 API](https://luma-oled.readthedocs.io/en/latest/api-documentation.html)
