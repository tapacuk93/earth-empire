"""The X poster: the official X API v2 only (POST /2/tweets, /2/media/upload/*).

Credentials: earth-empire/x = {"api_key","api_secret","access_token","access_secret"} (OAuth 1.0a
user context) or {"bearer_user_token"} (OAuth 2.0 user token with tweet.write, media.write).

Each item becomes a thread (compose.x_thread). Every tweet id is saved in the step's detail the
moment it exists, so a retry continues the thread rather than starting it again, and an item
whose step is `posted` is never posted again.
"""
from __future__ import annotations

import json
import logging
import math
import os
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

from . import compose, config, store
from .analysis import Media, probe
from .db import j, now, setting, tx
from .logs import event, metric

API = "https://api.x.com"
CHUNK = 4 * 1024 * 1024
MAX_VIDEO_S = 140   # 2:20 for accounts without Premium


class XError(Exception):
    def __init__(self, msg, status=None, retry_after=None):
        super().__init__(msg)
        self.status, self.retry_after = status, retry_after


class XNoCredits(XError):
    """The developer account has no pay-per-use credits (or no enrolment): pause, do not retry."""


CREDITS_RE = __import__("re").compile(r"credit|CreditsDepleted|payment|billing|insufficient|"
                                      r"client-not-enrolled|spend|usage cap|UsageCapExceeded", __import__("re").I)


def credentials():
    c = config.secret("x")
    if not isinstance(c, dict) or config.is_placeholder(c):
        return None
    return c


def session(creds: dict):
    import requests
    s = requests.Session()
    if creds.get("api_key"):
        from requests_oauthlib import OAuth1
        s.auth = OAuth1(creds["api_key"], creds["api_secret"], creds["access_token"], creds["access_secret"])
    else:
        s.headers["Authorization"] = "Bearer " + creds["bearer_user_token"]
    return s


def _check(r, what):
    if r.status_code == 402 or (r.status_code in (403, 429) and CREDITS_RE.search(r.text or "")):
        raise XNoCredits(f"{what}: X API refused for billing (HTTP {r.status_code}): {r.text[:400]}", r.status_code)
    if r.status_code == 429:
        reset = r.headers.get("x-rate-limit-reset")
        wait = max(60, int(reset) - int(time.time())) if reset else 900
        raise XError(f"{what}: rate limited", 429, wait)
    if r.status_code >= 400:
        raise XError(f"{what}: HTTP {r.status_code}: {r.text[:600]}", r.status_code)
    return r.json() if r.content else {}


def prepare_video(src: Path, work: Path) -> tuple[Path, bool]:
    """H.264/AAC, at most 1280 on the long side, at most 2:20. Returns (file, trimmed?)."""
    dur = probe(src)["duration"]
    out = work / (src.stem + ".x.mp4")
    cmd = ["ffmpeg", "-v", "error", "-y", "-i", str(src), "-t", str(MAX_VIDEO_S),
           "-vf", "scale='if(gt(iw,ih),min(1280,iw),-2)':'if(gt(iw,ih),-2,min(1280,ih))',fps=fps=30",
           "-c:v", "libx264", "-preset", "veryfast", "-crf", "23", "-pix_fmt", "yuv420p", "-profile:v", "high",
           "-c:a", "aac", "-b:a", "128k", "-ac", "2", "-movflags", "+faststart", str(out)]
    p = subprocess.run(cmd, capture_output=True, text=True, timeout=900)
    if p.returncode:
        raise RuntimeError("ffmpeg (x video): " + p.stderr[-500:])
    return out, dur > MAX_VIDEO_S + 0.5


def upload(s, path: Path, mime: str, category: str) -> str:
    size = path.stat().st_size
    init = _check(s.post(f"{API}/2/media/upload/initialize", json={
        "media_type": mime, "total_bytes": size, "media_category": category}, timeout=60), "media init")
    mid = init["data"]["id"]
    with open(path, "rb") as f:
        for i in range(math.ceil(size / CHUNK) or 1):
            chunk = f.read(CHUNK)
            for attempt in range(3):
                r = s.post(f"{API}/2/media/upload/{mid}/append", data={"segment_index": str(i)},
                           files={"media": ("chunk", chunk, "application/octet-stream")}, timeout=300)
                if r.status_code < 300:
                    break
                if attempt == 2:
                    _check(r, f"media append {i}")
                time.sleep(5 * (attempt + 1))
    fin = _check(s.post(f"{API}/2/media/upload/{mid}/finalize", timeout=120), "media finalize")
    info = (fin.get("data") or {}).get("processing_info")
    deadline = time.time() + 900
    while info and info.get("state") in ("pending", "in_progress"):
        if time.time() > deadline:
            raise XError("media processing took over 15 minutes")
        time.sleep(max(2, info.get("check_after_secs", 5)))
        st = _check(s.get(f"{API}/2/media/upload", params={"command": "STATUS", "media_id": mid}, timeout=60),
                    "media status")
        info = (st.get("data") or {}).get("processing_info")
    if info and info.get("state") == "failed":
        raise XError(f"media processing failed: {info.get('error')}")
    return mid


