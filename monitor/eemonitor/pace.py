"""Gentle requests: a random gap between requests to one platform, a daily cap, exponential
backoff on 429 / 5xx, and a stop (recorded in `stops`, logged) on anything that looks like a
warning, a checkpoint or a billing refusal. A stopped platform is not touched until the owner
clears it (`ee-monitor resume <platform>`) or, for rate limits, until its pause ends.
"""
from __future__ import annotations

import logging
import random
import time

from . import db

log = logging.getLogger("ee.monitor.pace")

GAPS = {  # seconds between two requests to the same platform (min, max), before jitter pauses
    "telegram": (4, 10), "youtube": (3, 8), "x": (5, 12), "instagram": (8, 20), "facebook": (8, 22), "tiktok": (12, 30),
    "media": (1, 3),
}
BACKOFF = (60, 300, 1200)


class Stop(Exception):
    """The platform must not be used now. kind: checkpoint | login | rate_limit | billing | cap | blocked."""

    def __init__(self, platform: str, kind: str, msg: str):
        super().__init__(f"{platform}: {kind}: {msg}")
        self.platform, self.kind, self.msg = platform, kind, msg


_last: dict[str, float] = {}
_count: dict[str, int] = {}


def wait(c, platform: str) -> None:
    """Before one request: refuse when stopped or over the daily cap, else sleep a jittered gap."""
    if c is not None:
        st = db.stopped(c, platform)
        if st:
            raise Stop(platform, st["kind"], st["message"] or "")
        cap = db.fsetting(c, f"{platform}.daily_requests") if platform != "media" else 0
        if cap and db.used(c, f"req.{platform}") >= cap:
            raise Stop(platform, "cap", f"daily cap of {cap:.0f} requests reached")
    lo, hi = GAPS.get(platform, (3, 8))
    gap = random.uniform(lo, hi)
    n = _count.get(platform, 0)
    if n and n % random.randint(15, 25) == 0:
        gap += random.uniform(30, 120)   # a longer pause now and then
    delay = gap - (time.monotonic() - _last.get(platform, 0))
    if delay > 0:
        time.sleep(delay)
    _last[platform] = time.monotonic()
    _count[platform] = n + 1
    if c is not None and platform != "media":
        db.add_usage(c, f"req.{platform}")


def halt(c, e: Stop) -> None:
    """Record and log a stop. Rate limits pause for an hour; everything else until the owner clears it."""
    # rate limits pause an hour; a missing Instagram session is looked at again every 3 hours (it
    # appears when the owner logs the collector in); everything else waits for the owner
    seconds = 3600 if e.kind == "rate_limit" else 3 * 3600 if (e.kind == "login" and e.platform in ("instagram", "tiktok")) \
        else 24 * 3600 if e.kind == "cap" else None
    if e.kind == "cap":
        return  # a cap is not a stop; it resets at midnight UTC
    if c is not None:
        db.stop(c, e.platform, e.kind, e.msg, seconds)
    log.warning("STOPPED %s (%s): %s", e.platform, e.kind, e.msg)
    try:
        from .worker import heartbeat
        heartbeat(c, f"{e.platform} paused ({e.kind})", "stop", ok=False, error=f"{e.platform}: {e.msg}")
    except Exception:  # noqa: BLE001
        pass


def get(c, platform: str, url: str, *, headers: dict | None = None, timeout: float = 30, stream_to=None,
        max_bytes: int | None = None):
    """GET with pacing and backoff. Returns the httpx response (or the path written, with stream_to)."""
    import httpx
    h = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
                       "Chrome/141.0.0.0 Safari/537.36", "Accept-Language": "en-US,en;q=0.8"}
    h.update(headers or {})
    for attempt in range(len(BACKOFF) + 1):
        wait(c, platform)
        try:
            if stream_to:
                with httpx.stream("GET", url, headers=h, timeout=timeout, follow_redirects=True) as r:
                    if r.status_code == 200:
                        size = 0
                        with open(stream_to, "wb") as f:
                            for chunk in r.iter_bytes(1 << 16):
                                size += len(chunk)
                                if max_bytes and size > max_bytes:
                                    raise Stop(platform, "too_large", f"{url[:80]} is over {max_bytes >> 20} MB")
                                f.write(chunk)
                        return stream_to
                    status, text = r.status_code, r.read()[:500].decode(errors="replace")
            else:
                r = httpx.get(url, headers=h, timeout=timeout, follow_redirects=True)
                if r.status_code == 200:
                    return r
                status, text = r.status_code, r.text[:500]
        except httpx.HTTPError as e:
            status, text = 0, repr(e)
        if status in (429, 0) or status >= 500:
            if attempt < len(BACKOFF):
                pause = BACKOFF[attempt] * random.uniform(1.0, 1.5)
                log.warning("%s GET %s -> %s; backing off %.0fs", platform, url[:100], status or text[:80], pause)
                time.sleep(pause)
                continue
            raise Stop(platform, "rate_limit" if status == 429 else "error", f"HTTP {status} after backoff: {text[:200]}")
        raise HTTPFail(status, text)
    raise Stop(platform, "error", "unreachable")


class HTTPFail(Exception):
    def __init__(self, status, text):
        super().__init__(f"HTTP {status}: {text[:200]}")
        self.status = status
