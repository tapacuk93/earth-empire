#!/bin/bash
# Installs the collector on the box (CONTRACT.md "The box"). Idempotent; run as root by
# backend/deploy/deploy-box.sh after every pull, or by hand:
#   sudo /opt/earth-empire/repo/collector/deploy/install.sh
# Leaves the hourly timer as it is: enable it once with
#   systemctl enable --now ee-collector-incremental.timer
set -euo pipefail

REPO=${EE_REPO:-/opt/earth-empire/repo}
C=$REPO/collector
VENV=/opt/earth-empire/collector-venv
export PLAYWRIGHT_BROWSERS_PATH=/opt/earth-empire/ms-playwright
export DEBIAN_FRONTEND=noninteractive

need=()
for p in python3-venv ffmpeg fonts-noto-color-emoji fonts-noto-cjk; do
  dpkg -s "$p" >/dev/null 2>&1 || need+=("$p")
done
if [ ${#need[@]} -gt 0 ]; then
  apt-get update -q
  apt-get install -y -q "${need[@]}"
fi

[ -x $VENV/bin/python ] || python3 -m venv $VENV
$VENV/bin/pip install -q --upgrade pip
$VENV/bin/pip install -q -r $C/requirements.txt

# the shared browsers dir belongs to earth (CONTRACT.md): system libraries as root, browsers as earth
install -d -o earth -g earth $PLAYWRIGHT_BROWSERS_PATH
$VENV/bin/python -m playwright install-deps chromium
sudo -u earth -H env PLAYWRIGHT_BROWSERS_PATH=$PLAYWRIGHT_BROWSERS_PATH $VENV/bin/python -m playwright install chromium

install -d -o earth -g earth -m 750 /var/lib/earth-empire/collector
install -d -o earth -g earth -m 700 /var/lib/earth-empire/browser
install -d -o earth -g earth -m 700 /var/lib/earth-empire/browser/instagram
install -d -o earth -g earth -m 750 /var/log/earth-empire /var/log/earth-empire/collector

install -m 755 $C/deploy/ee-collector /usr/local/bin/ee-collector
for u in ee-collector-incremental.service ee-collector-incremental.timer ee-collector-quick.service ee-collector-quick.timer ee-collector-backfill.service \
         ee-collector-heartbeat.service ee-collector-heartbeat.timer; do
  install -m 644 $C/deploy/$u /etc/systemd/system/$u
done
systemctl daemon-reload
# the heartbeat only reports the last run's state to the API; always on
systemctl enable --now ee-collector-heartbeat.timer >/dev/null 2>&1 || true
# the quick check for new posts and reposts follows the incremental timer: on when it is on
if systemctl is-enabled -q ee-collector-incremental.timer 2>/dev/null; then
  systemctl enable --now ee-collector-quick.timer >/dev/null 2>&1 || true
fi

# old run logs: keep 60 days
cat > /etc/cron.daily/ee-collector-logs <<'EOT'
#!/bin/sh
find /var/log/earth-empire/collector -name '*.log' -mtime +60 -delete
find /var/lib/earth-empire/collector/screenshots -name '*.png' -mtime +30 -delete 2>/dev/null || true
EOT
chmod 755 /etc/cron.daily/ee-collector-logs

echo "collector installed; timer: $(systemctl is-enabled ee-collector-incremental.timer 2>/dev/null || true)"
