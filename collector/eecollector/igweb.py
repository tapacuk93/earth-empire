"""Instagram through a real Chromium (Playwright): login, session, and Instagram's own JSON.

All data comes from Instagram's JSON as the web app gets it: either responses the browser
receives while it browses (intercepted with page.on("response")), or the same /api/v1/ calls the
web app makes, issued with fetch() from inside an instagram.com page so they carry the session's
cookies, CSRF token and app id like the web app's own requests.

Gentle by design: one browser, one tab, a stable user agent and viewport, a randomized gap between
requests, a long pause now and then, a cap per hour, and long backoff on 429 / "please wait".
A checkpoint, challenge or failed login stops the run (IGStop) - nothing is retried blindly.
"""

from __future__ import annotations

import json
import logging
import os
import random
import sys
import time
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlencode

from playwright.sync_api import Error as PWError

from .config import Settings, is_placeholder

log = logging.getLogger("ee.ig")

IG = "https://www.instagram.com"
APP_ID = "936619743392459"
CHALLENGE_PATHS = ("/challenge", "/checkpoint", "/accounts/suspended", "/auth_platform/", "/accounts/disabled")


def json_documents(text: str) -> list:
    """Instagram streams some GraphQL answers as several JSON documents in one body (deferred
    parts), sometimes behind "for (;;);". Returns every document."""
    text = text.strip()
    if text.startswith("for (;;);"):
        text = text[len("for (;;);"):]
    dec, out, i = json.JSONDecoder(), [], 0
    while i < len(text):
        while i < len(text) and text[i] in " \r\n\t":
            i += 1
        if i >= len(text):
            break
        doc, i = dec.raw_decode(text, i)
        out.append(doc)
    return out


class IGStop(RuntimeError):
    """Stop the run cleanly. `kind` is checkpoint | login | rate_limit | config."""

    def __init__(self, kind: str, msg: str):
        super().__init__(msg)
        self.kind = kind


class PaceFull(RuntimeError):
    """This hour's requests for the lane are used up, or waiting for room would outlast the run:
    the run stops what it is doing (cleanly, incomplete) instead of sleeping past its deadline."""

    def __init__(self, lane: str, wait_s: float):
        super().__init__(f"pacing: no room for {lane} requests for {wait_s:.0f}s")
        self.lane, self.wait_s = lane, wait_s


class Pacer:
    """At most `per_hour` requests an hour. The owner's own profile (`lane = "own"`) may use all of
    them; reposts (`lane = "repost"`) only `per_hour - own_reserve`, so the profile always has room.
    With a `deadline` (wall clock), a pause that would outlast it raises PaceFull instead."""

    def __init__(self, s: Settings):
        self.s = s
        self.last = 0.0
        self.n = 0
        self.window: list[float] = []
        self.lane = "own"
        self.deadline: float | None = None

    def limit(self) -> int:
        return self.s.per_hour if self.lane == "own" else max(1, self.s.per_hour - self.s.own_reserve)

    def wait(self) -> None:
        now = time.monotonic()
        self.window = [t for t in self.window if now - t < 3600]
        if len(self.window) >= self.limit():
            k = len(self.window) - self.limit()      # this many must age out of the hour first
            sleep = 3600 - (now - self.window[k]) + random.uniform(5, 60)
            if self.lane != "own" or (self.deadline and time.time() + sleep > self.deadline):
                log.info("pacing: %d requests in the last hour (%s may use %d); stopping instead of a %.0fs pause",
                         len(self.window), self.lane, self.limit(), sleep)
                raise PaceFull(self.lane, sleep)
            log.info("pacing: %d requests in the last hour, pausing %.0fs", len(self.window), sleep)
            time.sleep(sleep)
        gap = random.uniform(self.s.min_gap, self.s.max_gap)
        if self.n and self.n % random.randint(18, 26) == 0:
            gap += random.uniform(45, 150)  # a human pause
        delay = gap - (time.monotonic() - self.last)
        if delay > 0:
            time.sleep(delay)
        self.last = time.monotonic()
        self.window.append(self.last)
        self.n += 1


