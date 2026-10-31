#!/usr/bin/env bash
# Update an existing installation without controlling any services.
set -euo pipefail

usage() {
    cat <<'EOF'
Usage: sudo bash ./update.sh

Run from a checkout after git pull --ff-only.
Copies application code and supplied artwork into an existing installation.
Does not install dependencies, change configuration or systemd units, or
start, stop, reload, enable, or restart any services (including the companion).
Restart services manually later to fully activate the new Python code.
EOF
}
case "${1:-}" in
    -h|--help) usage; exit 0 ;;
    "") ;;
    *) usage >&2; exit 2 ;;
esac
[[ $# -eq 0 ]] || { usage >&2; exit 2; }
[[ $EUID -eq 0 ]] || { echo "Run with sudo." >&2; exit 1; }
source_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)
[[ -f /etc/adsb-radar/config.json && -d /opt/adsb-radar/adsb_radar ]] || {
    echo "Existing installation required; use install.sh for first-time setup." >&2
    exit 1
}
for command in python3 rsync; do
    command -v "$command" >/dev/null || { echo "Missing dependency: $command" >&2; exit 1; }
done
# Stage and validate everything before touching the installed runtime.
stage=$(mktemp -d /opt/.adsb-radar-update.XXXXXX)
trap 'rm -rf -- "$stage"' EXIT
for item in adsb_radar scripts docs systemd README.md NOTICE.md pyproject.toml requirements.txt install.sh uninstall.sh update.sh; do
    cp -R -- "$source_dir/$item" "$stage/"
done
find "$stage" -type d -name __pycache__ -prune -exec rm -rf -- {} +
chmod -R go-w "$stage"
chmod 0755 "$stage"
python3 -m compileall -q "$stage/adsb_radar"
# rsync replaces individual files by rename; do not use --inplace while running.
rsync -a --delete "$stage/" /opt/adsb-radar/
chown -R root:root /opt/adsb-radar
if [[ -d "$source_dir/images" ]]; then
    install -d -m 0750 -o adsb-radar -g adsb-radar /var/lib/adsb-radar/images
    rsync -a --exclude='.gitkeep' --exclude='README.md' "$source_dir/images/" /var/lib/adsb-radar/images/
    chown -R adsb-radar:adsb-radar /var/lib/adsb-radar/images
    chmod -R u+rwX,g+rX,o-rwx /var/lib/adsb-radar/images
fi
echo "Runtime files and artwork updated. No services were controlled."
echo "Running Python processes need a later manual restart to fully load new code."
echo "Dependency or service-unit changes require a separate maintenance install."
