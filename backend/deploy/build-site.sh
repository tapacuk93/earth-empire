#!/bin/bash
# On the box (as earth): build web/ against the live API and publish it with deploy-site.sh.
# The worker runs this when items have gone public since the last build; by hand: sudo -u earth
# bash /opt/earth-empire/repo/backend/deploy/build-site.sh
set -euo pipefail
set -a; . /etc/earth-empire/env; set +a
export PATH=/opt/earth-empire/node/bin:$PATH
REPO=/opt/earth-empire/repo
SRC=$REPO/web
# Build what is on main now, never a stale checkout: fast-forward first, as the checkout's owner
# (earth). If that fails, publish nothing.
if [ "$(id -un)" = earth ]; then git_() { git -C "$REPO" "$@"; }; else git_() { sudo -u earth git -C "$REPO" "$@"; }; fi
if ! git_ fetch -q origin main || ! git_ merge -q --ff-only origin/main; then
  echo "build-site: could not fast-forward $REPO to origin/main; not publishing a stale build" >&2
  exit 3
fi
echo "build-site: building $(git_ rev-parse --short HEAD)"
BUILD=/var/lib/earth-empire/backend/site-build
[ -f "$SRC/package.json" ] || { echo "no web/ in the checkout yet"; exit 0; }
mkdir -p "$BUILD"
# A copy, so node_modules and dist never touch the repository checkout.
rsync -a --delete --exclude node_modules --exclude dist "$SRC/" "$BUILD/src/"
cd "$BUILD/src"
if ! cmp -s package-lock.json "$BUILD/package-lock.installed" 2>/dev/null; then
  rm -rf node_modules
  [ -d "$BUILD/node_modules" ] && rm -rf "$BUILD/node_modules"
fi
[ -d "$BUILD/node_modules" ] && ln -sfn "$BUILD/node_modules" node_modules
if [ ! -d node_modules ]; then
  npm ci --no-audit --no-fund --loglevel=error
  mv node_modules "$BUILD/node_modules" && ln -sfn "$BUILD/node_modules" node_modules
  cp package-lock.json "$BUILD/package-lock.installed"
fi
# The real domains; EE_REPO_ROOT lets the build copy the apps' app-link files from ios/ and android/.
EE_REPO_ROOT=/opt/earth-empire/repo SITE_URL=${EE_SITE_URL:-https://empire.earth} \
  VITE_API_BASE=${EE_PUBLIC_API_URL:-https://api.empire.earth} npm run build --silent
bash /opt/earth-empire/repo/backend/deploy/deploy-site.sh "$BUILD/src/dist"
