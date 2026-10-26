"""Instagram through the collector's own logged-in browser (collector/eecollector/igweb.py): its
session, its pacing (7-18 s between requests, a cap per hour, long backoff on 429) and its stop on
any checkpoint. The monitor imports that code rather than copying it, holds the same profile lock
(/var/lib/earth-empire/browser/instagram.lock, non-blocking - the collector goes first) and never
logs in by itself: until the collector's session exists, Instagram work stays queued.

What it reads:
- the accounts tapacuk93 follows (`/api/v1/friendships/<id>/following/`), as `followed` sources;
- an account's reels (`/api/v1/clips/user/`);
- around a seed reel: the reels Instagram plays after it (the /reels/<code>/ viewer, whose JSON the
  page loads while scrolling) and the author's other reels - `recommended`, `via` the seed.
"""
from __future__ import annotations

import logging
import os
import sys
import time
from pathlib import Path

from .. import pace

log = logging.getLogger("ee.monitor.instagram")
COLLECTOR = Path(os.environ.get("EE_COLLECTOR_SRC", "/opt/earth-empire/repo/collector"))
if str(COLLECTOR) not in sys.path:
    sys.path.insert(0, str(COLLECTOR))


def to_video(m: dict, parse) -> dict | None:
    """A v1 media dict (a reel or a video post) as the monitor's video dict; None if not a video."""
    if not parse.is_video(m):
        kids = [k for k in m.get("carousel_media") or [] if parse.is_video(k)]
        if not kids:
            return None
        m = {**kids[0], "code": m.get("code"), "user": m.get("user"), "taken_at": m.get("taken_at"),
             "caption": m.get("caption")}
    pk = parse.media_pk(m)
    code = m.get("code")
    best = parse.best_video(m) or {}
    user = m.get("user") or m.get("owner") or {}
    img = parse.best_image(m) or {}
    return {
        "id": f"ig:{pk}", "platform": "instagram",
        "url": f"https://www.instagram.com/reel/{code}/" if code else f"https://www.instagram.com/p/{pk}/",
        "media_url": best.get("url"), "title": (parse.caption_text(m) or "")[:300] or None,
        "posted_at": parse.iso(m.get("taken_at")), "duration": parse._num(m.get("video_duration")),
        "thumbnail": img.get("url"), "blocked": None,
        "extra": {"pk": pk, "code": code, "author": user.get("username"), "author_name": user.get("full_name"),
                  "author_id": str(user.get("pk") or user.get("id") or "") or None,
                  "author_verified": user.get("is_verified")},
    }


def direct(c) -> bool:
    """Whether the monitor reads Instagram itself (setting `instagram.direct`, or the old env switch)."""
    from .. import db
    return os.environ.get("EE_MONITOR_INSTAGRAM_DIRECT") == "1" or db.setting(c, "instagram.direct") == "1"


def like_a_person(c, start: bool = True) -> bool:
    """A browsing session now? Only in the owner's daytime (`instagram.hours`, Kyiv time), and one session
    every 45-90 minutes (`instagram.session_gap_min`), like a person opening the app now and then.
    `start=False` only asks; True also books the session (the next one waits its gap)."""
    import random
    from datetime import datetime
    from zoneinfo import ZoneInfo
    from .. import db
    try:
        lo, hi = (int(x) for x in (db.setting(c, "instagram.hours") or "8-23").split("-"))
    except ValueError:
        lo, hi = 8, 23
    if not lo <= datetime.now(ZoneInfo("Europe/Kyiv")).hour < hi:
        return False
    nxt = db.setting(c, "instagram.next_session_at")
    if nxt and nxt > db.now():
        return False
    if not start:
        return True
    try:
        a, b = (int(x) for x in (db.setting(c, "instagram.session_gap_min") or "45-90").split("-"))
    except ValueError:
        a, b = 45, 90
    db.set_setting(c, "instagram.next_session_at", db.later(random.uniform(a, b) * 60))
    return True


def session_exists() -> bool:
    """A logged-in Instagram session, judged without touching Instagram: a `sessionid` cookie in the
    collector's profile, or in earth-empire/instagram-session. A profile that merely exists is not
    enough - opening Instagram logged out only spends the account's rate limit."""
    import sqlite3
    prof = Path(os.environ.get("EE_BROWSER_PROFILE", "/var/lib/earth-empire/browser/instagram"))
    for db_path in (prof / "Default" / "Cookies", prof / "Default" / "Network" / "Cookies"):
        if db_path.exists():
            try:
                con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=5)
                ok = con.execute("SELECT 1 FROM cookies WHERE host_key LIKE '%instagram.com' AND name='sessionid' "
                                 "AND (expires_utc = 0 OR expires_utc > (strftime('%s','now') + 11644473600) * 1000000)"
                                 ).fetchone()
                con.close()
                if ok:
                    return True
            except sqlite3.Error:
                pass
    try:
        from eecollector.config import Secrets, Settings
        st = Secrets(Settings()).session_state()
        return bool(st) and any(ck.get("name") == "sessionid" for ck in st.get("cookies", []))
    except Exception:  # noqa: BLE001
        return False


