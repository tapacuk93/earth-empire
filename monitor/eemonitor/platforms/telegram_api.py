"""Telegram's own API (MTProto, Telethon - MIT) for public channel videos the t.me/s/ preview does
not serve (it inlines only small files).

Credentials: earth-empire/telegram {"api_id", "api_hash"} and the user session string in
earth-empire/telegram-session, made once by the owner on the Mac with
monitor/deploy/telegram-login.py (phone + code typed by the owner; never automated here).

Read-only, public channels only: the monitor reads one message of a public channel and downloads
its video, nothing else. FloodWait is honoured: a wait Telegram asks for is slept (plus jitter) when
short, and pauses Telegram API use when long. A daily cap bounds downloads.
"""
from __future__ import annotations

import json
import logging
import os
import random
import time
from pathlib import Path

from .. import db, pace
from .youtube import Blocked

log = logging.getLogger("ee.monitor.telegram_api")
_cache: dict = {}


def _secret(name: str):
    import boto3
    from botocore.exceptions import ClientError
    try:
        raw = boto3.client("secretsmanager", region_name=os.environ.get("AWS_REGION", "us-east-1")) \
            .get_secret_value(SecretId=name)["SecretString"]
    except ClientError:
        return None
    try:
        return json.loads(raw)
    except ValueError:
        return raw


def credentials() -> tuple[int, str, str] | None:
    """(api_id, api_hash, session string), cached ten minutes; None until the owner has logged in."""
    if os.environ.get("EE_TELEGRAM_API") == "off":
        return None
    hit = _cache.get("creds")
    if hit and time.time() - hit[0] < 600:
        return hit[1]
    app = _secret("earth-empire/telegram") or {}
    sess = _secret("earth-empire/telegram-session")
    if isinstance(sess, dict):
        sess = sess.get("session") or sess.get("value")
    val = None
    if isinstance(app, dict) and app.get("api_id") and app.get("api_hash") and isinstance(sess, str) and len(sess) > 50:
        val = (int(app["api_id"]), str(app["api_hash"]), sess)
    _cache["creds"] = (time.time(), val)
    return val


def session_exists() -> bool:
    return credentials() is not None


def download(c, post: str, dest: Path, max_bytes: int = 600 << 20) -> Path:
    """Download the video of https://t.me/<post> ("channel/123") to dest."""
    creds = credentials()
    if not creds:
        raise pace.Stop("telegram_api", "login", "no Telegram session yet: the owner runs monitor/deploy/telegram-login.py")
    cap = db.fsetting(c, "telegram_api.daily_downloads") if c is not None else 0
    if c is not None:
        st = db.stopped(c, "telegram_api")
        if st:
            raise pace.Stop("telegram_api", st["kind"], st["message"] or "")
        if cap and db.used(c, "req.telegram_api") >= cap:
            raise pace.Stop("telegram_api", "cap", f"daily cap of {cap:.0f} Telegram API downloads reached")
        db.add_usage(c, "req.telegram_api")
    channel, msg_id = post.split("/")[0], int(post.split("/")[1].split("?")[0])
    from telethon.errors import ChannelPrivateError, FloodWaitError, UsernameInvalidError, UsernameNotOccupiedError
    from telethon.sessions import StringSession
    from telethon.sync import TelegramClient
    time.sleep(random.uniform(3, 9))   # jitter between API sessions
    client = TelegramClient(StringSession(creds[2]), creds[0], creds[1], flood_sleep_threshold=0,
                            device_model="earth-empire monitor", receive_updates=False)
    try:
        for attempt in range(3):
            try:
                client.connect()
                if not client.is_user_authorized():
                    raise pace.Stop("telegram_api", "login", "the Telegram session is no longer authorized; "
                                                             "run monitor/deploy/telegram-login.py again")
                entity = client.get_entity(channel)
                if not getattr(entity, "broadcast", False) or not getattr(entity, "username", None):
                    raise Blocked(f"{channel} is not a public channel")
                msg = client.get_messages(entity, ids=msg_id)
                if not msg or not msg.media:
                    raise pace.HTTPFail(404, f"no media in {post}")
                size = getattr(getattr(msg, "document", None), "size", 0) or 0
                if size > max_bytes:
                    raise pace.Stop("telegram_api", "too_large", f"{post} is {size >> 20} MB")
                out = client.download_media(msg, file=str(dest))
                if not out:
                    raise pace.HTTPFail(404, f"{post}: nothing downloaded")
                return Path(out)
            except FloodWaitError as e:
                wait = int(e.seconds) + random.uniform(5, 30)
                if wait > 900:
                    raise pace.Stop("telegram_api", "rate_limit", f"FloodWait {e.seconds}s") from None
                log.warning("Telegram FloodWait %ss; sleeping %.0fs", e.seconds, wait)
                time.sleep(wait)
            except (ChannelPrivateError, UsernameInvalidError, UsernameNotOccupiedError) as e:
                raise Blocked(f"{channel}: {type(e).__name__}") from None
        raise pace.Stop("telegram_api", "rate_limit", "still flood-limited after waiting")
    finally:
        try:
            client.disconnect()
        except Exception:  # noqa: BLE001
            pass
