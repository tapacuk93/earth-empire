#!/bin/sh
# Create every Earth Empire secret that does not exist yet, with a placeholder value. Never
# overwrites an existing secret. The ingest token is generated here, in AWS, and never printed.
set -eu
export AWS_REGION=us-east-1
create() { # create <name> <description> <json value>
  if aws secretsmanager describe-secret --secret-id "$1" >/dev/null 2>&1; then
    echo "exists   $1"
  else
    aws secretsmanager create-secret --name "$1" --description "$2" --secret-string "$3" \
      --tags Key=project,Value=earth-empire >/dev/null
    echo "created  $1"
  fi
}
create earth-empire/instagram "Downloader account: {username, password, totp_secret?}" \
  '{"username":"PLACEHOLDER","password":"PLACEHOLDER"}'
create earth-empire/target "The archived account: {username}" '{"username":"PLACEHOLDER"}'
if ! aws secretsmanager describe-secret --secret-id earth-empire/ingest-token >/dev/null 2>&1; then
  TOKEN=$(aws secretsmanager get-random-password --password-length 48 --exclude-punctuation \
    --query RandomPassword --output text)
  create earth-empire/ingest-token "Bearer token the collector sends to /v1/ingest" "$TOKEN"
  unset TOKEN
else
  echo "exists   earth-empire/ingest-token"
fi
if ! aws secretsmanager describe-secret --secret-id earth-empire/admin-token >/dev/null 2>&1; then
  TOKEN=$(aws secretsmanager get-random-password --password-length 40 --exclude-punctuation \
    --query RandomPassword --output text)
  create earth-empire/admin-token "The owner's token for owner-only API endpoints, entered once in the apps" "$TOKEN"
  unset TOKEN
else
  echo "exists   earth-empire/admin-token"
fi
create earth-empire/x "X API, OAuth 1.0a user context: {api_key, api_secret, access_token, access_secret}" \
  '{"placeholder":true}'
create earth-empire/facebook-session "Playwright storageState JSON of the owner's Facebook login" \
  '{"placeholder":true}'
create earth-empire/claude "How the backend reaches Claude: aicoin proxy + server wallet (generated on the box)" \
  '{"placeholder":true,"proxy_url":"https://proxy.aicoin.oeaio.com","model":"claude-sonnet-5-5"}'
