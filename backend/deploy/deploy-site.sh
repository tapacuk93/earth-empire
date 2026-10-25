#!/bin/sh
# Publish the web app: sync web/dist to the site bucket, then invalidate CloudFront.
#   backend/deploy/deploy-site.sh [build-dir]   (default: web/dist; build it first in web/)
# Hashed assets are cached for a year; HTML and everything unhashed for a minute.
set -eu
export AWS_REGION=us-east-1
ROOT=$(cd "$(dirname "$0")/../.." && pwd)
DIST=${1:-$ROOT/web/dist}
[ -f "$DIST/index.html" ] || { echo "no $DIST/index.html - build the site first (see web/)" >&2; exit 1; }
BUCKET=earth-empire-site
DIST_ID=$(aws cloudformation describe-stacks --stack-name earth-empire \
  --query "Stacks[0].Outputs[?OutputKey=='SiteDistributionId'].OutputValue" --output text)
# 1. hashed assets (name-<hash>.ext under assets/), immutable
aws s3 sync "$DIST" "s3://$BUCKET" --exclude '*' --include 'assets/*' \
  --cache-control 'public, max-age=31536000, immutable' --only-show-errors
# 2. everything else, short cache; delete what the build no longer has
aws s3 sync "$DIST" "s3://$BUCKET" --exclude 'assets/*' --cache-control 'public, max-age=60' \
  --delete --only-show-errors
aws s3 sync "$DIST" "s3://$BUCKET" --delete --only-show-errors   # removes stale assets too
ID=$(aws cloudfront create-invalidation --distribution-id "$DIST_ID" --paths '/*' --query Invalidation.Id --output text)
echo "synced $DIST -> s3://$BUCKET; invalidation $ID"
