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
# The runtime-only updater must not call systemctl at all.
calls_before=$(wc -l < /tmp/systemctl-calls)
printf 'outdated runtime sentinel\\n' > /opt/adsb-radar/adsb_radar/obsolete-update-test.txt
bash update.sh
test "$calls_before" = "$(wc -l < /tmp/systemctl-calls)"
test ! -e /opt/adsb-radar/adsb_radar/obsolete-update-test.txt
cmp adsb_radar/display.py /opt/adsb-radar/adsb_radar/display.py
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
# Switch the installed configuration to one combined tar1090 feed, retaining
# credentials, data, and the service account's ability to read config.json.
python3 - <<'PY'
import json
with open('/etc/adsb-radar/config.json') as stream:
    config = json.load(stream)
with open('/tmp/original-credentials.json', 'w') as stream:
    json.dump({k: config[k] for k in ('ADMIN_PASSWORD_HASH', 'SECRET_KEY')}, stream)
PY
bash install.sh --no-start --tar1090 127.0.0.1:59999
test "$(stat -c '%U:%G:%a' /etc/adsb-radar/config.json)" = root:adsb-radar:640
runuser -u adsb-radar -- sh -c 'cd /opt/adsb-radar && exec /usr/bin/python3 -' <<'PY'
from adsb_radar.config import load_config
assert load_config()['RECEIVER_URLS'] == ['http://127.0.0.1:59999']
PY
python3 - <<'PY'
import json
with open('/etc/adsb-radar/config.json') as stream:
    current = json.load(stream)
with open('/tmp/original-credentials.json') as stream:
    previous = json.load(stream)
assert all(current[k] == v for k, v in previous.items())
PY
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
