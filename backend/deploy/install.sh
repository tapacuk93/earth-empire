#!/bin/bash
# The backend's installer on the box (CONTRACT.md "The box"): its venv, Playwright's Chromium,
# nginx in front of the API, and the systemd units ee-api and ee-worker. Run as root; idempotent.
set -euxo pipefail
ROOT=/opt/earth-empire
SRC=$ROOT/repo/backend
VENV=$ROOT/backend-venv
export PLAYWRIGHT_BROWSERS_PATH=$ROOT/ms-playwright

[ -x $VENV/bin/python ] || sudo -u earth python3 -m venv $VENV
sudo -u earth $VENV/bin/pip install --no-cache-dir -q --upgrade pip
sudo -u earth $VENV/bin/pip install --no-cache-dir -q "$SRC"
# Chromium for the Facebook poster (shared with the collector's under PLAYWRIGHT_BROWSERS_PATH)
$VENV/bin/playwright install-deps chromium >/dev/null
sudo -u earth env PLAYWRIGHT_BROWSERS_PATH=$PLAYWRIGHT_BROWSERS_PATH $VENV/bin/playwright install chromium

install -d -o earth -g earth -m 755 /var/lib/earth-empire/backend /var/lib/earth-empire/backend/facebook

# A rebuilt box: bring every part's state back from the hourly S3 backup before anything starts
# (backend/ee/backup.py). Runs before the other parts' installers, which deploy-box.sh runs after.
if [ ! -f /var/lib/earth-empire/backend/earth-empire.sqlite3 ] && \
   aws s3 ls s3://earth-empire-backups/state/latest/backend/ >/dev/null 2>&1; then
  echo "fresh box: restoring state from S3"
  set -a; . /etc/earth-empire/env; set +a
  $VENV/bin/ee restore
fi

cat > /usr/local/bin/ee <<EOF
#!/bin/sh
# The backend's CLI, as the earth user with the box's config.
set -a; . /etc/earth-empire/env; set +a
if [ "\$(id -un)" = earth ]; then exec $VENV/bin/ee "\$@"; else exec sudo -E -u earth $VENV/bin/ee "\$@"; fi
EOF
chmod 755 /usr/local/bin/ee

cat > /etc/nginx/sites-available/earth-empire <<'NGINX'
# CloudFront -> here (port 80, from CloudFront's addresses only, by security group) -> uvicorn
server {
    listen 80 default_server;
    listen [::]:80 default_server;
    server_name _;
    client_max_body_size 50m;
    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto https;
        proxy_read_timeout 120s;
    }
}
NGINX
ln -sf /etc/nginx/sites-available/earth-empire /etc/nginx/sites-enabled/earth-empire
rm -f /etc/nginx/sites-enabled/default
nginx -t && systemctl reload nginx || systemctl restart nginx

cat > /etc/systemd/system/ee-api.service <<EOF
[Unit]
Description=Earth Empire API
After=network-online.target
Wants=network-online.target

[Service]
User=earth
EnvironmentFile=/etc/earth-empire/env
WorkingDirectory=/var/lib/earth-empire/backend
ExecStart=$VENV/bin/uvicorn ee.api:app --host 127.0.0.1 --port 8000 --proxy-headers --no-access-log
Restart=always
RestartSec=3
MemoryMax=800M

[Install]
WantedBy=multi-user.target
EOF

cat > /etc/systemd/system/ee-worker.service <<EOF
[Unit]
Description=Earth Empire pipeline worker (analysis, X, Facebook, backups)
After=network-online.target ee-api.service
Wants=network-online.target

[Service]
User=earth
EnvironmentFile=/etc/earth-empire/env
WorkingDirectory=/var/lib/earth-empire/backend
ExecStart=$VENV/bin/python -m ee.worker
Restart=always
RestartSec=10
TimeoutStopSec=60
MemoryMax=2500M

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable ee-api ee-worker
systemctl restart ee-api ee-worker
install -m 755 $SRC/deploy/restore-state.sh /usr/local/bin/ee-restore-state
sleep 3
curl -fsS http://127.0.0.1:8000/v1/health | head -c 300; echo
