#!/usr/bin/env bash
set -euo pipefail
if [[ ${1:-} == --help ]]; then
    echo 'Usage: sudo ./pimoroni_companion/uninstall.sh [--purge]'
    exit 0
fi
[[ $# -eq 0 || ( $# -eq 1 && $1 == --purge ) ]] || exit 2
[[ $EUID -eq 0 ]] || { echo 'Run with sudo.' >&2; exit 1; }
systemctl disable --now adsb-radar-companion.service 2>/dev/null || true
rm -f /etc/systemd/system/adsb-radar-companion.service
systemctl daemon-reload
rm -rf /opt/adsb-radar-companion
if [[ ${1:-} == --purge ]]; then
    rm -f /etc/adsb-radar/companion.json
fi
echo 'Companion removed. HDMI, shared OS packages, groups and I2C/SPI remain available.'
