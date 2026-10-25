"""Facebook public videos through the *downloader* account's browser session.

Session: the Playwright storageState in earth-empire/facebook-dl-session, kept afterwards in the
persistent profile /var/lib/earth-empire/browser/facebook-dl/ (lock facebook-dl.lock). Only when
that session is logged out does it type earth-empire/facebook-dl's password, once; a checkpoint,
two-step prompt or any warning stops Facebook (recorded in `stops`) with a screenshot. The owner's
own account (earth-empire/facebook-session) is never used here - it is for posting only.

Data: Facebook's own JSON as the page receives it - the GraphQL responses the web app loads while
a page's Videos / Reels tab is open and scrolled, and the JSON embedded in the page's HTML. Video
nodes carry a progressive MP4 URL on Facebook's CDN, which is downloaded once and deleted after
transcription.
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

log = logging.getLogger("ee.monitor.facebook")
FB = "https://www.facebook.com"
PROFILE = Path(os.environ.get("EE_FB_DL_PROFILE", "/var/lib/earth-empire/browser/facebook-dl"))
SHOTS = Path(os.environ.get("EE_MONITOR_DIR", "/var/lib/earth-empire/monitor")) / "screenshots"
LOGGED_OUT = re.compile(r"/login|/checkpoint|/two_step_verification|/recover|/two_factor", re.I)
CHALLENGE = re.compile(r"/checkpoint|/two_step_verification|/two_factor|/recover|/confirmemail|/disabled", re.I)
WARNINGS = re.compile(r"temporarily blocked|try again later|you.re going too fast|we limit how often|"
                      r"your account has been (locked|restricted|suspended)|confirm your identity|"
                      r"тимчасово заблоковано|спробуйте пізніше|временно заблокирован|повторите попытку позже", re.I)
URL_KEYS = ("browser_native_sd_url", "playable_url", "browser_native_hd_url", "playable_url_quality_hd")


def secret(name: str):
    import boto3
    from botocore.exceptions import ClientError
    try:
        raw = boto3.client("secretsmanager", region_name=os.environ.get("AWS_REGION", "us-east-1")) \
            .get_secret_value(SecretId=name)["SecretString"]
    except ClientError:
        return None
    try:
        v = json.loads(raw)
    except ValueError:
        return None
    if isinstance(v, dict) and isinstance(v.get("value"), str):
        try:
            v = json.loads(v["value"])
        except ValueError:
            pass
    return v


# ------------------------------------------------------------------ parsing (pure; tested with fixtures)
def json_blobs(text: str):
    """Every JSON value in a GraphQL response (one per line) or in a page's <script type=application/json>."""
    if text.lstrip().startswith("<"):
        for m in re.finditer(r'<script type="application/json"[^>]*>(.*?)</script>', text, re.S):
            try:
                yield json.loads(m.group(1))
            except ValueError:
                pass
        return
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("for (;;);"):
            line = line[9:]
        if line[:1] in "{[":
            try:
                yield json.loads(line)
            except ValueError:
                pass


def _walk(v, depth=0):
    if depth > 60:
        return
    if isinstance(v, dict):
        yield v
        for x in v.values():
            yield from _walk(x, depth + 1)
    elif isinstance(v, list):
        for x in v:
            yield from _walk(x, depth + 1)


def _media_url(d: dict) -> str | None:
    for k in URL_KEYS:
        if isinstance(d.get(k), str) and d[k].startswith("http"):
            return d[k]
    for k in ("videoDeliveryLegacyFields",):
        if isinstance(d.get(k), dict):
            u = _media_url(d[k])
            if u:
                return u
    vr = (d.get("videoDeliveryResponseFragment") or {}).get("videoDeliveryResponseResult") or {}
    prog = vr.get("progressive_urls") or []
    for p in sorted(prog, key=lambda p: 0 if (p.get("metadata") or {}).get("quality") == "SD" else 1):
        if p.get("progressive_url"):
            return p["progressive_url"]
    return None


