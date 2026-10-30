#!/usr/bin/env bash
# Run only inside a disposable Debian Trixie CI container, as root.
set -euo pipefail
[[ ${CI:-} == true && $EUID -eq 0 ]] || { echo "For disposable CI containers only." >&2; exit 1; }
apt-get update
apt-get install -y systemd
# Simulate only service-manager operations. The actual apt installation,
# Python dependencies, file permissions, account creation and removal run normally.
mkdir -p /tmp/mock-bin
cat > /tmp/mock-bin/systemctl <<'MOCK'
#!/usr/bin/env bash
printf '%s\n' "$*" >> /tmp/systemctl-calls
case "$1" in
    is-enabled) echo enabled ;;
    is-active) echo active ;;
esac
MOCK
chmod +x /tmp/mock-bin/systemctl
export PATH="/tmp/mock-bin:$PATH"
cat > /tmp/radar-seed.json <<'JSON'
{"RECEIVER_URLS":["http://127.0.0.1:59999"],"LATITUDE":41.88,"LONGITUDE":-87.63,
 "ADMIN_PASSWORD":"CI-only-password-123", "ROUTE_LOOKUP":false,"TYPE_LOOKUP":false}
JSON
bash install.sh --config /tmp/radar-seed.json --no-start
test -x /opt/adsb-radar/uninstall.sh
test -f /etc/systemd/system/adsb-radar-display.service
test "$(stat -c '%U:%G:%a' /etc/adsb-radar/config.json)" = root:adsb-radar:640
test "$(stat -c '%U:%G:%a' /var/lib/adsb-radar)" = adsb-radar:adsb-radar:750
systemd-analyze verify /etc/systemd/system/adsb-radar-admin.service /etc/systemd/system/adsb-radar-display.service
before=$(sha256sum /etc/adsb-radar/config.json)
printf '{"RADIUS":7}\n' > /var/lib/adsb-radar/settings.json
printf '{"My colors":{}}\n' > /var/lib/adsb-radar/presets.json
mkdir -p /var/lib/adsb-radar/images/air
printf 'asset preservation sentinel\n' > /var/lib/adsb-radar/images/air/local-upload.txt
bash install.sh --no-start
test "$before" = "$(sha256sum /etc/adsb-radar/config.json)"
test -f /var/lib/adsb-radar/presets.json
test -f /var/lib/adsb-radar/images/air/local-upload.txt
PYTHONDONTWRITEBYTECODE=1 runuser -u adsb-radar -- sh -c 'cd /opt/adsb-radar && exec /usr/bin/python3 -' <<'PY'
from adsb_radar.config import load_config
from adsb_radar.web import create_app
config = load_config()
assert config['LATITUDE'] == 41.88
app = create_app(config=config)
assert app.test_client().get('/healthz').status_code == 200
PY
runuser -u adsb-radar -- env SDL_VIDEODRIVER=dummy \
    sh -c 'cd /opt/adsb-radar && exec /usr/bin/python3 -m adsb_radar.display --windowed --demo radar --frames 2 --state-dir /var/lib/adsb-radar'
# Also exercise the actual Gunicorn entry point, independent of HDMI.
runuser -u adsb-radar -- sh -c 'cd /opt/adsb-radar && exec /usr/bin/python3 -m adsb_radar.admin' &
admin_pid=$!
trap 'kill "$admin_pid" 2>/dev/null || true' EXIT
python3 - <<'PY'
import time, urllib.request
for _ in range(50):
    try:
        with urllib.request.urlopen('http://127.0.0.1:8080/healthz', timeout=1) as response:
            assert response.status == 200
            break
    except OSError:
        time.sleep(0.1)
else:
    raise SystemExit('Admin did not start')
PY
kill "$admin_pid"
wait "$admin_pid" || true
trap - EXIT
bash uninstall.sh
test ! -e /opt/adsb-radar
test ! -e /etc/systemd/system/adsb-radar-display.service
test -f /etc/adsb-radar/config.json
test -f /var/lib/adsb-radar/settings.json
test -f /var/lib/adsb-radar/images/air/local-upload.txt
rg_restore=0
while IFS= read -r line; do
    [[ $line != 'enable getty@tty1.service' ]] || rg_restore=1
done < /tmp/systemctl-calls
test "$rg_restore" = 1
bash uninstall.sh --purge
test ! -e /etc/adsb-radar
test ! -e /var/lib/adsb-radar
if id adsb-radar >/dev/null 2>&1; then exit 1; fi
echo "Install, update, retained data, runtime imports, headless rendering and purge passed."