def plan(c, item_id: str) -> dict:
    row = c.execute("SELECT * FROM items WHERE id=?", (item_id,)).fetchone()
    item = store.render_item(c, row)
    post = compose.build(item)
    thread = compose.x_thread(post)
    return {"item": item_id, "taken_at": item["taken_at"], "post": post, "thread": thread}


def describe(p: dict) -> str:
    lines = [f"=== {p['item']} ({p['taken_at']}) - {len(p['thread'])} tweet(s)"]
    for i, t in enumerate(p["thread"]):
        media = [p["post"].media[k] for k in t["media"]]
        lines.append(f"--- tweet {i + 1} [{compose.x_len(t['text'])}/280]"
                     + (f" media: {[m['type'] + ' ' + m['url'].rsplit('/', 1)[-1] for m in media]}" if media else ""))
        lines.append(t["text"])
    return "\n".join(lines)


def post_item(c, item_id: str, *, dry_run: bool) -> dict:
    p = plan(c, item_id)
    if dry_run:
        text = describe(p)
        print(text)
        event("x.dry_run", item=item_id, tweets=len(p["thread"]))
        return {"dry_run": True, "tweets": len(p["thread"])}
    creds = credentials()
    if not creds:
        raise XError("earth-empire/x holds no credentials yet")
    step = c.execute("SELECT detail FROM steps WHERE item_id=? AND step='x'", (item_id,)).fetchone()
    detail = json.loads(step["detail"]) if step and step["detail"] else {}
    done: list[str] = detail.get("tweet_ids") or []
    s = session(creds)
    work = Path(tempfile.mkdtemp(prefix="ee-x-"))
    try:
        media_ids: dict[int, str] = {int(k): v for k, v in (detail.get("media_ids") or {}).items()}
        fetch = Media(work)
        for i, t in enumerate(p["thread"]):
            if i < len(done):
                continue   # already posted on an earlier attempt
            ids = []
            for k in t["media"]:
                if k not in media_ids:
                    m = p["post"].media[k]
                    src = fetch.fetch(m["url"], f"x{k}{Path(m['url']).suffix or '.bin'}")
                    if m["type"] == "video":
                        vid, trimmed = prepare_video(src, work)
                        media_ids[k] = upload(s, vid, "video/mp4", "tweet_video")
                        if trimmed:
                            event("x.video_trimmed", item=item_id, media=k)
                    else:
                        mime = {".png": "image/png", ".webp": "image/webp"}.get(src.suffix.lower(), "image/jpeg")
                        media_ids[k] = upload(s, src, mime, "tweet_image")
                    detail["media_ids"] = {str(a): b for a, b in media_ids.items()}
                    store.set_step(c, item_id, "x", "running", detail=detail)
                ids.append(media_ids[k])
            body: dict = {}
            if t["text"]:
                body["text"] = t["text"]
            if ids:
                body["media"] = {"media_ids": ids}
            if done:
                body["reply"] = {"in_reply_to_tweet_id": done[-1]}
            r = _check(s.post(f"{API}/2/tweets", json=body, timeout=60), f"tweet {i + 1}")
            done.append(r["data"]["id"])
            detail["tweet_ids"] = done
            store.set_step(c, item_id, "x", "running", detail=detail)
            event("x.tweet", item=item_id, n=i + 1, of=len(p["thread"]), tweet=done[-1])
            metric("XPosts")
            time.sleep(3)
        url = f"https://x.com/i/status/{done[0]}"
        store.set_step(c, item_id, "x", "posted", remote_id=done[0], remote_url=url, detail=detail,
                       note=f"{len(done)} tweet(s)")
        return {"posted": url, "tweets": len(done)}
    finally:
        shutil.rmtree(work, ignore_errors=True)
