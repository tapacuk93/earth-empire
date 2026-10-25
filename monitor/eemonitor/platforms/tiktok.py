"""TikTok, read-only, through the downloader account's browser session.

Session: the Playwright storageState in earth-empire/tiktok-session (made by the owner's sign-in on
the Mac), kept afterwards in /var/lib/earth-empire/browser/tiktok/ (lock tiktok.lock). The monitor
never types the password in earth-empire/tiktok: until the session exists TikTok stays paused and is
looked at again every 3 hours. A captcha, a verification page or a login wall stops TikTok
(recorded in `stops`, with a screenshot). It only watches: no likes, follows, comments or messages.

Data: TikTok's own JSON as its web app receives it while a profile page or the For You feed is open
(`/api/post/item_list/`, `/api/recommend/item_list/`, `/api/related/item_list/`) and the page's
embedded `__UNIVERSAL_DATA_FOR_REHYDRATION__`. A video's file URL only works with the session's
cookies, so it is downloaded through the same browser context.
"""
from __future__ import annotations

import fcntl
import json
import logging
import os
import random
import re
import time
from pathlib import Path

from .. import pace

log = logging.getLogger("ee.monitor.tiktok")
TT = "https://www.tiktok.com"
PROFILE = Path(os.environ.get("EE_TT_PROFILE", "/var/lib/earth-empire/browser/tiktok"))
SHOTS = Path(os.environ.get("EE_MONITOR_DIR", "/var/lib/earth-empire/monitor")) / "screenshots"
CHALLENGE = re.compile(r"captcha|verify to continue|drag the slider|select 2 objects|"
                       r"too many attempts|unusual activity|Maximum number of attempts", re.I)


def session_state():
    from .facebook import secret
    s = secret("earth-empire/tiktok-session")
    return s if isinstance(s, dict) and s.get("cookies") else None


def session_exists() -> bool:
    """A TikTok sessionid in the profile's cookies or in the handed-over storageState (no network)."""
    import sqlite3
    for db_path in (PROFILE / "Default" / "Cookies", PROFILE / "Default" / "Network" / "Cookies"):
        if db_path.exists():
            try:
                con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=5)
                ok = con.execute("SELECT 1 FROM cookies WHERE host_key LIKE '%tiktok.com' AND name='sessionid'").fetchone()
                con.close()
                if ok:
                    return True
            except sqlite3.Error:
                pass
    st = session_state()
    return bool(st) and any(ck.get("name") == "sessionid" for ck in st.get("cookies", []))


# ------------------------------------------------------------------ parsing (pure)
def _walk(v, depth=0):
    if depth > 40:
        return
    if isinstance(v, dict):
        yield v
        for x in v.values():
            yield from _walk(x, depth + 1)
    elif isinstance(v, list):
        for x in v:
            yield from _walk(x, depth + 1)


def videos_in(blob) -> list[dict]:
    """TikTok item structs (id, video{playAddr, downloadAddr, duration, cover}, author, createTime, desc)."""
    out: dict[str, dict] = {}
    for d in _walk(blob):
        v = d.get("video")
        if not isinstance(v, dict) or not str(d.get("id") or "").isdigit():
            continue
        url = v.get("playAddr") or v.get("downloadAddr")
        if isinstance(url, list):
            url = url[0] if url else None
        if not url and isinstance(v.get("bitrateInfo"), list) and v["bitrateInfo"]:
            url = ((v["bitrateInfo"][-1].get("PlayAddr") or {}).get("UrlList") or [None])[0]
        a = d.get("author") if isinstance(d.get("author"), dict) else {"uniqueId": d.get("author")}
        uid = a.get("uniqueId") or ""
        t = d.get("createTime")
        out[str(d["id"])] = {
            "id": f"tt:{d['id']}", "platform": "tiktok",
            "url": f"{TT}/@{uid}/video/{d['id']}" if uid else f"{TT}/video/{d['id']}",
            "media_url": url, "title": (d.get("desc") or "")[:300] or None,
            "posted_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(int(t))) if str(t or "").isdigit() else None,
            "duration": float(v["duration"]) if v.get("duration") else None, "thumbnail": v.get("cover"),
            "blocked": None if url else "no playable address in TikTok's JSON",
            "extra": {"author": uid, "author_name": a.get("nickname"), "author_id": a.get("id"),
                      "verified": a.get("verified")},
        }
    return list(out.values())


def blobs_in(text: str):
    if text.lstrip().startswith("<"):
        m = re.search(r'<script id="__UNIVERSAL_DATA_FOR_REHYDRATION__"[^>]*>(.*?)</script>', text, re.S)
        if m:
            try:
                yield json.loads(m.group(1))
            except ValueError:
                pass
        return
    try:
        yield json.loads(text)
    except ValueError:
        pass


