"""YouTube: listing through the channel's public RSS feed (no key), or the Data API v3 when a key
is in the secret earth-empire/youtube ({"api_key"}) - it pages further back than the feed's 15.

Audio: YouTube has no official media API. yt-dlp reads public videos the way a browser does;
that is against YouTube's terms of service for automated downloading, which is why it is the
only platform where the monitor uses it, only for public videos, audio only, deleted after
transcription. From AWS addresses YouTube answers "Sign in to confirm you're not a bot"; the video
is then recorded as `blocked` with that reason (see monitor/README.md for the options).
"""
from __future__ import annotations

import re
import subprocess
from pathlib import Path

from .. import pace

FEED = "https://www.youtube.com/feeds/videos.xml?channel_id="


def parse_feed(xml: str) -> list[dict]:
    out = []
    for e in re.findall(r"<entry>(.*?)</entry>", xml, re.S):
        vid = re.search(r"<yt:videoId>([^<]+)", e)
        if not vid:
            continue
        title = re.search(r"<title>([^<]*)</title>", e)
        pub = re.search(r"<published>([^<]+)</published>", e)
        import html
        from datetime import datetime, timezone
        posted = (datetime.fromisoformat(pub.group(1)).astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
                  if pub else None)
        v = vid.group(1)
        is_short = "/shorts/" in e
        out.append({"id": f"yt:{v}", "platform": "youtube",
                    "url": f"https://www.youtube.com/{'shorts/' + v if is_short else 'watch?v=' + v}",
                    "media_url": None, "title": html.unescape(title.group(1)) if title else None,
                    "posted_at": posted, "duration": None,
                    "thumbnail": f"https://i.ytimg.com/vi/{v}/hqdefault.jpg", "blocked": None,
                    "extra": {"video_id": v}})
    return out


def api_key():
    try:
        from ee import config
        s = config.secret("youtube") if "youtube" in config.SECRET_NAMES else None
    except Exception:  # noqa: BLE001
        s = None
    if s is None:
        try:
            import boto3
            import json
            raw = boto3.client("secretsmanager", region_name="us-east-1").get_secret_value(
                SecretId="earth-empire/youtube")["SecretString"]
            s = json.loads(raw)
        except Exception:  # noqa: BLE001 - no key: the feed is used
            return None
    return (s or {}).get("api_key") if isinstance(s, dict) else None


def list_videos(c, account: dict, before: str | None = None) -> tuple[list[dict], str | None]:
    cid = account.get("platform_id") or account["handle"]
    key = api_key()
    if key:
        import httpx
        pace.wait(c, "youtube")
        uploads = "UU" + cid[2:]
        q = {"part": "snippet,contentDetails", "playlistId": uploads, "maxResults": 25, "key": key}
        if before:
            q["pageToken"] = before
        r = httpx.get("https://www.googleapis.com/youtube/v3/playlistItems", params=q, timeout=30)
        if r.status_code == 403 and "quota" in r.text.lower():
            raise pace.Stop("youtube", "cap", "Data API quota exhausted for today")
        r.raise_for_status()
        d = r.json()
        out = []
        for it in d.get("items", []):
            v = it["contentDetails"]["videoId"]
            sn = it["snippet"]
            out.append({"id": f"yt:{v}", "platform": "youtube", "url": f"https://www.youtube.com/watch?v={v}",
                        "media_url": None, "title": sn.get("title"),
                        "posted_at": (it["contentDetails"].get("videoPublishedAt") or sn.get("publishedAt")),
                        "duration": None, "thumbnail": f"https://i.ytimg.com/vi/{v}/hqdefault.jpg",
                        "blocked": None, "extra": {"video_id": v}})
        return out, d.get("nextPageToken")
    if before:
        return [], None   # the feed has only the newest 15
    r = pace.get(c, "youtube", FEED + cid)
    return parse_feed(r.text), None


BOT_RE = re.compile(r"confirm you.re not a bot|Sign in to confirm|HTTP Error 429|This video is unavailable"
                    r"|Private video|members-only", re.I)


def download_audio(c, video: dict, work: Path, ytdlp: str) -> Path:
    pace.wait(c, "youtube")
    out = work / "yt.%(ext)s"
    p = subprocess.run([ytdlp, "-q", "--no-warnings", "--no-playlist", "-f", "bestaudio[abr<=96]/bestaudio/best",
                        "--max-filesize", "200M", "-o", str(out), video["url"]],
                       capture_output=True, text=True, timeout=1800)
    files = [f for f in work.glob("yt.*") if not f.name.endswith(".part")]
    if p.returncode != 0 or not files:
        msg = (p.stderr or p.stdout or "").strip()[-400:]
        if BOT_RE.search(msg):
            raise Blocked("YouTube refused this address (" + msg.split("ERROR:")[-1].strip()[:160] + ")")
        raise RuntimeError(f"yt-dlp failed: {msg}")
    return files[0]


class Blocked(Exception):
    pass
