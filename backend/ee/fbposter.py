"""The Facebook poster: the owner's own profile, through a headless browser with their session.

Facebook offers no API for personal profiles, so this drives the ordinary web composer with
Playwright, which Facebook's terms do not allow. The owner chose this, at the risk of their own
account. To keep the account looking like a person posting:

- The session is a Playwright storageState from the secret earth-empire/facebook-session,
  captured where the owner logged in by hand. This code never types a password and never answers
  a checkpoint. When the session is logged out or challenged, it stops, saves a screenshot, logs
  it, and stays paused until the secret changes.
- A few posts a day (facebook.daily_cap, default 4), with random gaps (min/max_gap_minutes),
  only in waking hours (facebook.active_hours in facebook.timezone).
- On any warning ("you're posting too fast", "temporarily blocked", "try again later"), it
  pauses for 72 hours and logs it.

Every post leaves a screenshot as proof (also copied to s3://earth-empire-backups/facebook/), and
the post's URL when the profile page shows it. Dry run walks through the composer, fills it in,
screenshots it and closes it without clicking Post.

The labels the UI uses are matched in English, Ukrainian and Russian.
"""
from __future__ import annotations

import fcntl
import hashlib
import json
import logging
import os
import random
import re
import shutil
import tempfile
import time
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path

from . import compose, config, store
from .analysis import Media
from .db import now, set_setting, setting
from .logs import event, metric

BROWSER_DIR = Path(os.environ.get("EE_BROWSER_DIR", "/var/lib/earth-empire/browser"))
PROOF_DIR = config.DATA_DIR / "facebook"

L = {  # accessible names, as regular expressions, in the languages the owner may use
    "composer": r"What's on your mind|Що у вас на думці|Що у вас нового|О чём вы думаете|Что у вас нового",
    "not_now": r"^(Not now|Не зараз|Не сейчас)$",
    "dialog": r"Create post|Створити допис|Створення допису|Создать публикацию|Создание публикации",
    "photo": r"^(Photo/video|Фото/відео|Фото/видео)$",
    "next": r"^(Next|Далі|Далее)$",
    "post": r"^(Post|Опублікувати|Публікувати|Опубликовать)$",
    "close": r"^(Close|Закрити|Закрыть)$",
    "discard": r"^(Discard|Leave|Відхилити|Вийти|Скасувати|Отменить|Выйти)$",
}
WARNINGS = re.compile(r"posting too fast|temporarily blocked|try again later|we limit how often|"
                      r"you can't use this feature|публікуєте надто|тимчасово заблоковано|спробуйте пізніше|"
                      r"временно заблокирован|повторите попытку позже", re.I)
LOGGED_OUT = re.compile(r"/login|/checkpoint|/two_step_verification|/recover", re.I)


class FacebookError(Exception):
    pass


class NeedsOwner(FacebookError):
    """Logged out or challenged: only the owner can fix this."""


class Warned(FacebookError):
    """Facebook warned about the posting rate."""


def session_state():
    s = config.secret("facebook_session", fresh=True)
    if not isinstance(s, dict) or config.is_placeholder(s) or not s.get("cookies"):
        return None
    return s


def session_fingerprint(state) -> str:
    return hashlib.sha256(json.dumps(state, sort_keys=True).encode()).hexdigest()[:16] if state else ""


@contextmanager
def profile_lock():
    BROWSER_DIR.mkdir(parents=True, exist_ok=True)
    with open(BROWSER_DIR / "facebook.lock", "w") as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(f, fcntl.LOCK_UN)


def pause(ms_lo=600, ms_hi=1800):
    time.sleep(random.uniform(ms_lo, ms_hi) / 1000)


