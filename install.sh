#!/usr/bin/env bash
# Raspberry Pi OS Trixie Lite installer. Run from a checkout as root.
set -euo pipefail

usage() {
    cat <<'EOF'
Usage: sudo ./install.sh [--config /path/to/config.json] [--no-start]

Installs OS dependencies, code, artwork you supplied, and two systemd services.
Existing /etc/adsb-radar/config.json and saved palettes are preserved.
--config FILE  Seed the first installation (does not replace an existing config).
--no-start     Stage the installation without taking tty1 or starting services.
EOF
}

seed=""
start=1
while (($#)); do
    case "$1" in
        --config) [[ $# -ge 2 ]] || { usage; exit 2; }; seed="$2"; shift 2 ;;
        --no-start) start=0; shift ;;
        -h|--help) usage; exit 0 ;;
        *) usage; exit 2 ;;
    esac
done
[[ $EUID -eq 0 ]] || { echo "Run with sudo." >&2; exit 1; }
[[ $(uname -s) == Linux && -r /etc/os-release ]] || { echo "Requires Raspberry Pi OS Trixie Lite." >&2; exit 1; }
# shellcheck disable=SC1091
source /etc/os-release
[[ ${VERSION_CODENAME:-} == trixie ]] || { echo "This installer targets Debian/Raspberry Pi OS Trixie." >&2; exit 1; }
if ((start)) && [[ ! -d /run/systemd/system ]]; then
    echo "systemd must be running; use --no-start only when staging an image." >&2
    exit 1
fi
if ((start)) && systemctl is-active --quiet display-manager.service; then
    echo "Boot to the console before installing. See docs/SETUP.md." >&2
    exit 1
fi
source_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)
[[ -f "$source_dir/adsb_radar/display.py" ]] || { echo "Run from the complete repository checkout." >&2; exit 1; }
if [[ -n $seed ]]; then
    [[ -r $seed ]] || { echo "Cannot read the seed config." >&2; exit 1; }
    seed=$(realpath -- "$seed")
fi

export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get install -y --no-install-recommends \
    python3 python3-pygame python3-pil python3-flask python3-requests gunicorn \
    libsdl2-2.0-0 libegl1 libgles2 libgbm1 libdrm2 libgl1-mesa-dri \
    fonts-dejavu-core fonts-bebas-neue fonts-jetbrains-mono ca-certificates rsync kbd passwd

# Use Debian's SDL build with KMS/DRM. PyPI wheels may omit this backend.
python3 - <<'PY'
import ctypes
library = ctypes.CDLL('libSDL2-2.0.so.0')
library.SDL_GetVideoDriver.restype = ctypes.c_char_p
drivers = [library.SDL_GetVideoDriver(i).decode().lower() for i in range(library.SDL_GetNumVideoDrivers())]
if 'kmsdrm' not in drivers:
    raise SystemExit('The system SDL2 has no kmsdrm backend. Install a KMS-enabled Raspberry Pi OS build.')
print('System SDL2 has the KMS/DRM backend.')
PY

for group in video render input tty adsb-radar; do
    getent group "$group" >/dev/null || groupadd --system "$group"
done
if ! id adsb-radar >/dev/null 2>&1; then
    useradd --system --gid adsb-radar --groups video,render,input,tty \
        --home-dir /var/lib/adsb-radar --no-create-home --shell /usr/sbin/nologin adsb-radar
fi
usermod -a -G video,render,input,tty adsb-radar
install -d -m 0750 -o root -g adsb-radar /etc/adsb-radar
install -d -m 0750 -o adsb-radar -g adsb-radar /var/lib/adsb-radar

if [[ ! -f /etc/adsb-radar/install-state.json ]]; then
    # Keep the original console state across updates and failed/repeated installs.
    getty_enabled=$(systemctl is-enabled getty@tty1.service 2>/dev/null || true)
    getty_active=$(systemctl is-active getty@tty1.service 2>/dev/null || true)
    python3 - "$getty_enabled" "$getty_active" <<'PY'
import json, sys
from pathlib import Path
Path('/etc/adsb-radar/install-state.json').write_text(json.dumps({
    'getty_enabled': sys.argv[1].strip(), 'getty_active': sys.argv[2].strip()
}) + '\n')
PY
    chmod 0600 /etc/adsb-radar/install-state.json
fi

configure_args=(/etc/adsb-radar/config.json)
[[ -z $seed ]] || configure_args+=(--seed "$seed")
python3 "$source_dir/scripts/configure.py" "${configure_args[@]}"
chown root:adsb-radar /etc/adsb-radar/config.json
chmod 0640 /etc/adsb-radar/config.json

# Prepare the new code before stopping a working display. Copy only runtime files.
stage=$(mktemp -d /opt/.adsb-radar-stage.XXXXXX)
trap 'rm -rf -- "$stage"' EXIT
for item in adsb_radar scripts docs systemd README.md NOTICE.md pyproject.toml requirements.txt install.sh uninstall.sh; do
    cp -R -- "$source_dir/$item" "$stage/"
done
find "$stage" -type d -name __pycache__ -prune -exec rm -rf -- {} +
chmod -R go-w "$stage"
chmod 0755 "$stage"
python3 -m compileall -q "$stage/adsb_radar"
systemctl stop adsb-radar-display.service adsb-radar-admin.service 2>/dev/null || true
install -d -m 0755 /opt/adsb-radar
rsync -a --delete "$stage/" /opt/adsb-radar/
chown -R root:root /opt/adsb-radar
install -d -m 0750 -o adsb-radar -g adsb-radar /var/lib/adsb-radar/images
if [[ -d "$source_dir/images" ]]; then
    rsync -a --exclude='.gitkeep' --exclude='README.md' "$source_dir/images/" /var/lib/adsb-radar/images/
    chown -R adsb-radar:adsb-radar /var/lib/adsb-radar/images
    chmod -R u+rwX,g+rX,o-rwx /var/lib/adsb-radar/images
fi
install -m 0644 "$stage/systemd/adsb-radar-display.service" "$stage/systemd/adsb-radar-admin.service" /etc/systemd/system/
systemctl daemon-reload
systemctl enable adsb-radar-admin.service adsb-radar-display.service
if ((start)); then
    # Disable only the login console this application occupies. SSH and tty2+ stay available.
    if [[ $(systemctl is-enabled getty@tty1.service 2>/dev/null || true) != masked* ]]; then
        systemctl disable --now getty@tty1.service
    fi
    systemctl start adsb-radar-admin.service adsb-radar-display.service
    sleep 2
    if ! systemctl is-active --quiet adsb-radar-admin.service; then
        echo "Admin service failed. Run: journalctl -u adsb-radar-admin -n 60" >&2
        exit 1
    fi
    echo "Services started. Check HDMI status: systemctl status adsb-radar-display"
else
    echo "Staged only. Before starting: sudo systemctl disable --now getty@tty1"
    echo "Then: sudo systemctl start adsb-radar-admin adsb-radar-display"
fi
python3 - <<'PY'
import json
with open('/etc/adsb-radar/config.json') as stream:
    config = json.load(stream)
print(f'Admin: http://<Pi-IP>:{config["ADMIN_PORT"]}/ (user {config["ADMIN_USERNAME"]})')
PY
echo "Update: git pull, then sudo ./install.sh. Uninstall: sudo /opt/adsb-radar/uninstall.sh"