# ------------------------------------------------------------------ the browser
class TikTok:
    def __init__(self, c, headless: bool = True):
        self.c, self.headless = c, headless
        self.pw = self.ctx = self.page = None
        self.seen: list[str] = []
        self.harvest = False
        self._lockf = None

    def __enter__(self):
        PROFILE.mkdir(parents=True, exist_ok=True)
        os.chmod(PROFILE, 0o700)
        self._lockf = open(PROFILE.parent / "tiktok.lock", "a")
        try:
            fcntl.flock(self._lockf, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise pace.Stop("tiktok", "busy", "another process holds the tiktok profile") from None
        from playwright.sync_api import sync_playwright
        self.pw = sync_playwright().start()
        self.ctx = self.pw.chromium.launch_persistent_context(
            str(PROFILE), headless=self.headless, viewport={"width": 1366, "height": 900}, locale="en-US",
            timezone_id="Europe/Kyiv", args=["--disable-blink-features=AutomationControlled"])
        self.page = self.ctx.pages[0] if self.ctx.pages else self.ctx.new_page()
        self.page.set_default_timeout(45000)
        self.page.on("response", self._on_response)
        if not any(ck["name"] == "sessionid" for ck in self.ctx.cookies(TT)):
            st = session_state()
            if not st:
                self.__exit__()
                raise pace.Stop("tiktok", "login", "no TikTok session yet: the owner signs in on the Mac and the "
                                                   "storageState lands in earth-empire/tiktok-session")
            good = []
            for ck in st["cookies"]:
                if "tiktok.com" not in ck.get("domain", ""):
                    continue
                ck = {k: v for k, v in ck.items() if k in ("name", "value", "domain", "path", "expires", "httpOnly",
                                                          "secure", "sameSite")}
                if ck.get("sameSite") not in ("Strict", "Lax", "None"):
                    ck["sameSite"] = "Lax"
                if (ck.get("expires") or -1) < 0:
                    ck.pop("expires", None)
                good.append(ck)
            self.ctx.add_cookies(good)
        return self

    def __exit__(self, *a):
        for f in (lambda: self.ctx.close(), lambda: self.pw.stop()):
            try:
                f()
            except Exception:  # noqa: BLE001
                pass
        if self._lockf:
            self._lockf.close()
            self._lockf = None

    def _on_response(self, r):
        if self.harvest and "/api/" in r.url and "item_list" in r.url:
            try:
                self.seen.append(r.text())
            except Exception:  # noqa: BLE001
                pass

    def shot(self, name):
        try:
            SHOTS.mkdir(parents=True, exist_ok=True)
            p = SHOTS / f"{time.strftime('%Y%m%dT%H%M%S', time.gmtime())}-tiktok-{name}.png"
            self.page.screenshot(path=str(p))
            return str(p)
        except Exception:  # noqa: BLE001
            return None

    def check(self, where: str):
        try:
            body = self.page.inner_text("body", timeout=5000)[:20000]
        except Exception:  # noqa: BLE001
            body = ""
        if CHALLENGE.search(body) or self.page.locator("#captcha-verify-container, .captcha_verify_container").count():
            raise pace.Stop("tiktok", "checkpoint", f"captcha/verification at {where} (screenshot {self.shot('captcha')})")
        if "/login" in self.page.url:
            raise pace.Stop("tiktok", "login", f"TikTok asked to log in at {where} (screenshot {self.shot('login')})")

    def browse(self, url: str, where: str, scrolls: int = 2) -> list[dict]:
        self.seen, self.harvest = [], True
        try:
            pace.wait(self.c, "tiktok")
            self.page.goto(url, wait_until="domcontentloaded")
            self.page.wait_for_timeout(random.randint(4000, 8000))
            self.check(where)
            html = self.page.content()
            for _ in range(scrolls):
                self.page.mouse.wheel(0, random.randint(1200, 2400))
                self.page.wait_for_timeout(random.randint(4000, 9000))
            self.check(where)
        finally:
            self.harvest = False
        out: dict[str, dict] = {}
        for text in [html] + self.seen:
            for b in blobs_in(text):
                for v in videos_in(b):
                    out[v["id"]] = v
        return list(out.values())

    def download(self, url: str, dest: Path, max_bytes: int = 300 << 20) -> Path:
        pace.wait(self.c, "media")
        r = self.ctx.request.get(url, headers={"Referer": TT + "/"}, timeout=180000)
        if r.status != 200:
            raise pace.HTTPFail(r.status, f"TikTok media {r.status}")
        body = r.body()
        if len(body) > max_bytes:
            raise pace.Stop("tiktok", "too_large", "video over the size cap")
        dest.write_bytes(body)
        return dest


def list_videos(c, account: dict, before=None, tt: TikTok | None = None):
    return tt.browse(f"{TT}/@{account['handle'].lstrip('@')}", f"@{account['handle']}", scrolls=3 if before else 1), None


def related(c, video: dict, tt: TikTok) -> list[dict]:
    return [v for v in tt.browse(video["url"], "related", scrolls=2) if v["id"] != video["id"]]


def for_you(c, tt: TikTok) -> list[dict]:
    return tt.browse(f"{TT}/foryou", "for you", scrolls=3)
