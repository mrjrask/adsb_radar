#!/usr/bin/env bash
# Remove this application; preserve private settings and artwork unless --purge.
set -euo pipefail
purge=0
case "${1:-}" in
    --purge) purge=1 ;;
    "") ;;
    -h|--help) echo "Usage: sudo ./uninstall.sh [--purge]"; exit 0 ;;
    *) echo "Usage: sudo ./uninstall.sh [--purge]" >&2; exit 2 ;;
esac
[[ $# -le 1 ]] || exit 2
[[ $EUID -eq 0 ]] || { echo "Run with sudo." >&2; exit 1; }
[[ $(uname -s) == Linux ]] || { echo "Run this on the installed Raspberry Pi." >&2; exit 1; }
systemctl disable --now adsb-radar-display.service adsb-radar-admin.service 2>/dev/null || true
rm -f /etc/systemd/system/adsb-radar-display.service /etc/systemd/system/adsb-radar-admin.service
systemctl daemon-reload
systemctl reset-failed adsb-radar-display.service adsb-radar-admin.service 2>/dev/null || true
if [[ -f /etc/adsb-radar/install-state.json ]]; then
    mapfile -t console_state < <(python3 - <<'PY'
import json
with open('/etc/adsb-radar/install-state.json') as stream:
    state = json.load(stream)
print(state.get('getty_enabled', ''))
print(state.get('getty_active', ''))
PY
)
    case "${console_state[0]:-}" in
        enabled) systemctl enable getty@tty1.service ;;
        enabled-runtime) systemctl enable --runtime getty@tty1.service ;;
        disabled) systemctl disable getty@tty1.service ;;
    esac
    if [[ ${console_state[1]:-} == active ]]; then
        systemctl start getty@tty1.service
    fi
    rm -f /etc/adsb-radar/install-state.json
fi
# Move out before deleting the directory if this script was run from /opt/adsb-radar.
cd /
rm -rf -- /opt/adsb-radar
if ((purge)); then
    rm -rf -- /etc/adsb-radar /var/lib/adsb-radar
    if id adsb-radar >/dev/null 2>&1; then userdel adsb-radar; fi
    if getent group adsb-radar >/dev/null; then groupdel adsb-radar; fi
    echo "Application, credentials, cache, palettes and installed artwork removed."
else
    echo "Application removed. Settings, credentials, palettes and artwork remain in /etc/adsb-radar and /var/lib/adsb-radar."
fi
echo "Shared apt dependencies and your source checkout were kept."
