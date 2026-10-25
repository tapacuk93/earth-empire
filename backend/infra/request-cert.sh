#!/bin/sh
# Request (or find) the one ACM certificate for empire.earth, www, media and api in us-east-1,
# and write its DNS validation records into the zone. Idempotent. ACM issues it on its own once
# the domain's nameservers point at the zone; finish-domains.sh then attaches it.
set -eu
export AWS_REGION=us-east-1
DOMAIN=empire.earth
ZONE=$(aws route53 list-hosted-zones-by-name --dns-name $DOMAIN \
  --query "HostedZones[?Name=='$DOMAIN.'].Id" --output text | sed 's|/hostedzone/||')
[ -n "$ZONE" ] || { echo "no hosted zone for $DOMAIN - deploy the stack first" >&2; exit 1; }

ARN=$(aws acm list-certificates --certificate-statuses PENDING_VALIDATION ISSUED \
  --query "CertificateSummaryList[?DomainName=='$DOMAIN'].CertificateArn | [0]" --output text)
if [ "$ARN" = "None" ] || [ -z "$ARN" ]; then
  ARN=$(aws acm request-certificate --domain-name $DOMAIN \
    --subject-alternative-names www.$DOMAIN media.$DOMAIN api.$DOMAIN \
    --validation-method DNS --idempotency-token earthempire1 \
    --tags Key=project,Value=earth-empire --query CertificateArn --output text)
  echo "requested $ARN"
  sleep 10   # the validation records take a moment to appear
fi
echo "certificate: $ARN"

aws acm describe-certificate --certificate-arn "$ARN" \
  --query 'Certificate.DomainValidationOptions[].ResourceRecord' --output json |
python3 -c '
import json, sys
recs = {(r["Name"], r["Value"]) for r in json.load(sys.stdin) if r}
print(json.dumps({"Changes": [{"Action": "UPSERT", "ResourceRecordSet": {
    "Name": n, "Type": "CNAME", "TTL": 300, "ResourceRecords": [{"Value": v}]}} for n, v in sorted(recs)]}))
' > /tmp/ee-validation.json
aws route53 change-resource-record-sets --hosted-zone-id "$ZONE" --change-batch file:///tmp/ee-validation.json \
  --query ChangeInfo.Status --output text
rm -f /tmp/ee-validation.json
aws acm describe-certificate --certificate-arn "$ARN" --query Certificate.Status --output text
