"""Configuration: plain settings from the environment, secrets from AWS Secrets Manager.

On the box the environment comes from /etc/earth-empire/env. Locally, export what a test needs;
for secrets, EE_SECRET_<NAME> (e.g. EE_SECRET_INGEST_TOKEN) overrides Secrets Manager so tests
never need AWS.
"""
from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path


def env(name: str, default: str | None = None) -> str | None:
    return os.environ.get(name, default)


DATA_DIR = Path(env("EE_DATA_DIR", "/var/lib/earth-empire/backend"))
DB_PATH = Path(env("EE_DB", str(DATA_DIR / "earth-empire.sqlite3")))
REGION = env("AWS_REGION", "us-east-1")
MEDIA_BUCKET = env("EE_MEDIA_BUCKET", "earth-empire-media")
BACKUP_BUCKET = env("EE_BACKUP_BUCKET", "earth-empire-backups")
# Where media is served from now; URLs are built from it on every response.
MEDIA_BASE_URL = env("EE_MEDIA_BASE_URL", "https://media.empire.earth").rstrip("/")
# Every host a stored media URL may carry; any of them is reduced to a key on ingest.
MEDIA_HOSTS = [h for h in (env("EE_MEDIA_HOSTS", "") or "").split(",") if h] + [
    "media.empire.earth",
    f"{MEDIA_BUCKET}.s3.amazonaws.com",
    f"{MEDIA_BUCKET}.s3.{REGION}.amazonaws.com",
]
PUBLIC_API_URL = env("EE_PUBLIC_API_URL", "https://api.empire.earth")
LOG_GROUP = env("EE_LOG_GROUP", "/earth-empire")
CLOUDWATCH = env("EE_CLOUDWATCH", "0") == "1"   # ship logs and metrics (on the box)

SECRET_NAMES = {
    "ingest_token": "earth-empire/ingest-token",
    "admin_token": "earth-empire/admin-token",
    "claude": "earth-empire/claude",
    "x": "earth-empire/x",
    "facebook_session": "earth-empire/facebook-session",
    "instagram": "earth-empire/instagram",
    "target": "earth-empire/target",
}

_cache: dict[str, tuple[float, object]] = {}
_lock = threading.Lock()
_TTL = 300


def secret(key: str, *, fresh: bool = False):
    """A secret's value: parsed JSON when it is JSON, else the string. None when absent."""
    override = os.environ.get("EE_SECRET_" + key.upper())
    if override is not None:
        try:
            return json.loads(override)
        except ValueError:
            return override
    name = SECRET_NAMES[key]
    with _lock:
        hit = _cache.get(name)
        if hit and not fresh and time.time() - hit[0] < _TTL:
            return hit[1]
    import boto3
    from botocore.exceptions import ClientError
    try:
        raw = boto3.client("secretsmanager", region_name=REGION).get_secret_value(SecretId=name)["SecretString"]
    except ClientError as e:
        if e.response["Error"]["Code"] == "ResourceNotFoundException":
            return None
        raise
    try:
        value = json.loads(raw)
    except ValueError:
        value = raw
    with _lock:
        _cache[name] = (time.time(), value)
    return value


def is_placeholder(value) -> bool:
    if value is None:
        return True
    if isinstance(value, dict):
        return bool(value.get("placeholder")) or "PLACEHOLDER" in json.dumps(value)
    return "PLACEHOLDER" in str(value)


def put_secret(key: str, value) -> None:
    import boto3
    boto3.client("secretsmanager", region_name=REGION).put_secret_value(
        SecretId=SECRET_NAMES[key], SecretString=json.dumps(value) if not isinstance(value, str) else value)
    with _lock:
        _cache.pop(SECRET_NAMES[key], None)
