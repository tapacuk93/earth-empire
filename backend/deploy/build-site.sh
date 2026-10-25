#!/bin/bash
# On the box (as earth): build web/ against the live API and publish it with deploy-site.sh.
# The worker runs this when items have gone public since the last build; by hand: sudo -u earth
# bash /opt/earth-empire/repo/backend/deploy/build-site.sh
set -euo pipefail
set -a; . /etc/earth-empire/env; set +a
export PATH=/opt/earth-empire/node/bin:$PATH
SRC=/opt/earth-empire/repo/web
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
VITE_API_BASE=${EE_PUBLIC_API_URL:-https://api.empire.earth} npm run build --silent
bash /opt/earth-empire/repo/backend/deploy/deploy-site.sh "$BUILD/src/dist"