class Browser:
    def __init__(self, state: dict, headless: bool = True):
        from playwright.sync_api import sync_playwright
        self.pw = sync_playwright().start()
        self.browser = self.pw.chromium.launch(headless=headless, args=["--disable-blink-features=AutomationControlled"])
        self.ctx = self.browser.new_context(storage_state=state, viewport={"width": 1366, "height": 900},
                                            locale=os.environ.get("EE_FB_LOCALE", "en-US"),
                                            timezone_id=os.environ.get("EE_FB_TZ", "Europe/Kyiv"))
        self.page = self.ctx.new_page()
        self.page.set_default_timeout(30000)

    def close(self):
        for f in (self.ctx.close, self.browser.close, self.pw.stop):
            try:
                f()
            except Exception:
                pass

    def shot(self, name: str) -> Path:
        PROOF_DIR.mkdir(parents=True, exist_ok=True)
        p = PROOF_DIR / f"{datetime.now(timezone.utc):%Y%m%dT%H%M%S}-{name}.png"
        self.page.screenshot(path=str(p), full_page=False)
        try:
            if config.CLOUDWATCH:
                import boto3
                boto3.client("s3", region_name=config.REGION).upload_file(
                    str(p), config.BACKUP_BUCKET, f"facebook/{p.name}")
        except Exception as e:
            event("facebook.proof_upload_failed", logging.WARNING, error=str(e))
        return p

    def check(self, where: str):
        url = self.page.url
        body = ""
        try:
            body = self.page.inner_text("body", timeout=5000)[:20000]
        except Exception:
            pass
        if LOGGED_OUT.search(url) or self.page.locator("input[name='pass']").count() > 0:
            p = self.shot(f"logged-out-{where}")
            raise NeedsOwner(f"Facebook session is logged out or challenged at {where} ({url}); screenshot {p}")
        if WARNINGS.search(body):
            p = self.shot(f"warning-{where}")
            raise Warned(f"Facebook warned at {where}: {WARNINGS.search(body).group(0)!r}; screenshot {p}")

    def open_home(self):
        self.page.goto("https://www.facebook.com/", wait_until="domcontentloaded")
        pause(2500, 5000)
        self.check("home")

    def dismiss_prompts(self):
        """Close 'remember password' and similar cards, never answering them otherwise."""
        b = self.page.get_by_role("button", name=re.compile(L["not_now"], re.I))
        if b.count():
            try:
                b.first.click(timeout=5000)
                pause()
            except Exception:
                pass

    def open_composer(self):
        self.dismiss_prompts()
        btn = self.page.get_by_role("button", name=re.compile(L["composer"], re.I)).first
        if btn.count() == 0:
            btn = self.page.get_by_text(re.compile(L["composer"], re.I)).first
        btn.click()
        pause()
        dlg = self.page.get_by_role("dialog", name=re.compile(L["dialog"], re.I)).first
        dlg.wait_for(state="visible", timeout=20000)
        return dlg

    def add_media(self, dlg, files: list[Path]):
        if not files:
            return
        inp = dlg.locator("input[type=file]")
        if inp.count() == 0:
            dlg.get_by_role("button", name=re.compile(L["photo"], re.I)).first.click()
            pause()
            inp = dlg.locator("input[type=file]")
        inp.first.set_input_files([str(f) for f in files])
        # Wait until uploads settle: the Post/Next button turns enabled once media is processed.
        deadline = time.time() + 600
        while time.time() < deadline:
            pause(2000, 3000)
            busy = dlg.locator("[role=progressbar]").count()
            if not busy:
                break
        pause(1500, 3000)

    def type_text(self, dlg, text: str):
        box = dlg.get_by_role("textbox").first
        box.click()
        pause()
        # Paragraph by paragraph, at a human-ish pace; long text is inserted in pieces.
        for i, para in enumerate(text.split("\n")):
            if i:
                self.page.keyboard.press("Shift+Enter")
            for chunk in re.findall(r".{1,40}", para, flags=re.S):
                self.page.keyboard.insert_text(chunk)
                time.sleep(random.uniform(0.05, 0.25))
        pause(1000, 2500)

    def submit(self, dlg):
        nxt = dlg.get_by_role("button", name=re.compile(L["next"], re.I))
        if nxt.count() and nxt.first.is_enabled():
            nxt.first.click()
            pause(1500, 3000)
        post = self.page.get_by_role("button", name=re.compile(L["post"], re.I)).last
        post.click()
        # Wait for the dialog to go away (the post is being published).
        deadline = time.time() + 300
        while time.time() < deadline:
            pause(2000, 3000)
            self.check("after-post")
            if self.page.get_by_role("dialog", name=re.compile(L["dialog"], re.I)).count() == 0:
                return
        raise FacebookError("the composer did not close within 5 minutes after Post")

    def discard(self):
        self.page.keyboard.press("Escape")
        pause()
        d = self.page.get_by_role("button", name=re.compile(L["discard"], re.I))
        if d.count():
            d.first.click()
            pause()

    def latest_post_url(self) -> str | None:
        self.page.goto("https://www.facebook.com/me", wait_until="domcontentloaded")
        pause(3000, 5000)
        self.check("profile")
        links = self.page.locator("a[href*='/posts/'], a[href*='story_fbid'], a[href*='/permalink/'], a[href*='/videos/']")
        for i in range(min(links.count(), 10)):
            href = links.nth(i).get_attribute("href") or ""
            if href:
                return href.split("?")[0] if "/posts/" in href else href.split("&__")[0]
        return None