def videos_in(blob) -> list[dict]:
    """Video nodes anywhere in a JSON value, as the monitor's video dicts (by id, deduplicated)."""
    found: dict[str, dict] = {}
    for d in _walk(blob):
        vid = d.get("id") or d.get("video_id")
        if not isinstance(vid, str) or not vid.isdigit():
            continue
        url = _media_url(d)
        if not url:
            continue
        t = d.get("publish_time") or d.get("created_time") or d.get("creation_time")
        posted = None
        if isinstance(t, (int, float)) and t > 1e9:
            posted = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(t))
        dur = d.get("length_in_second") or d.get("playable_duration_in_ms")
        if isinstance(dur, (int, float)) and d.get("playable_duration_in_ms") and not d.get("length_in_second"):
            dur = dur / 1000
        owner = d.get("owner") or d.get("video_owner") or {}
        thumb = ((d.get("preferred_thumbnail") or {}).get("image") or {}).get("uri") or \
                (d.get("thumbnailImage") or {}).get("uri") or (d.get("image") or {}).get("uri")
        permalink = d.get("permalink_url") or d.get("url")
        if not isinstance(permalink, str) or "facebook.com" not in permalink:
            permalink = f"{FB}/watch/?v={vid}"
        title = d.get("title") or (d.get("savable_description") or {}).get("text") or \
            (d.get("message") or {}).get("text") if isinstance(d.get("message") or {}, dict) else None
        if isinstance(title, dict):
            title = title.get("text")
        prev = found.get(vid, {})
        found[vid] = {
            "id": f"fb:{vid}", "platform": "facebook", "url": permalink, "media_url": url,
            "title": (title or prev.get("title") or None) and str(title or prev.get("title"))[:300],
            "posted_at": posted or prev.get("posted_at"), "duration": float(dur) if dur else prev.get("duration"),
            "thumbnail": thumb or prev.get("thumbnail"), "blocked": None,
            "extra": {"owner_id": owner.get("id"), "owner_name": owner.get("name"),
                      "is_reel": "/reel/" in permalink},
        }
    return list(found.values())