class Instagram:
    """The collector's IGBrowser under the profile lock; never logs in (creds=None)."""

    def __init__(self, c, client=None):
        self.c = c
        self.client = client   # tests pass a fake with the same interface
        self._lockf = None
        self._ig = None
        from eecollector import parse
        self.parse = parse

    def __enter__(self):
        if self.client:
            return self
        import fcntl
        from eecollector.config import Secrets, Settings
        from eecollector.igweb import IGBrowser
        s = Settings()
        s.profile_lock.parent.mkdir(parents=True, exist_ok=True)
        self._lockf = open(s.profile_lock, "a")
        try:
            fcntl.flock(self._lockf, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise pace.Stop("instagram", "busy", "the collector holds the Instagram profile") from None
        sec = Secrets(s)
        self._ig = IGBrowser(s, creds=None, session_state=sec.session_state).start()
        self._ig.pacer.lane = "monitor"   # counted with the collector's requests; never the owner's reserve
        self.client = self._ig
        try:
            self._ig.ensure_session()
        except Exception as e:  # noqa: BLE001 - IGStop(login/checkpoint) or the refused login
            self.__exit__()
            kind = getattr(e, "kind", "login")
            raise pace.Stop("instagram", "login" if kind in ("login", "config") else kind,
                            f"Instagram session not usable yet: {e}") from None
        return self

    def __exit__(self, *a):
        if self._ig:
            try:
                self._ig.close()
            except Exception:  # noqa: BLE001
                pass
            self._ig = None
        if self._lockf:
            self._lockf.close()
            self._lockf = None

    def _call(self, fn, *args):
        pace.wait(self.c, "instagram")   # the monitor's own daily cap; IGBrowser paces each request too
        try:
            return fn(*args)
        except Exception as e:  # noqa: BLE001
            if type(e).__name__ == "PaceFull":   # this hour's room is used: stop the round, try later
                raise pace.Stop("instagram", "busy", str(e)) from None
            kind = getattr(e, "kind", None)
            if kind:
                raise pace.Stop("instagram", kind, str(e)) from None
            raise

    def user_id(self, username: str) -> str | None:
        prof = self._call(self.client.profile, username)
        u = (prof.get("data") or {}).get("user") or prof.get("user") or {}
        return str(u.get("id") or u.get("pk") or "") or None

    def following(self, username: str, limit: int = 400) -> list[dict]:
        uid = self.user_id(username)
        out, cursor = [], None
        while uid and len(out) < limit:
            q = "?count=50" + (f"&max_id={cursor}" if cursor else "")
            r = self._call(self.client.api, f"/api/v1/friendships/{uid}/following/{q}")
            for u in r.get("users") or []:
                out.append({"username": u.get("username"), "name": u.get("full_name") or u.get("username"),
                            "id": str(u.get("pk") or u.get("id") or ""), "verified": u.get("is_verified")})
            cursor = r.get("next_max_id")
            if not cursor:
                break
        return out

    def account_videos(self, username: str, user_id: str | None = None, cursor=None) -> tuple[list[dict], str | None]:
        uid = user_id or self.user_id(username)
        if not uid:
            return [], None
        r = self._call(self.client.clips, uid, cursor)
        media, nxt = self.parse.clips_page(r)
        return [v for v in (to_video(m, self.parse) for m in media) if v], nxt

    def media(self, pk: str) -> dict | None:
        r = self._call(self.client.media_info, pk)
        ms = self.parse.find_media(r)
        return to_video(ms[0], self.parse) if ms else None

    def around(self, code: str, scrolls: int = 3) -> list[dict]:
        """The reels Instagram plays after this one in its reels viewer."""
        bodies = self._call(self.client.browse, f"https://www.instagram.com/reels/{code}/", scrolls)
        out = {}
        for b in bodies:
            for m in self.parse.find_media(b):
                v = to_video(m, self.parse)
                if v and (v["extra"].get("code") != code):
                    out[v["id"]] = v
        return list(out.values())

    def explore(self, scrolls: int = 3) -> list[dict]:
        bodies = self._call(self.client.browse, "https://www.instagram.com/reels/", scrolls)
        out = {}
        for b in bodies:
            for m in self.parse.find_media(b):
                v = to_video(m, self.parse)
                if v:
                    out[v["id"]] = v
        return list(out.values())


def media_url_fresh(video: dict) -> bool:
    """Instagram CDN URLs carry an expiry (oe=<hex unix time>)."""
    import re
    m = re.search(r"[?&]oe=([0-9A-Fa-f]+)", video.get("media_url") or "")
    return bool(m) and int(m.group(1), 16) > time.time() + 600
