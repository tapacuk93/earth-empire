#!/bin/bash
# The monitor's installer on the box (CONTRACT.md "The box"): its venv (faster-whisper, yt-dlp, the
# backend package for secrets/aicoin, the collector's requirements for its Instagram browser), the
# units ee-monitor-api (127.0.0.1:8010) and ee-monitor-worker, and nginx routes for /v1/monitor/ and
# /v1/published. Run as root by backend/deploy/deploy-box.sh; idempotent.
set -euxo pipefail
ROOT=/opt/earth-empire
REPO=$ROOT/repo
VENV=$ROOT/monitor-venv
DATA=/var/lib/earth-empire/monitor
export PLAYWRIGHT_BROWSERS_PATH=$ROOT/ms-playwright

[ -x $VENV/bin/python ] || sudo -u earth python3 -m venv $VENV
sudo -u earth $VENV/bin/pip install --no-cache-dir -q --upgrade pip
sudo -u earth $VENV/bin/pip install --no-cache-dir -q "$REPO/backend" -r "$REPO/collector/requirements.txt"
sudo -u earth $VENV/bin/pip install --no-cache-dir -q --upgrade --force-reinstall --no-deps "$REPO/monitor"
sudo -u earth $VENV/bin/pip install --no-cache-dir -q "$REPO/monitor"
sudo -u earth $VENV/bin/pip install --no-cache-dir -q --upgrade yt-dlp
# Chromium for the Facebook downloader: the shared one under PLAYWRIGHT_BROWSERS_PATH
sudo -u earth env PLAYWRIGHT_BROWSERS_PATH=$PLAYWRIGHT_BROWSERS_PATH $VENV/bin/playwright install chromium

install -d -o earth -g earth -m 750 $DATA $DATA/models $DATA/tmp $DATA/screenshots
install -d -o earth -g earth -m 700 /var/lib/earth-empire/browser /var/lib/earth-empire/browser/facebook-dl

cat > /usr/local/bin/ee-monitor <<SH
#!/bin/sh
# The monitor's CLI, as the earth user with the box's config.
set -a; . /etc/earth-empire/env; set +a
export EE_COLLECTOR_SRC=$REPO/collector PLAYWRIGHT_BROWSERS_PATH=$PLAYWRIGHT_BROWSERS_PATH EE_MONITOR_TMP=$DATA/tmp EE_WHISPER_MODELS=$DATA/models
cd $DATA
if [ "\$(id -un)" = earth ]; then exec $VENV/bin/ee-monitor "\$@"; else exec sudo -E -u earth $VENV/bin/ee-monitor "\$@"; fi
SH
chmod 755 /usr/local/bin/ee-monitor

install -d /etc/nginx/earth-empire.d
cat > /etc/nginx/earth-empire.d/monitor.conf <<'NGINX'
location /v1/monitor/ {
    proxy_pass http://127.0.0.1:8010;
    proxy_set_header Host $host;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto https;
    proxy_read_timeout 120s;
}
location = /v1/published {
    proxy_pass http://127.0.0.1:8010;
    proxy_set_header Host $host;
    proxy_set_header X-Forwarded-Proto https;
}
NGINX
# the backend's server block includes this directory (backend/deploy/install.sh); older configs get it here
if ! grep -q "earth-empire.d" /etc/nginx/sites-available/earth-empire; then
  sed -i 's|^    location / {|    include /etc/nginx/earth-empire.d/*.conf;\n    location / {|' /etc/nginx/sites-available/earth-empire
fi
nginx -t && systemctl reload nginx

COMMON="User=earth
EnvironmentFile=/etc/earth-empire/env
Environment=EE_COLLECTOR_SRC=$REPO/collector
Environment=PLAYWRIGHT_BROWSERS_PATH=$PLAYWRIGHT_BROWSERS_PATH
Environment=EE_MONITOR_TMP=$DATA/tmp
Environment=EE_WHISPER_MODELS=$DATA/models
Environment=HF_HUB_DISABLE_TELEMETRY=1
WorkingDirectory=$DATA"

cat > /etc/systemd/system/ee-monitor-api.service <<UNIT
[Unit]
Description=Earth Empire monitor API (/v1/monitor/, /v1/published)
After=network-online.target
Wants=network-online.target

[Service]
$COMMON
ExecStart=$VENV/bin/uvicorn eemonitor.api:app --host 127.0.0.1 --port 8010 --proxy-headers --no-access-log
Restart=always
RestartSec=3
MemoryMax=400M

[Install]
WantedBy=multi-user.target
UNIT

cat > /etc/systemd/system/ee-monitor-worker.service <<UNIT
[Unit]
Description=Earth Empire monitor worker (discover, transcribe, detect, recommendations)
After=network-online.target ee-monitor-api.service
Wants=network-online.target

[Service]
$COMMON
ExecStart=$VENV/bin/python -m eemonitor.worker
Restart=always
RestartSec=30
TimeoutStopSec=30
Nice=10
CPUWeight=50
MemoryMax=2200M

[Install]
WantedBy=multi-user.target
UNIT

systemctl daemon-reload
systemctl enable ee-monitor-api ee-monitor-worker
systemctl restart ee-monitor-api ee-monitor-worker
sleep 4
curl -fsS http://127.0.0.1:8010/v1/monitor/status | head -c 300; echo
