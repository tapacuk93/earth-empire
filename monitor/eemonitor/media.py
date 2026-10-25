"""Hit clips and frames (CONTRACT.md "Monitor media"): private in S3 under monitor/clips/ and
monitor/frames/ (the media CDN refuses /monitor/ except /monitor/public/), shown to the owner as
presigned URLs valid for an hour; copied to monitor/public/<hit id>.<ext> on publish, deleted and
invalidated on unpublish.
"""
from __future__ import annotations

import logging
import os
import time

log = logging.getLogger("ee.monitor.media")
BUCKET = os.environ.get("EE_MEDIA_BUCKET", "earth-empire-media")
BASE = os.environ.get("EE_MEDIA_BASE_URL", "https://media.empire.earth").rstrip("/")
REGION = os.environ.get("AWS_REGION", "us-east-1")
EXT = {"clip": "mp3", "frame": "jpg"}
TYPES = {"clip": "audio/mpeg", "frame": "image/jpeg"}
_s3 = None


def s3():
    global _s3
    if _s3 is None:
        import boto3
        from botocore.config import Config
        _s3 = boto3.client("s3", region_name=REGION, config=Config(signature_version="s3v4"))
    return _s3


def private_key(h: dict, what: str) -> str | None:
    k = h.get(f"{what}_key")
    if k:
        return k
    old = h.get(what)   # hits saved before keys were kept: a URL on the media host
    if isinstance(old, str) and "/monitor/" in old:
        return "monitor/" + old.split("/monitor/", 1)[1]
    return None


def public_key(hit_id: str, what: str) -> str:
    return f"monitor/public/{hit_id}.{EXT[what]}"


def url(row, h: dict, what: str) -> str | None:
    key = private_key(h, what)
    if not key:
        return None
    if row["published_at"]:
        return f"{BASE}/{public_key(row['id'], what)}"
    try:
        return s3().generate_presigned_url("get_object", Params={"Bucket": BUCKET, "Key": key}, ExpiresIn=3600)
    except Exception as e:  # noqa: BLE001
        log.warning("presign %s failed: %s", key, e)
        return None


def publish(row, h: dict) -> None:
    for what in ("clip", "frame"):
        key = private_key(h, what)
        if key:
            s3().copy_object(Bucket=BUCKET, Key=public_key(row["id"], what), CopySource={"Bucket": BUCKET, "Key": key},
                             MetadataDirective="REPLACE", ContentType=TYPES[what],
                             CacheControl="public, max-age=86400")


def unpublish(row, h: dict) -> None:
    keys = [public_key(row["id"], w) for w in ("clip", "frame") if private_key(h, w)]
    for k in keys:
        try:
            s3().delete_object(Bucket=BUCKET, Key=k)
        except Exception as e:  # noqa: BLE001
            log.warning("delete %s failed: %s", k, e)
    if keys:
        invalidate([f"/monitor/public/{row['id']}.*"])


def invalidate(paths: list[str]) -> None:
    try:
        import boto3
        dist = os.environ.get("EE_MEDIA_DISTRIBUTION_ID")
        if not dist:
            outs = boto3.client("cloudformation", region_name=REGION).describe_stacks(StackName="earth-empire")["Stacks"][0]["Outputs"]
            dist = next(o["OutputValue"] for o in outs if o["OutputKey"] == "MediaDistributionId")
        boto3.client("cloudfront").create_invalidation(
            DistributionId=dist, InvalidationBatch={"Paths": {"Quantity": len(paths), "Items": paths},
                                                    "CallerReference": f"monitor-{time.time():.0f}"})
    except Exception as e:  # noqa: BLE001
        log.warning("invalidation of %s failed: %s", paths, e)