def due(c) -> tuple[bool, str]:
    """Whether a Facebook post may go out now, and why not."""
    paused = setting(c, "facebook.paused_until")
    nowdt = datetime.now(timezone.utc)
    if paused:
        if paused.startswith("session:"):
            if session_fingerprint(session_state()) == paused[len("session:"):]:
                return False, "waiting for a new earth-empire/facebook-session"
            set_setting(c, "facebook.paused_until", "")
            event("facebook.resumed", reason="new session secret")
        elif paused > nowdt.strftime("%Y-%m-%dT%H:%M:%SZ"):
            return False, f"paused until {paused}"
    from zoneinfo import ZoneInfo
    local = nowdt.astimezone(ZoneInfo(setting(c, "facebook.timezone") or "Europe/Kyiv"))
    lo, hi = (int(x) for x in (setting(c, "facebook.active_hours") or "9-22").split("-"))
    if not lo <= local.hour < hi:
        return False, f"outside active hours ({local:%H:%M} local)"
    day_start = local.replace(hour=0, minute=0, second=0, microsecond=0).astimezone(timezone.utc)
    n = c.execute("SELECT COUNT(*) n FROM steps WHERE step='facebook' AND state='posted' AND updated_at >= ?",
                  (day_start.strftime("%Y-%m-%dT%H:%M:%SZ"),)).fetchone()["n"]
    if n >= int(setting(c, "facebook.daily_cap") or 4):
        return False, f"daily cap reached ({n})"
    nxt = setting(c, "facebook.next_at")
    if nxt and nxt > nowdt.strftime("%Y-%m-%dT%H:%M:%SZ"):
        return False, f"next post at {nxt}"
    return True, ""


def schedule_next(c):
    lo = int(setting(c, "facebook.min_gap_minutes") or 120)
    hi = int(setting(c, "facebook.max_gap_minutes") or 300)
    at = datetime.now(timezone.utc) + timedelta(minutes=random.uniform(lo, hi))
    set_setting(c, "facebook.next_at", at.strftime("%Y-%m-%dT%H:%M:%SZ"))


def post_item(c, item_id: str, *, dry_run: bool) -> dict:
    row = c.execute("SELECT * FROM items WHERE id=?", (item_id,)).fetchone()
    item = store.render_item(c, row)
    post = compose.build(item)
    text = compose.facebook_text(post)
    state = session_state()
    if not state:
        raise NeedsOwner("earth-empire/facebook-session holds no session yet")
    work = Path(tempfile.mkdtemp(prefix="ee-fb-"))
    b = None
    try:
        fetch = Media(work)
        files = [fetch.fetch(m["url"], f"{i}{Path(m['url']).suffix or '.bin'}") for i, m in enumerate(post.media)]
        with profile_lock():
            b = Browser(state)
            b.open_home()
            event("facebook.step", item=item_id, step="home", url=b.page.url)
            dlg = b.open_composer()
            event("facebook.step", item=item_id, step="composer open")
            b.add_media(dlg, files)
            event("facebook.step", item=item_id, step="media added", files=len(files))
            b.type_text(dlg, text)
            event("facebook.step", item=item_id, step="text typed", chars=len(text))
            b.check("composer")
            if dry_run:
                p = b.shot(f"dry-run-{item_id}")
                b.discard()
                event("facebook.dry_run", item=item_id, screenshot=str(p))
                print(f"=== {item_id}: dry run, composer filled and closed; screenshot {p}\n{text}")
                return {"dry_run": True, "screenshot": str(p)}
            # From here a retry could post twice: mark it, so a failure needs the owner to look.
            store.set_step(c, item_id, "facebook", "running", detail={"submitted_at": now()})
            b.submit(dlg)
            event("facebook.step", item=item_id, step="posted")
            pause(4000, 8000)
            url = None
            try:
                url = b.latest_post_url()
            except FacebookError:
                raise
            except Exception as e:
                event("facebook.url_unreadable", logging.WARNING, item=item_id, error=str(e))
            p = b.shot(f"posted-{item_id}")
            store.set_step(c, item_id, "facebook", "posted", remote_url=url, detail={"screenshot": p.name},
                           note="posted")
            metric("FacebookPosts")
            return {"posted": url, "screenshot": str(p)}
    finally:
        if b:
            b.close()
        shutil.rmtree(work, ignore_errors=True)


def handle_block(c, e: Exception):
    """Pause posting after a logout/challenge (until the secret changes) or a warning (72 h)."""
    if isinstance(e, NeedsOwner):
        set_setting(c, "facebook.paused_until", "session:" + session_fingerprint(session_state()))
        event("facebook.needs_owner", logging.ERROR, error=str(e),
              action="refresh the secret earth-empire/facebook-session; posting resumes by itself")
    elif isinstance(e, Warned):
        until = (datetime.now(timezone.utc) + timedelta(hours=72)).strftime("%Y-%m-%dT%H:%M:%SZ")
        set_setting(c, "facebook.paused_until", until)
        event("facebook.warned", logging.ERROR, error=str(e), paused_until=until)
    metric("WorkerErrors")
