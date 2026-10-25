#!/bin/bash
# The box's base system (CONTRACT.md "The box"). Run as root; idempotent. The first boot runs it
# from user data, and every deploy runs it again (deploy-box.sh) before the parts' installers.
set -euxo pipefail
export DEBIAN_FRONTEND=noninteractive
ROOT=/opt/earth-empire
REPO=$ROOT/repo

# --- packages: python, ffmpeg, nginx, the remote view (Xvfb + x11vnc + noVNC), tools
if [ ! -f /var/lib/earth-empire/.base-packages-v1 ]; then
  apt-get update
  apt-get install -y python3 python3-venv python3-pip ffmpeg nginx sqlite3 jq unzip curl git \
    xvfb x11vnc novnc websockify fonts-noto fonts-noto-color-emoji fonts-noto-cjk
  if ! command -v aws >/dev/null; then
    curl -fsSL "https://awscli.amazonaws.com/awscli-exe-linux-$(uname -m).zip" -o /tmp/awscli.zip
    unzip -q -o /tmp/awscli.zip -d /tmp && /tmp/aws/install --update && rm -rf /tmp/aws /tmp/awscli.zip
  fi
  mkdir -p /var/lib/earth-empire && touch /var/lib/earth-empire/.base-packages-v1
fi

# --- swap: headless Chromium, ffmpeg and the API share 4 GB
if [ ! -f /swapfile ]; then
  fallocate -l 4G /swapfile && chmod 600 /swapfile && mkswap /swapfile
  echo '/swapfile none swap sw 0 0' >> /etc/fstab
fi
swapon --show | grep -q /swapfile || swapon /swapfile

# --- the user, the directories
id earth >/dev/null 2>&1 || useradd --system --create-home --home-dir /var/lib/earth-empire --shell /bin/bash earth
install -d -o earth -g earth -m 755 $ROOT /var/lib/earth-empire
install -d -o earth -g earth -m 700 /var/lib/earth-empire/browser
install -d -o earth -g earth -m 755 $ROOT/ms-playwright
chown -R earth:earth $ROOT/ms-playwright   # shared by every part, all running as earth
install -d -m 755 /etc/earth-empire
chown -R earth:earth $REPO

# --- config not in git; deploy-box.sh fills the hostnames from the stack's outputs
if [ ! -f /etc/earth-empire/env ]; then
  cat > /etc/earth-empire/env <<'ENV'
AWS_REGION=us-east-1
AWS_DEFAULT_REGION=us-east-1
EE_API_URL=http://127.0.0.1:8000
EE_PUBLIC_API_URL=https://api.empire.earth
EE_MEDIA_BASE_URL=https://media.empire.earth
PLAYWRIGHT_BROWSERS_PATH=/opt/earth-empire/ms-playwright
EE_CLOUDWATCH=1
ENV
fi
chmod 644 /etc/earth-empire/env

# --- the remote view (fallback for a human login): display :99, VNC and noVNC on localhost only
cat > /etc/systemd/system/ee-remote-view.service <<'UNIT'
[Unit]
Description=Earth Empire remote view: Xvfb :99 + x11vnc + noVNC on 127.0.0.1:6080
After=network.target

[Service]
User=earth
Environment=DISPLAY=:99
ExecStartPre=/bin/sh -c 'rm -f /tmp/.X99-lock'
ExecStart=/bin/sh -c 'Xvfb :99 -screen 0 1366x900x24 -nolisten tcp & sleep 1; \
  x11vnc -display :99 -localhost -rfbport 5900 -forever -shared -nopw -quiet & \
  exec websockify --web /usr/share/novnc 127.0.0.1:6080 127.0.0.1:5900'
Restart=on-failure

[Install]
WantedBy=multi-user.target
UNIT
install -m 755 $REPO/backend/deploy/ee-browser-login /usr/local/bin/ee-browser-login
systemctl daemon-reload
# Started on demand only: `sudo systemctl start ee-remote-view` (see backend/README.md).

# --- the CloudWatch log group is written by the services themselves (watchtower)
echo "bootstrap done"
