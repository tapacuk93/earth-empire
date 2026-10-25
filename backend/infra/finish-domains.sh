#!/bin/sh
# Once the nameservers at GoDaddy point at the zone: wait for the certificate, attach
# empire.earth, www, media and api to the distributions with alias records, and move the box's
# URLs to the real names. Safe to run again.
set -eu
export AWS_REGION=us-east-1
HERE=$(cd "$(dirname "$0")" && pwd)
echo "delegation: $(dig +short NS empire.earth @1.1.1.1 | tr '\n' ' ')"
"$HERE/request-cert.sh" >/dev/null
ARN=$(aws acm list-certificates --certificate-statuses ISSUED PENDING_VALIDATION \
  --query "CertificateSummaryList[?DomainName=='empire.earth'].CertificateArn | [0]" --output text)
echo "certificate $ARN"
for i in $(seq 1 60); do
  S=$(aws acm describe-certificate --certificate-arn "$ARN" --query Certificate.Status --output text)
  [ "$S" = ISSUED ] && break
  echo "  $S - waiting (validation needs the NS switch to have propagated)"; sleep 30
done
[ "$S" = ISSUED ] || { echo "not issued yet; run this again later" >&2; exit 1; }
"$HERE/deploy.sh" "$ARN"
"$HERE/../deploy/deploy-box.sh" backend
for u in https://empire.earth/ https://www.empire.earth/ https://api.empire.earth/v1/health https://media.empire.earth/; do
  printf '%-40s %s\n' "$u" "$(curl -s -o /dev/null -w '%{http_code}' "$u")"
done
