#!/bin/bash
# Run a shell command on the box over SSM (as root, under bash) and print its output.
#   backend/deploy/box-run.sh 'ee status'
set -euo pipefail
export AWS_REGION=us-east-1
ID=$(aws ec2 describe-instances --filters Name=tag:Name,Values=earth-empire Name=instance-state-name,Values=running \
  --query 'Reservations[0].Instances[0].InstanceId' --output text)
CMD=$(aws ssm send-command --instance-ids "$ID" --document-name AWS-RunShellScript --timeout-seconds 600 \
  --parameters "$(jq -n --arg s "$*" '{commands: ["cat > /tmp/ee-run.sh <<'"'"'EE_RUN_EOF'"'"'\n" + $s + "\nEE_RUN_EOF", "cd /tmp && bash /tmp/ee-run.sh"], executionTimeout: ["3600"]}')" \
  --query Command.CommandId --output text)
while :; do
  sleep 3
  S=$(aws ssm get-command-invocation --command-id "$CMD" --instance-id "$ID" --query Status --output text 2>/dev/null || echo Pending)
  case $S in Pending|InProgress|Delayed) ;; *) break ;; esac
done
aws ssm get-command-invocation --command-id "$CMD" --instance-id "$ID" --query StandardOutputContent --output text
ERR=$(aws ssm get-command-invocation --command-id "$CMD" --instance-id "$ID" --query StandardErrorContent --output text)
[ -n "$ERR" ] && [ "$ERR" != "None" ] && echo "--- stderr" && echo "$ERR"
[ "$S" = Success ]
