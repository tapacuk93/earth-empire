"""Telegram public channels through the web preview, https://t.me/s/<channel>.

The preview is Telegram's own public, logged-out page for a public channel. It serves small videos
inline (a <video src> on Telegram's CDN); larger ones show "not supported" and need the Telegram
API (MTProto with an api_id, see monitor/README.md) - those are recorded as `blocked` with that
reason rather than fetched some other way.
"""
from __future__ import annotations

import html
import re

from .. import pace

BASE = "https://t.me/s/"

_POST = re.compile(r'<div class="tgme_widget_message_wrap.*?data-post="([^"]+)"(.*?)(?=<div class="tgme_widget_message_wrap|\Z)', re.S)


def _dur(s: str | None) -> float | None:
    if not s:
        return None
    parts = [int(p) for p in s.strip().split(":") if p.isdigit()]
    v = 0
    for p in parts:
        v = v * 60 + p
    return float(v)


def parse(page: str, handle: str) -> tuple[list[dict], str | None]:
    """Videos on one preview page, newest last as Telegram shows them, and the cursor for older ones."""
    out, ids = [], []
    for m in _POST.finditer(page):
        post, body = m.group(1), m.group(2)
        pid = post.split("/")[-1]
        if pid.isdigit():
            ids.append(int(pid))
        if "message_video" not in body and "<video" not in body:
            continue
        t = re.search(r'<time datetime="([^"]+)"', body)
        posted = None
        if t:
            from datetime import datetime, timezone
            posted = datetime.fromisoformat(t.group(1)).astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        # one post can carry several videos (an album); each <a ... video_player> block is one
        players = re.findall(r'(<a class="tgme_widget_message_video_player.*?</a>)', body, re.S) or [body]
        text = re.search(r'<div class="tgme_widget_message_text[^"]*"[^>]*>(.*?)</div>', body, re.S)
        title = html.unescape(re.sub(r"<[^>]+>", " ", text.group(1))).strip() if text else None
        for i, pl in enumerate(players):
            src = re.search(r'<video[^>]*src="([^"]+)"', pl)
            thumb = re.search(r"video_thumb\" style=\"background-image:url\('([^']+)'\)", pl)
            d = re.search(r'message_video_duration[^>]*>([^<]+)<', pl)
            href = re.search(r'href="(https://t\.me/[^"]+)"', pl)
            vid = f"tg:{post}" + (f"#{i}" if len(players) > 1 else "")
            out.append({
                "id": vid, "platform": "telegram", "url": f"https://t.me/{post}" + (f"?single" if len(players) > 1 else ""),
                "media_url": html.unescape(src.group(1)) if src else None,
                "title": (title or "")[:300] or None, "posted_at": posted, "duration": _dur(d.group(1) if d else None),
                "thumbnail": html.unescape(thumb.group(1)) if thumb else None,
                "blocked": None if src else "the Telegram preview does not serve this video (too large); "
                                            "it needs the Telegram API (an api_id, see monitor/README.md)",
                "extra": {"post": post, "index": i, "href": href.group(1) if href else None},
            })
    cursor = str(min(ids)) if ids else None
    return out, cursor


def list_videos(c, account: dict, before: str | None = None) -> tuple[list[dict], str | None]:
    url = BASE + account["handle"] + (f"?before={before}" if before else "")
    r = pace.get(c, "telegram", url)
    if 'tgme_channel_info' not in r.text and "data-post=" not in r.text:
        raise pace.HTTPFail(404, f"no public preview for {account['handle']}")
    return parse(r.text, account["handle"])


def refresh_media_url(c, video: dict) -> str | None:
    """CDN links in the preview carry a token that expires; read the post again for a fresh one."""
    post = (video.get("extra") or {}).get("post")
    if not post:
        return video.get("media_url")
    r = pace.get(c, "telegram", f"https://t.me/{post}?embed=1&mode=tme")
    vids, _ = parse(f'<div class="tgme_widget_message_wrap" data-post="{post}">' + r.text, post.split("/")[0])
    idx = (video.get("extra") or {}).get("index", 0)
    for v in vids:
        if v["extra"]["index"] == idx and v["media_url"]:
            return v["media_url"]
    return video.get("media_url")
