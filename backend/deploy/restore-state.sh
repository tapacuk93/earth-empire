#!/bin/bash
# Restore every part's state on the box from s3://earth-empire-backups/state/ (see ee/backup.py).
# Run as root on the box (or through box-run.sh):
#   restore-state.sh                  the latest hourly backup
#   restore-state.sh 2026-10-25       that day's backup
#   restore-state.sh --check          download and verify only; change nothing, stop nothing
# It stops every ee-* service and timer, restores, then starts what was running.
set -euo pipefail
set -a; . /etc/earth-empire/env; set +a
EE=/opt/earth-empire/backend-venv/bin/ee
if [ "${1:-}" = "--check" ]; then
  exec sudo -E -u earth $EE restore --dry-run
fi
DATE=${1:-}
RUNNING=$(systemctl list-units --type=service --type=timer --state=active --no-legend 'ee-*' | awk '{print $1}')
echo "stopping: $RUNNING"
[ -n "$RUNNING" ] && systemctl stop $RUNNING
# Root runs the restore (it chowns the files to earth); the AWS credentials are the box role's.
$EE restore ${DATE:+--date "$DATE"} || { echo "restore failed; starting services again" >&2; }
[ -n "$RUNNING" ] && systemctl start $RUNNING
echo "started: $RUNNING"
