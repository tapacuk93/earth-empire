#!/bin/bash
# Runs the collector on this Mac (where the Instagram session was created) instead of the box.
#
#   collector/deploy/mac/install.sh            install or update, and make the Mac the runner
#   collector/deploy/mac/install.sh --run      one incremental run now, in the foreground
#   collector/deploy/mac/install.sh --uninstall  stop here and hand the collector back to the box
#
# Everything lives in ~/Library/Application Support/earth-empire/collector (mode 700): the code
# copy, a venv, state.sqlite, the browser profile and logs. Uses the Playwright Chromium already in
# ~/Library/Caches/ms-playwright. Secrets come from Secrets Manager with this Mac's AWS credentials.
# The SSM parameter /earth-empire/collector/runner says which machine may touch Instagram, so the
# box and the Mac never use the session at the same time.
set -euo pipefail

SRC=$(cd "$(dirname "$0")/../.." && pwd)            # .../collector
APP="$HOME/Library/Application Support/earth-empire/collector"
AGENTS="$HOME/Library/LaunchAgents"
LABEL=com.oeaio.earthempire.collector
HB_LABEL=com.oeaio.earthempire.collector-heartbeat
REGION=us-east-1
PARAM=/earth-empire/collector/runner

set_runner() {
  aws ssm put-parameter --region $REGION --name $PARAM --type String --overwrite --value "$1" >/dev/null
  echo "runner: $1"
}

case "${1:-}" in
  --uninstall)
    launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true
    launchctl bootout "gui/$(id -u)/$HB_LABEL" 2>/dev/null || true
    rm -f "$AGENTS/$LABEL.plist" "$AGENTS/$HB_LABEL.plist"
    set_runner box
    echo "launchd agents removed; state kept in $APP"
    exit 0;;
  --run)
    exec "$APP/run.sh" incremental "${@:2}";;
esac

install -d -m 700 "$APP" "$APP/state" "$APP/browser" "$APP/logs"
rsync -a --delete --exclude __pycache__ "$SRC/eecollector/" "$APP/app/eecollector/"
cp "$SRC/requirements.txt" "$APP/app/requirements.txt"
[ -x "$APP/venv/bin/python" ] || python3 -m venv "$APP/venv"
"$APP/venv/bin/pip" install -q --disable-pip-version-check -r "$APP/app/requirements.txt"
# the Chromium build this Playwright expects must already be in the cache (no big download here)
"$APP/venv/bin/python" -m playwright install --dry-run chromium | grep -q "Install location" || true
ls -d "$HOME/Library/Caches/ms-playwright"/chromium-* >/dev/null

cat > "$APP/run.sh" <<EOT
#!/bin/bash
# launchd entry point: ee-collector for the Mac runner
export EE_RUNNER=mac
export EE_API_URL=https://api.empire.earth
export AWS_REGION=$REGION
export EE_STATE_DIR="$APP/state"
export EE_BROWSER_PROFILE="$APP/browser/instagram"
export EE_LOG_DIR="$APP/logs"
export EE_TIMEZONE=\$(readlink /etc/localtime | sed 's#.*/zoneinfo/##')
export PLAYWRIGHT_BROWSERS_PATH="$HOME/Library/Caches/ms-playwright"
export PYTHONPATH="$APP/app"
export PYTHONUNBUFFERED=1
export PATH=/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin
exec "$APP/venv/bin/python" -m eecollector "\$@"
EOT
chmod 700 "$APP/run.sh"

plist() {  # label, interval seconds, command
  cat > "$AGENTS/$1.plist" <<EOT
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>$1</string>
  <key>ProgramArguments</key><array><string>$APP/run.sh</string><string>$3</string></array>
  <key>StartInterval</key><integer>$2</integer>
  <key>RunAtLoad</key><false/>
  <key>LowPriorityIO</key><true/>
  <key>Nice</key><integer>5</integer>
  <key>StandardOutPath</key><string>$APP/logs/launchd-$3.log</string>
  <key>StandardErrorPath</key><string>$APP/logs/launchd-$3.log</string>
</dict></plist>
EOT
  launchctl bootout "gui/$(id -u)/$1" 2>/dev/null || true
  launchctl bootstrap "gui/$(id -u)" "$AGENTS/$1.plist"
}
mkdir -p "$AGENTS"
plist $LABEL 2700 incremental       # every 45 min while the Mac is awake (stories live 24 h)
plist $HB_LABEL 300 heartbeat       # /v1/status between runs
set_runner mac
echo "installed in $APP; first run: $0 --run"
