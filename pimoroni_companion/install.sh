#!/usr/bin/env bash
set -euo pipefail
if [[ ${1:-} == --help ]]; then
    echo 'Usage: sudo ./pimoroni_companion/install.sh [--no-start]'
    exit 0
fi
[[ $# -eq 0 || ( $# -eq 1 && $1 == --no-start ) ]] || exit 2
[[ $EUID -eq 0 ]] || { echo 'Run with sudo.' >&2; exit 1; }
if [[ ! -e /proc/device-tree/model ]] || ! grep -q 'Raspberry Pi' /proc/device-tree/model; then
    echo 'Requires a Raspberry Pi running Raspberry Pi OS.' >&2; exit 1;
fi
if [[ ! -f /etc/adsb-radar/config.json ]] || ! id adsb-radar >/dev/null 2>&1; then
    echo 'Install the main HDMI application first.' >&2; exit 1;
fi
source_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)
[[ $source_dir != /opt/adsb-radar-companion ]] || {
    echo 'Run the installer from your repository checkout.' >&2; exit 1;
}
command -v raspi-config >/dev/null || { echo 'raspi-config is required.' >&2; exit 1; }
export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get install -y --no-install-recommends python3-venv python3-dev build-essential \
    libjpeg-dev zlib1g-dev liblgpio-dev libgpiod-dev swig pkg-config fonts-dejavu-core i2c-tools
for group in i2c spi gpio; do
    getent group "$group" >/dev/null || groupadd --system "$group"
done
usermod -a -G i2c,spi,gpio adsb-radar
install -d -m 0755 /opt/adsb-radar-companion
systemctl stop adsb-radar-companion.service 2>/dev/null || true
# A private environment is removed on uninstall; no system Python packages are overwritten.
python3 -m venv /opt/adsb-radar-companion/venv
/opt/adsb-radar-companion/venv/bin/pip install -r "$source_dir/requirements.txt"
for file in companion.py requirements.txt uninstall.sh README.md; do
    install -m 0644 "$source_dir/$file" "/opt/adsb-radar-companion/$file"
done
chmod 0755 /opt/adsb-radar-companion/uninstall.sh
if [[ ! -f /etc/adsb-radar/companion.json ]]; then
    install -o root -g adsb-radar -m 0640 "$source_dir/config.example.json" /etc/adsb-radar/companion.json
fi
raspi-config nonint do_i2c 0
raspi-config nonint do_spi 0
install -m 0644 "$source_dir/adsb-radar-companion.service" /etc/systemd/system/
systemctl daemon-reload
systemctl enable adsb-radar-companion.service
if [[ ${1:-} != --no-start && -e /dev/i2c-1 && -e /dev/spidev0.1 ]]; then
    systemctl restart adsb-radar-companion.service
fi
echo 'Installed. Reboot to apply I2C/SPI changes. Cut the address trace on ONE OLED (0x3d).'
echo 'Update the main application too: its display service publishes companion.json.'
echo 'Status: systemctl status adsb-radar-companion; logs: journalctl -u adsb-radar-companion -n 60'