# ------------------------------------------------------------------ the browser
class FacebookDL:
    def __init__(self, c, headless: bool = True):
        self.c = c
        self.headless = headless
        self.pw = self.ctx = self.page = None
        self.seen: list[str] = []
        self.harvest = False
        self._lockf = None

    def __enter__(self):
        PROFILE.mkdir(parents=True, exist_ok=True)
        os.chmod(PROFILE, 0o700)
        self._lockf = open(PROFILE.parent / "facebook-dl.lock", "a")
        try:
            fcntl.flock(self._lockf, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise pace.Stop("facebook", "busy", "another process holds the facebook-dl profile") from None
        from playwright.sync_api import sync_playwright
        self.pw = sync_playwright().start()
        self.ctx = self.pw.chromium.launch_persistent_context(
            str(PROFILE), headless=self.headless, viewport={"width": 1366, "height": 900}, locale="en-US",
            timezone_id="Europe/Kyiv", args=["--disable-blink-features=AutomationControlled"],
            user_agent="Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
                       "Chrome/141.0.0.0 Safari/537.36")
        self.page = self.ctx.pages[0] if self.ctx.pages else self.ctx.new_page()
        self.page.set_default_timeout(45000)
        self.page.on("response", self._on_response)
        if not any(ck["name"] == "c_user" for ck in self.ctx.cookies(FB)):
            st = secret("earth-empire/facebook-dl-session")
            if isinstance(st, dict) and st.get("cookies"):
                good = []
                for ck in st["cookies"]:
                    if "facebook.com" not in ck.get("domain", ""):
                        continue
                    ck = {k: v for k, v in ck.items() if k in ("name", "value", "domain", "path", "expires",
                                                              "httpOnly", "secure", "sameSite")}
                    if ck.get("sameSite") not in ("Strict", "Lax", "None"):
                        ck["sameSite"] = "Lax"
                    if (ck.get("expires") or -1) < 0:
                        ck.pop("expires", None)
                    good.append(ck)
                self.ctx.add_cookies(good)
                log.info("facebook-dl: imported %d cookies from earth-empire/facebook-dl-session", len(good))
        return self

    def __exit__(self, *a):
        for f in (lambda: self.ctx.close(), lambda: self.pw.stop()):
            try:
                f()
            except Exception:  # noqa: BLE001
                pass
        if self._lockf:
            self._lockf.close()

    def _on_response(self, r):
        if not self.harvest:
            return
        try:
            if "/api/graphql" in r.url or "/ajax/" in r.url:
                self.seen.append(r.text())
        except Exception:  # noqa: BLE001
            pass

    def shot(self, name: str) -> str | None:
        try:
            SHOTS.mkdir(parents=True, exist_ok=True)
            p = SHOTS / f"{time.strftime('%Y%m%dT%H%M%S', time.gmtime())}-facebook-{name}.png"
            self.page.screenshot(path=str(p))
            return str(p)
        except Exception:  # noqa: BLE001
            return None

    def check(self, where: str):
        url = self.page.url
        if CHALLENGE.search(url):
            raise pace.Stop("facebook", "checkpoint", f"challenge at {where}: {url.split('?')[0]} "
                                                      f"(screenshot {self.shot('checkpoint')})")
        try:
            body = self.page.inner_text("body", timeout=5000)[:30000]
        except Exception:  # noqa: BLE001
            body = ""
        m = WARNINGS.search(body)
        if m:
            raise pace.Stop("facebook", "checkpoint", f"warning at {where}: {m.group(0)!r} "
                                                      f"(screenshot {self.shot('warning')})")
        return body

    def logged_in(self) -> bool:
        return any(ck["name"] == "c_user" for ck in self.ctx.cookies(FB)) and not LOGGED_OUT.search(self.page.url) \
            and self.page.locator("input[name='pass']").count() == 0

    def goto(self, url: str, where: str):
        pace.wait(self.c, "facebook")
        self.page.goto(url, wait_until="domcontentloaded")
        self.page.wait_for_timeout(random.randint(3000, 6000))
        return self.check(where)

    def ensure_session(self):
        self.goto(FB + "/", "home")
        if self.logged_in():
            return
        st = self.c.execute("SELECT value FROM settings WHERE key='facebook.password_tried_at'").fetchone()
        if st and st["value"]:
            raise pace.Stop("facebook", "login", "the downloader session is logged out and the one password "
                                                 "login was already tried; refresh earth-empire/facebook-dl-session")
        creds = secret("earth-empire/facebook-dl") or {}
        if not creds.get("username") or not creds.get("password"):
            raise pace.Stop("facebook", "login", "the downloader session is logged out and earth-empire/facebook-dl "
                                                 "has no username/password")
        from .. import db
        db.set_setting(self.c, "facebook.password_tried_at", db.now())
        log.warning("facebook-dl: session logged out; one password login")
        self.goto(FB + "/login/", "login")
        self.page.fill("input[name='email']", creds["username"])
        self.page.wait_for_timeout(random.randint(600, 1500))
        self.page.fill("input[name='pass']", creds["password"])
        self.page.wait_for_timeout(random.randint(600, 1500))
        self.page.keyboard.press("Enter")
        self.page.wait_for_timeout(8000)
        self.check("after login")
        if not self.logged_in():
            raise pace.Stop("facebook", "login", f"password login did not log in (at {self.page.url.split('?')[0]}; "
                                                 f"screenshot {self.shot('login')})")
        db.set_setting(self.c, "facebook.password_tried_at", "")

    def browse(self, url: str, where: str, scrolls: int = 3) -> list[dict]:
        """Open a page like a person, scroll, and return the video nodes it loaded."""
        self.seen = []
        self.harvest = True
        try:
            self.goto(url, where)
            html = self.page.content()
            for _ in range(scrolls):
                self.page.mouse.wheel(0, random.randint(1400, 2600))
                self.page.wait_for_timeout(random.randint(2500, 5500))
            self.check(where)
        finally:
            self.harvest = False
        out: dict[str, dict] = {}
        for text in [html] + self.seen:
            for blob in json_blobs(text):
                for v in videos_in(blob):
                    out[v["id"]] = {**out.get(v["id"], {}), **{k: x for k, x in v.items() if x}}
        return list(out.values())


def page_url(handle: str) -> str:
    return handle if handle.startswith("http") else f"{FB}/{handle.strip('/')}"


def list_videos(c, account: dict, before=None, fb: FacebookDL | None = None) -> tuple[list[dict], str | None]:
    base = page_url(account["handle"])
    vids: dict[str, dict] = {}
    for tab in ("/videos", "/reels"):
        for v in fb.browse(base + tab, f"{account['handle']}{tab}", scrolls=4 if before else 2):
            vids[v["id"]] = v
    return list(vids.values()), None


def related(c, video: dict, fb: FacebookDL) -> list[dict]:
    """What Facebook shows next to a video (the watch page's suggestions, or the next reels)."""
    vid = video["id"].split(":", 1)[1]
    url = f"{FB}/reel/{vid}" if (video.get("extra") or {}).get("is_reel") else f"{FB}/watch/?v={vid}"
    return [v for v in fb.browse(url, "related", scrolls=3) if v["id"] != video["id"]]


def explore(c, fb: FacebookDL) -> list[dict]:
    return fb.browse(f"{FB}/watch/", "watch feed", scrolls=4)


def following(c, fb: FacebookDL, profile: str) -> list[dict]:
    """Pages and people a profile follows, when its following list is visible."""
    fb.goto(f"{FB}/{profile}/following", "following")
    for _ in range(4):
        fb.page.mouse.wheel(0, random.randint(1400, 2600))
        fb.page.wait_for_timeout(random.randint(2500, 5000))
    links = fb.page.eval_on_selector_all("a[href^='https://www.facebook.com/']",
                                         "els => els.map(e => [e.href, e.innerText])")
    out, seen = [], set()
    for href, text in links:
        m = re.match(r"https://www\.facebook\.com/(profile\.php\?id=\d+|[A-Za-z0-9.]{3,})/?(\?|$)", href)
        if not m or not text.strip() or len(text) > 80:
            continue
        h = m.group(1)
        if h in seen or h.split("?")[0] in ("watch", "reel", "groups", "marketplace", "friends", "gaming",
                                             profile, "help", "policies", "privacy", "settings", "notifications",
                                             "bookmarks", "events", "pages", "messages", "stories", "photo"):
            continue
        seen.add(h)
        out.append({"handle": h, "name": text.strip().split("\n")[0]})
    return out
