#!/bin/sh
# Create or update the stack. Keeps the CertificateArn the stack already has unless one is given:
#   backend/infra/deploy.sh [certificate-arn]
set -eu
export AWS_REGION=us-east-1
cd "$(dirname "$0")"
CERT=${1:-$(aws cloudformation describe-stacks --stack-name earth-empire \
  --query "Stacks[0].Parameters[?ParameterKey=='CertificateArn'].ParameterValue" --output text 2>/dev/null || true)}
[ "$CERT" = "None" ] && CERT=""
aws cloudformation deploy --stack-name earth-empire --template-file stack.yaml \
  --capabilities CAPABILITY_NAMED_IAM --tags project=earth-empire --no-fail-on-empty-changeset \
  --parameter-overrides "CertificateArn=$CERT"
aws cloudformation describe-stacks --stack-name earth-empire --query 'Stacks[0].Outputs' --output table
