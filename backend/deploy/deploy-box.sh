#!/bin/bash
# Deploy to the box over SSM (no SSH): write the hostnames into /etc/earth-empire/env, pull main,
# run the base bootstrap, then <part>/deploy/install.sh for every part that has one.
#   backend/deploy/deploy-box.sh            everything
#   backend/deploy/deploy-box.sh backend    only that part's installer
set -euo pipefail
export AWS_REGION=us-east-1
PARTS=${*:-}
out() { aws cloudformation describe-stacks --stack-name earth-empire \
  --query "Stacks[0].Outputs[?OutputKey=='$1'].OutputValue" --output text; }
ID=$(out InstanceId)
CERT=$(aws cloudformation describe-stacks --stack-name earth-empire \
  --query "Stacks[0].Parameters[?ParameterKey=='CertificateArn'].ParameterValue" --output text)
if [ -n "$CERT" ] && [ "$CERT" != "None" ]; then
  API=https://api.empire.earth; MEDIA=https://media.empire.earth
else
  API=https://$(out ApiHost); MEDIA=https://$(out MediaHost)
fi
MEDIA_HOSTS=$(out MediaHost)
SITE_DIST=$(out SiteDistributionId)
MEDIA_DIST=$(out MediaDistributionId)

read -r -d '' SCRIPT <<EOF || true
set -euxo pipefail
cd /opt/earth-empire/repo
sudo -u earth git fetch -q origin main && sudo -u earth git reset -q --hard origin/main
bash backend/deploy/bootstrap.sh
f=/etc/earth-empire/env
setkv() { grep -q "^\$1=" \$f && sed -i "s|^\$1=.*|\$1=\$2|" \$f || echo "\$1=\$2" >> \$f; }
setkv EE_PUBLIC_API_URL $API
setkv EE_MEDIA_BASE_URL $MEDIA
setkv EE_MEDIA_HOSTS $MEDIA_HOSTS
setkv EE_SITE_DISTRIBUTION_ID $SITE_DIST
setkv EE_MEDIA_DISTRIBUTION_ID $MEDIA_DIST
for p in ${PARTS:-*}; do
  if [ -x "\$p/deploy/install.sh" ] || [ -f "\$p/deploy/install.sh" ]; then echo "== \$p"; bash "\$p/deploy/install.sh"; fi
done
EOF

CMD=$(aws ssm send-command --instance-ids "$ID" --document-name AWS-RunShellScript \
  --comment "earth-empire deploy" --timeout-seconds 1800 \
  --parameters "$(jq -n --arg s "$SCRIPT" '{commands: ["cat > /tmp/ee-deploy-$$.sh <<'"'"'EE_DEPLOY_EOF'"'"'\n" + $s + "\nEE_DEPLOY_EOF", "bash /tmp/ee-deploy-$$.sh"], executionTimeout: ["1800"]}')" \
  --cloud-watch-output-config CloudWatchOutputEnabled=true,CloudWatchLogGroupName=/earth-empire \
  --query Command.CommandId --output text)
echo "deploy $CMD on $ID"
while :; do
  sleep 10
  S=$(aws ssm get-command-invocation --command-id "$CMD" --instance-id "$ID" --query Status --output text 2>/dev/null || echo Pending)
  case $S in Pending|InProgress|Delayed) printf . ;; *) echo " $S"; break ;; esac
done
aws ssm get-command-invocation --command-id "$CMD" --instance-id "$ID" \
  --query '[StandardOutputContent, StandardErrorContent]' --output text | tail -40
[ "$S" = Success ]