def classify(status: int, body: Any, url: str = "") -> IGStop | None:
    """Turn Instagram's refusals into a clean stop. None when the response is usable."""
    msg = ""
    if isinstance(body, dict):
        msg = str(body.get("message") or "")
        if body.get("checkpoint_url") or msg in ("checkpoint_required", "challenge_required") \
                or body.get("error_type") in ("checkpoint_challenge_required", "challenge_required"):
            return IGStop("checkpoint", f"Instagram checkpoint/challenge ({msg or body.get('error_type')}); "
                                        "log in by hand through the remote browser, see collector/README.md")
        if msg == "login_required" or body.get("require_login") and status in (401, 403):
            return IGStop("login", "Instagram session is not logged in (login_required)")
        if "feedback_required" in msg or body.get("spam"):
            return IGStop("checkpoint", f"Instagram feedback_required / spam flag: {msg[:200]}")
    if status == 429 or "wait a few minutes" in msg.lower():
        return IGStop("rate_limit", f"Instagram rate limit ({status}: {msg[:120]})")
    if any(x in url for x in CHALLENGE_PATHS):
        return IGStop("checkpoint", f"Instagram redirected to {url.split('?')[0]}")
    return None


class IGBrowser:
    """The live client. Same interface as tests' FakeIG: profile, feed, clips, tray, reels, media_info."""

    def __init__(self, settings: Settings, creds: Callable[[], dict] | None = None,
                 session_state: Callable[[], dict | None] | None = None, state=None):
        self.s = settings
        self.creds = creds
        self.session_state = session_state
        self.state = state
        self.pacer = Pacer(settings)
        self.pw = self.ctx = self.page = None
        self.seen: list[dict] = []   # responses intercepted while browsing
        self.harvest = False
        self.user_agent = settings.user_agent

    # ------------------------------------------------------------ lifecycle

    def start(self) -> "IGBrowser":
        from playwright.sync_api import sync_playwright
        prof = self.s.profile_dir
        prof.mkdir(parents=True, exist_ok=True)
        os.chmod(prof, 0o700)
        self.pw = sync_playwright().start()
        ua = self.user_agent or self._stable_ua()
        self.user_agent = ua
        kw = dict(user_data_dir=str(prof), headless=self.s.headless, user_agent=ua,
                  viewport={"width": 1366, "height": 900}, locale=self.s.locale,
                  timezone_id=self.s.timezone, args=["--disable-blink-features=AutomationControlled"])
        if self.s.channel:
            kw["channel"] = self.s.channel
        try:
            self.ctx = self.pw.chromium.launch_persistent_context(**kw)
        except Exception as e:  # noqa: BLE001 - e.g. only the headless shell is installed
            if "channel" not in kw:
                raise
            log.warning("browser channel %s unavailable (%s); using the default build", kw.pop("channel"), str(e)[:200])
            self.ctx = self.pw.chromium.launch_persistent_context(**kw)
        self.page = self.ctx.pages[0] if self.ctx.pages else self.ctx.new_page()
        self.page.on("response", self._on_response)
        return self

    def _stable_ua(self) -> str:
        """The browser's own UA minus "HeadlessChrome", fixed per profile (stored once), true to the OS."""
        f = self.s.profile_dir / "user-agent.txt"
        if f.exists():
            return f.read_text().strip()
        try:
            b = self.pw.chromium.launch(headless=True, **({"channel": self.s.channel} if self.s.channel else {}))
        except Exception:  # noqa: BLE001
            b = self.pw.chromium.launch(headless=True)
        major = b.version.split(".")[0]
        b.close()
        if sys.platform == "darwin":
            osname = "Macintosh; Intel Mac OS X 10_15_7"
        else:
            osname = "X11; Linux x86_64"  # what Chrome reports on every Linux, ARM too (UA reduction)
        ua = f"Mozilla/5.0 ({osname}) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/{major}.0.0.0 Safari/537.36"
        f.write_text(ua)
        return ua

    def close(self) -> None:
        try:
            if self.ctx:
                self.ctx.close()
        finally:
            if self.pw:
                self.pw.stop()

    def __enter__(self):
        return self.start()

    def __exit__(self, *a):
        self.close()

    # ------------------------------------------------------------ session

    def cookies(self) -> dict[str, str]:
        return {c["name"]: c["value"] for c in self.ctx.cookies(IG)}

    def logged_in(self) -> bool:
        return bool(self.cookies().get("sessionid"))

    def goto(self, url: str) -> None:
        self.pacer.wait()
        self.page.goto(url, wait_until="domcontentloaded", timeout=60000)
        self.page.wait_for_timeout(random.randint(2500, 5000))
        stop = classify(200, None, self.page.url)
        if stop:
            raise stop

    def screenshot(self, folder: Path) -> Path | None:
        """For the owner: what the browser showed when a run stopped."""
        try:
            folder.mkdir(parents=True, exist_ok=True)
            path = folder / f"{time.strftime('%Y%m%dT%H%M%S', time.gmtime())}.png"
            self.page.screenshot(path=str(path))
            log.info("screenshot of the stop: %s (page %s)", path, self.page.url.split("?")[0])
            return path
        except Exception as e:  # noqa: BLE001
            log.warning("no screenshot: %s", e)
            return None

    def import_state(self, state: dict) -> int:
        """Add the cookies of a Playwright storageState (or a plain cookie list) to the profile."""
        cookies = state.get("cookies") if isinstance(state, dict) else state
        good = []
        for c in cookies or []:
            if "instagram.com" not in c.get("domain", ""):
                continue
            c = {k: v for k, v in c.items() if k in ("name", "value", "domain", "path", "expires",
                                                     "httpOnly", "secure", "sameSite")}
            if c.get("sameSite") not in ("Strict", "Lax", "None"):
                c["sameSite"] = "Lax"
            if c.get("expires") in (None, -1) or c.get("expires", 0) < 0:
                c.pop("expires", None)
            good.append(c)
        self.ctx.add_cookies(good)
        return len(good)

    def mark_logged_in(self) -> None:
        if self.state is not None:
            self.state.set("login.last_failed_at", 0)
            self.state.set("login.refused", None)

    def ensure_session(self) -> None:
        """Logged in, or IGStop. Order: saved profile, handed-over storageState, automatic login."""
        if not self.logged_in() and self.session_state:
            st = self.session_state()
            if st:
                n = self.import_state(st)
                log.info("session: imported %d cookies from earth-empire/instagram-session", n)
        self.goto(IG + "/")
        if self.logged_in() and "/accounts/login" not in self.page.url:
            log.info("session: reusing the saved Instagram session")
            self.mark_logged_in()
            return
        self.login()

    def login(self) -> None:
        if not self.creds:
            raise IGStop("login", "the Instagram session is logged out and automatic login is off; "
                                  "log in by hand (ee-collector login) or put a storageState in "
                                  "earth-empire/instagram-session")
        creds = self.creds()
        if not creds or is_placeholder(creds.get("username")) or is_placeholder(creds.get("password")):
            raise IGStop("config", "no usable credentials in earth-empire/instagram (placeholder?); "
                                   "log in by hand through the remote browser instead")
        # never brute-force: after Instagram refused the credentials, no automatic login until a
        # person logs in (ee-collector login / import-session); after other failures, one try per 12h
        if self.state is not None and self.state.get("login.refused"):
            raise IGStop("login", f"Instagram refused the automatic login earlier ({self.state.get('login.refused')}); "
                                  "not trying again. Log in by hand: ee-collector login (remote view), "
                                  "or put a storageState in earth-empire/instagram-session")
        if self.state is not None:
            last = self.state.get("login.last_failed_at", 0)
            if time.time() - last < 12 * 3600:
                raise IGStop("login", "an automatic login failed less than 12h ago; not trying again. "
                                      "Log in by hand through the remote browser, or wait.")
        log.info("login: signing in as the downloader account")
        self.goto(IG + "/accounts/login/")
        self._dismiss_cookie_banner()
        p = self.page
        user_sel = 'input[name="username"], input[name="email"], input[autocomplete*="username"]'
        pass_sel = 'input[name="password"], input[name="pass"], input[type="password"]'
        p.wait_for_selector(user_sel, timeout=30000)
        self._type(user_sel, creds["username"])
        self._type(pass_sel, creds["password"])
        p.wait_for_timeout(random.randint(600, 1500))
        btn = p.query_selector('[role="button"][aria-label="Log In"], [role="button"][aria-label="Log in"], '
                               'button[type="submit"]')
        disabled = btn.get_attribute("aria-disabled") if btn else None
        typed_ok = (len(p.locator(user_sel).first.input_value()) == len(creds["username"])
                    and len(p.locator(pass_sel).first.input_value()) == len(creds["password"]))
        if not typed_ok:  # never submit a mangled password: that is a failed login for nothing
            raise IGStop("login", "login: the form did not take the typed credentials; not submitting")
        log.info("login: form filled (button %s, disabled=%s, lengths match)", "found" if btn else "missing", disabled)

        def on_login_response(r):
            if "login" in r.url and r.request.method == "POST":
                try:
                    body = r.text()[:300]
                except Exception:  # noqa: BLE001
                    body = "?"
                log.info("login: %s -> %d %s", r.url.split("?")[0], r.status, body.replace("\n", " "))
        p.on("response", on_login_response)
        if btn and disabled != "true":
            btn.click()
        else:
            p.locator(pass_sel).first.press("Enter")
        result = self._await_login(creds)
        if result != "ok":
            try:
                txt = p.evaluate("document.body.innerText")[:400].replace("\n", " | ")
                log.info("login: page at %s shows: %s", p.url.split("?")[0], txt)
            except PWError:
                pass
            if self.state is not None:
                self.screenshot(self.s.state_dir / "screenshots")
        if result != "ok":
            if self.state is not None:
                self.state.set("login.last_failed_at", time.time())
                if result.startswith("refused") or result.startswith("checkpoint"):
                    self.state.set("login.refused", result[:200])
            raise IGStop("checkpoint" if result.startswith("checkpoint") else "login", f"login: {result}")
        if self.state is not None:
            self.state.set("login.last_failed_at", 0)
        log.info("login: signed in; session saved in the browser profile")

    def _await_login(self, creds: dict) -> str:
        p = self.page
        deadline = time.monotonic() + 60
        totp_done = False
        while time.monotonic() < deadline:
            try:
                r = self._login_step(creds, totp_done)
            except PWError as e:  # the page navigated under us; look again
                log.debug("login: page changed (%s)", str(e)[:80])
                continue
            if r == "totp":
                totp_done = True
            elif r:
                return r
        if "/accounts/login" in p.url:
            return "no answer from the login form within 60s"
        return "ok" if self.logged_in() else f"not logged in after submit (at {p.url.split('?')[0]})"

    def _login_step(self, creds: dict, totp_done: bool) -> str | None:
        """One look at the page after submitting: None (keep waiting), "totp", "ok" or a reason to stop."""
        p = self.page
        p.wait_for_timeout(1500)
        url = p.url
        if any(x in url for x in CHALLENGE_PATHS):
            return f"checkpoint at {url.split('?')[0]}"
        if p.query_selector('input[name="verificationCode"]') or "two_factor" in url:
            secret = creds.get("totp_secret")
            if not secret:
                return "checkpoint: two-factor code required and no totp_secret is set"
            if totp_done:
                return None
            import pyotp
            self._type('input[name="verificationCode"]', pyotp.TOTP(secret.replace(" ", "")).now())
            p.wait_for_timeout(random.randint(500, 1200))
            btn = p.query_selector('button:has-text("Confirm"), [role="button"]:has-text("Confirm")')
            (btn.click() if btn else p.keyboard.press("Enter"))
            return "totp"
        if "/accounts/login" in url:
            body = p.evaluate("document.body.innerText") or ""
            for phrase in ("login information you entered is incorrect", "password was incorrect",
                           "password you entered", "couldn't connect to Instagram", "Please wait a few minutes"):
                if phrase.lower() in body.lower():
                    return f"refused: Instagram says '{phrase}'"
            for sel in ('#slfErrorAlert', '[role="alert"]', 'span:has-text("password was incorrect")',
                        'span:has-text("password you entered")', 'div:has-text("Sorry, ") >> nth=-1'):
                err = p.query_selector(sel)
                txt = (err.inner_text() or "").strip()[:200] if err else ""
                if txt:
                    return f"refused: {txt}"
        if self.logged_in():
            for label in ("Save info", "Save Info", "Not now", "Not Now"):
                b = p.query_selector(f'button:has-text("{label}"), [role="button"]:has-text("{label}")')
                if b:
                    b.click()
                    p.wait_for_timeout(1500)
                    break
            if "/accounts/login" not in p.url:
                return "ok"
        return None

    def _type(self, sel: str, text: str) -> None:
        el = self.page.locator(sel).first
        el.click()
        self.page.wait_for_timeout(random.randint(200, 600))
        el.press_sequentially(text, delay=random.randint(60, 140))

    def _dismiss_cookie_banner(self) -> None:
        for label in ("Allow all cookies", "Decline optional cookies", "Only allow essential cookies"):
            b = self.page.query_selector(f'button:has-text("{label}")')
            if b:
                b.click()
                self.page.wait_for_timeout(1000)
                return

    # ------------------------------------------------------------ requests

    def _on_response(self, r) -> None:
        if not self.harvest:
            return
        u = r.url
        if "/api/v1/" not in u and "/graphql" not in u:
            return
        try:
            ctype = r.headers.get("content-type", "")
            if not any(t in ctype for t in ("json", "javascript", "text/plain")):
                return
            for body in json_documents(r.text()):
                self.seen.append({"url": u.split("?")[0], "status": r.status, "body": body})
        except Exception as e:  # noqa: BLE001 - a response we cannot read is just skipped
            log.debug("unreadable response %s: %s", u.split("?")[0], e)

    def _fetch(self, method: str, path: str, form: dict | None = None) -> dict:
        csrf = self.cookies().get("csrftoken", "")
        js = """async ([method, url, form, csrf, appId]) => {
            const opts = {method, credentials: 'include', headers: {
                'X-IG-App-ID': appId, 'X-Requested-With': 'XMLHttpRequest', 'X-CSRFToken': csrf,
                'X-ASBD-ID': '359341', 'Accept': '*/*'}};
            if (form) { opts.body = new URLSearchParams(form).toString();
                        opts.headers['Content-Type'] = 'application/x-www-form-urlencoded'; }
            const r = await fetch(url, opts);
            return {status: r.status, url: r.url, text: await r.text()};
        }"""
        return self.page.evaluate(js, [method, path, form, csrf, APP_ID])

    def api(self, path: str, method: str = "GET", form: dict | None = None) -> dict:
        """One request the web app makes. A 429 / "please wait" ends the run at once (IGStop
        rate_limit); the CLI then keeps every run off Instagram for a growing cool-down."""
        if not self.page.url.startswith(IG):
            self.goto(IG + "/")
        self.pacer.wait()
        r = self._fetch(method, path, form)
        try:
            body = json.loads(r["text"])
        except json.JSONDecodeError:
            body = None
        stop = classify(r["status"], body, r.get("url", ""))
        if stop:
            log.warning("IG %s %s -> %d: %s", method, path.split("?")[0], r["status"], stop)
            raise stop
        if r["status"] >= 400 or body is None:
            log.warning("IG %s %s -> %d %s", method, path.split("?")[0], r["status"], r["text"][:200])
            raise IGError(f"{path.split('?')[0]} -> {r['status']}")
        log.info("IG %s %s -> %d", method, path.split("?")[0], r["status"])
        rec = os.environ.get("EE_RECORD_DIR")
        if rec:  # raw responses for building fixtures; local only, never committed
            Path(rec).mkdir(parents=True, exist_ok=True)
            name = path.split("?")[0].strip("/").replace("/", "_")
            Path(rec, f"{int(time.time()*1000)}_{name}.json").write_text(json.dumps(body))
        return body

    # ------------------------------------------------------------ the client interface

    def feed(self, user_id: str, cursor: str | None) -> dict:
        q = {"count": 12}
        if cursor:
            q["max_id"] = cursor
        return self.api(f"/api/v1/feed/user/{user_id}/?{urlencode(q)}")

    def clips(self, user_id: str, cursor: str | None) -> dict:
        form = {"target_user_id": user_id, "page_size": "12", "include_feed_video": "true"}
        if cursor:
            form["max_id"] = cursor
        return self.api("/api/v1/clips/user/", "POST", form)

    def tray(self, user_id: str) -> dict:
        return self.api(f"/api/v1/highlights/{user_id}/highlights_tray/")

    def reels(self, reel_ids: list[str]) -> dict:
        return self.api("/api/v1/feed/reels_media/?" + urlencode([("reel_ids", r) for r in reel_ids]))

    def media_info(self, pk: str) -> dict:
        return self.api(f"/api/v1/media/{pk}/info/")

    def page_text(self) -> str:
        try:
            return self.page.evaluate("document.body.innerText")[:2000]
        except PWError:
            return ""

    def browse(self, url: str, scrolls: int = 3, click: tuple[str, ...] = ()) -> list[dict]:
        """Visit a page like a person and return the JSON it loaded (responses and embedded data).
        `click`: button labels to press once if shown (the story viewer's "View story")."""
        self.seen = []
        self.harvest = True
        try:
            self.goto(url)
            for label in click:
                b = self.page.query_selector(f'button:has-text("{label}"), [role="button"]:has-text("{label}")')
                if b:
                    self.page.wait_for_timeout(random.randint(800, 2000))
                    b.click()
                    self.page.wait_for_timeout(random.randint(4000, 6500))
                    break
            for _ in range(scrolls):
                self.page.mouse.wheel(0, random.randint(1500, 2600))
                self.page.wait_for_timeout(random.randint(2500, 5000))
            # data the server rendered into the page (preloaded queries) never shows up as a response
            for text in self.page.evaluate(
                    """() => [...document.querySelectorAll('script[type="application/json"]')]
                             .map(s => s.textContent).filter(t => t && t.length > 200)"""):
                try:
                    for body in json_documents(text):
                        self.seen.append({"url": "embedded", "status": 200, "body": body})
                except ValueError:
                    pass
        finally:
            self.harvest = False
        rec = os.environ.get("EE_RECORD_DIR")
        for s in self.seen:
            stop = classify(s["status"], s["body"])
            if stop:
                log.warning("browsing %s: %s answered %d: %s", url, s["url"], s["status"], stop)
                if stop.kind != "rate_limit" or "/api/v1/" in s["url"]:
                    raise stop
            if rec:
                Path(rec).mkdir(parents=True, exist_ok=True)
                Path(rec, f"{int(time.time()*1000)}_browse.json").write_text(json.dumps(s))
        log.info("browsed %s: %d JSON responses", url.split("?")[0], len(self.seen))
        return [s["body"] for s in self.seen]


class IGError(RuntimeError):
    pass
