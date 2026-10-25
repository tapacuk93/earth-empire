"""The monitor's worker: discover videos, scan them (audio -> transcript -> hits), follow
recommendations around seeds. One process, one thing at a time, gentle on every platform.

    python -m eemonitor.worker            the loop (systemd: ee-monitor-worker)
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import random
import shutil
import subprocess
import tempfile
import time
import zlib
from pathlib import Path

from . import db, detect, pace, phrases, registry, transcribe
from .platforms import facebook, instagram, telegram, telegram_api, tiktok, youtube

log = logging.getLogger("ee.monitor")
MEDIA_BUCKET = os.environ.get("EE_MEDIA_BUCKET", "earth-empire-media")
MEDIA_BASE = os.environ.get("EE_MEDIA_BASE_URL", "https://media.empire.earth").rstrip("/")
YTDLP = os.environ.get("EE_YTDLP", str(Path(os.sys.executable).parent / "yt-dlp"))
MAIN_KINDS = ("official", "followed", "reposted_author", "reposted")
# The monitor never calls Instagram itself: Instagram data comes only from what the collector ingested
# into the backend (items, reposts; the following list once the collector gathers it). The browser code
# in platforms/instagram.py is kept for a later stage, behind this switch.
INSTAGRAM_DIRECT = os.environ.get("EE_MONITOR_INSTAGRAM_DIRECT") == "1"
BACKEND_DB = os.environ.get("EE_BACKEND_DB", "/var/lib/earth-empire/backend/earth-empire.sqlite3")


def ev(name: str, level=logging.INFO, **f):
    log.log(level, json.dumps({"event": "monitor." + name, **f}, ensure_ascii=False, default=str))


# ------------------------------------------------------------------ heartbeats (CONTRACT.md: /v1/ingest/heartbeat)
JOB: dict = {}
_hb_lock = __import__("threading").Lock()


def heartbeat(c=None, event: str | None = None, kind: str | None = None, ok: bool = True, error: str | None = None):
    """Tell the backend we are alive, what we are doing and (optionally) what just happened."""
    import httpx
    try:
        from ee import config
        tok = config.secret("ingest_token")
        tok = tok.get("token") or tok.get("value") if isinstance(tok, dict) else tok
        c = c or db.connect()
        from . import learn
        lr = learn.report(c)
        detail = {"recall_mirror": lr["recall"] if lr["recall"] is not None else "n/a",
                  "mirror_matched": lr["matched"], "mirror_found_first": lr["found_first"],
                  "misses": sum(lr["misses_by_cause"].values()),
                  "improvements": c.execute("SELECT COUNT(*) n FROM improvements WHERE applied=1").fetchone()["n"],
                  "scanned": c.execute("SELECT COUNT(*) n FROM videos WHERE state='done'").fetchone()["n"],
                  "queued": c.execute("SELECT COUNT(*) n FROM videos WHERE state='queued'").fetchone()["n"],
                  "hits": c.execute("SELECT COUNT(*) n FROM hits").fetchone()["n"],
                  "audio_min_today": round(db.used(c, "audio_min.main") + db.used(c, "audio_min.recommended"), 1),
                  "stopped": ",".join(r["platform"] for r in c.execute("SELECT platform FROM stops")) or "none"}
        body = {"component": "monitor", "ok": ok, "detail": detail}
        with _hb_lock:
            if JOB:
                body["jobs"] = [dict(JOB)]
        if error:
            body["error"] = error[:300]
        if event:
            body["event"] = event[:300]
            body["kind"] = kind or "monitor"
        httpx.post(os.environ.get("EE_API_URL", "http://127.0.0.1:8000") + "/v1/ingest/heartbeat", json=body,
                   headers={"Authorization": f"Bearer {tok}"}, timeout=10)
    except Exception as e:  # noqa: BLE001 - a heartbeat never breaks the work
        log.debug("heartbeat failed: %s", e)


def set_job(what: str | None, progress: str | None = None):
    with _hb_lock:
        JOB.clear()
        if what:
            JOB.update({"what": what, "progress": progress or "", "started_at": db.now()})


def _heartbeat_thread():
    import threading

    def run():
        c = db.connect()
        while True:
            heartbeat(c)
            time.sleep(60)
    threading.Thread(target=run, daemon=True, name="heartbeat").start()


# ------------------------------------------------------------------ phrases
def ensure_phrases(c) -> None:
    if not c.execute("SELECT 1 FROM phrases LIMIT 1").fetchone():
        set_phrases(c, phrases.DEFAULT_PHRASES, use_claude=False)


def set_phrases(c, texts: list[str], use_claude: bool = True) -> list[dict]:
    texts = [t.strip() for t in texts if t and t.strip()][:30]
    old = {r["text"]: json.loads(r["claude_variants"]) for r in c.execute("SELECT text, claude_variants FROM phrases")}
    c.execute("DELETE FROM phrases")
    for i, t in enumerate(texts):
        extra = old.get(t.lower())
        if extra is None and use_claude:
            from . import judge
            try:
                extra = phrases.claude_expand(t, lambda p: judge.ask(c, p, "phrase-variants", max_tokens=600))
            except Exception as e:  # noqa: BLE001
                log.warning("claude variants for %r failed: %s", t, e)
                extra = []
        comp = phrases.variants(t.lower(), extra or [])
        c.execute("INSERT OR REPLACE INTO phrases(text, position, compiled, claude_variants, updated_at) VALUES (?,?,?,?,?)",
                  (t.lower(), i, db.j(comp), db.j(extra or []), db.now()))
    return list_phrases(c)


def list_phrases(c) -> list[dict]:
    out = []
    for r in c.execute("SELECT * FROM phrases ORDER BY position"):
        comp = json.loads(r["compiled"])
        out.append({"text": r["text"], "variants": comp["variants"], "mishearings": comp.get("mishearings", []),
                    "claude_variants": json.loads(r["claude_variants"]), "updated_at": r["updated_at"]})
    return out


def compiled_phrases(c) -> list[dict]:
    return [json.loads(r["compiled"]) for r in c.execute("SELECT compiled FROM phrases ORDER BY position")]


# ------------------------------------------------------------------ videos
def insert_video(c, v: dict, account=None, source_kind="official", via=None, hop=0, source_id=None,
                 queue=False, requested=False) -> bool:
    """Insert a discovered video (or refresh its media URL). True when it is new."""
    row = c.execute("SELECT state FROM videos WHERE id=?", (v["id"],)).fetchone()
    if row:
        if v.get("media_url"):
            c.execute("UPDATE videos SET media_url=?, thumbnail=COALESCE(?, thumbnail), "
                      "duration=COALESCE(duration, ?) WHERE id=?",
                      (v["media_url"], v.get("thumbnail"), v.get("duration"), v["id"]))
            if row["state"] == "blocked" and not v.get("blocked"):
                c.execute("UPDATE videos SET state='new', error=NULL WHERE id=?", (v["id"],))
        return False
    if v.get("blocked") and v["platform"] == "telegram" and telegram_api.session_exists():
        v = {**v, "blocked": None}   # too large for the preview: the Telegram API fetches it
    state = "blocked" if v.get("blocked") else "queued" if queue or requested else "new"
    c.execute("""INSERT INTO videos(id, platform, account_id, source_id, source_kind, via, hop, url, media_url, title,
                 posted_at, duration, thumbnail, state, priority, requested, error, discovered_at, extra)
                 VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
              (v["id"], v["platform"], account["id"] if account else None,
               source_id or (account["source_id"] if account else None), source_kind, via, hop, v["url"],
               v.get("media_url"), v.get("title"), v.get("posted_at"), v.get("duration"), v.get("thumbnail"), state,
               (10 if requested else 0), int(requested), v.get("blocked"), db.now(), db.j(v.get("extra") or {})))
    return True


def open_request(c):
    return c.execute("SELECT * FROM requests WHERE remaining > 0 AND done_at IS NULL ORDER BY id LIMIT 1").fetchone()


def fetch_request(c, n: int, filters: dict | None = None) -> dict:
    """POST /v1/monitor/fetch: queue at least n more videos to scan, newest unscanned first, spread
    over sources; what is not yet discovered is looked for further back by the worker."""
    n = max(1, min(int(n), int(db.fsetting(c, "fetch.max_n"))))
    filters = {k: v for k, v in (filters or {}).items() if k in ("platform", "source_kind") and v}
    where, args = ["v.state='new'"], []
    if filters.get("platform"):
        where.append("v.platform=?")
        args.append(filters["platform"])
    if filters.get("source_kind"):
        where.append("v.source_kind=?")
        args.append(filters["source_kind"])
    rows = c.execute(f"""SELECT v.id FROM videos v WHERE {' AND '.join(where)}
        ORDER BY ROW_NUMBER() OVER (PARTITION BY v.account_id ORDER BY v.posted_at DESC), v.posted_at DESC
        LIMIT ?""", (*args, n)).fetchall()
    for r in rows:
        c.execute("UPDATE videos SET state='queued', requested=1, priority=10 WHERE id=?", (r["id"],))
    rest = n - len(rows)
    rid = c.execute("INSERT INTO requests(n, remaining, filters, created_at, done_at) VALUES (?,?,?,?,?)",
                    (n, rest, db.j(filters), db.now(), None if rest else db.now())).lastrowid
    if rest:   # look further back on every account soon
        c.execute("UPDATE accounts SET next_poll_at=? WHERE enabled=1 AND backfill_done=0", (db.now(),))
    ev("fetch_request", id=rid, n=n, queued_now=len(rows), to_discover=rest, filters=filters)
    return {"request_id": rid, "n": n, "queued": len(rows), "to_discover": rest}


def _claim_requested(c, platform: str) -> bool:
    r = open_request(c)
    if not r:
        return False
    f = json.loads(r["filters"])
    if f.get("platform") and f["platform"] != platform:
        return False
    c.execute("UPDATE requests SET remaining=remaining-1, done_at=CASE WHEN remaining-1<=0 THEN ? END WHERE id=?",
              (db.now(), r["id"]))
    return True


# ------------------------------------------------------------------ discovery
def poll_account(c, a, fb=None, ig=None, tt=None) -> int:
    """List an account's videos (newest page, or one page further back while a request wants more)."""
    platform = a["platform"]
    req = open_request(c)
    backfill = bool(req) and not a["backfill_done"]
    before = a["backfill_cursor"] if backfill else None
    if platform == "telegram":
        vids, cursor = telegram.list_videos(c, dict(a), before)
    elif platform == "youtube":
        vids, cursor = youtube.list_videos(c, dict(a), before)
    elif platform == "facebook":
        vids, cursor = facebook.list_videos(c, dict(a), before, fb=fb)
    elif platform == "instagram":
        vids, cursor = ig.account_videos(a["handle"], a["platform_id"], before)
    elif platform == "tiktok":
        vids, cursor = tiktok.list_videos(c, dict(a), before, tt=tt)
    else:
        return 0
    src = c.execute("SELECT source_kind FROM sources WHERE id=?", (a["source_id"],)).fetchone()
    sk = src["source_kind"] if src else "official"
    first = a["polls"] == 0
    latest_n = int(db.fsetting(c, "scan.auto_latest_per_account"))
    vids.sort(key=lambda v: v.get("posted_at") or "", reverse=True)
    recent_cut = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() - 3 * 86400))
    new = 0
    for i, v in enumerate(vids):
        auto = (i < latest_n) if first else (v.get("posted_at") or "") >= recent_cut
        auto = auto or (a["priority"] or 0) > 0 and i < 4 * latest_n
        requested = not v.get("blocked") and not auto and backfill and _claim_requested(c, platform)
        if insert_video(c, v, a, sk, queue=auto and not v.get("blocked"), requested=requested):
            new += 1
        elif requested:   # already known: give the claim back
            c.execute("UPDATE requests SET remaining=remaining+1, done_at=NULL WHERE id=?", (req["id"],))
    nxt = db.later(db.fsetting(c, "poll.minutes") * 60 * random.uniform(0.8, 1.3))
    c.execute("""UPDATE accounts SET last_polled_at=?, next_poll_at=?, polls=polls+1, last_error=NULL,
                 backfill_cursor=CASE WHEN ? THEN ? ELSE COALESCE(backfill_cursor, ?) END,
                 backfill_done=CASE WHEN ? AND ? IS NULL THEN 1 ELSE backfill_done END WHERE id=?""",
              (db.now(), nxt, backfill, cursor, cursor, backfill, cursor, a["id"]))
    if backfill and req:
        c.execute("UPDATE accounts SET next_poll_at=? WHERE id=?", (db.later(60), a["id"]))
    ev("polled", platform=platform, account=a["handle"], videos=len(vids), new=new, backfill=backfill)
    return new


def due_accounts(c, platform: str, limit: int):
    return c.execute("""SELECT * FROM accounts WHERE platform=? AND enabled=1 AND (next_poll_at IS NULL OR next_poll_at<=?)
                        ORDER BY next_poll_at LIMIT ?""", (platform, db.now(), limit)).fetchall()


def _account_error(c, a, e):
    c.execute("UPDATE accounts SET last_error=?, next_poll_at=? WHERE id=?",
              (str(e)[:500], db.later(6 * 3600), a["id"]))
    ev("poll_failed", logging.WARNING, platform=a["platform"], account=a["handle"], error=str(e)[:300])


_last_browser = 0.0


def discover(c, browsers: bool = True) -> int:
    """Poll due accounts: the plain-HTTP platforms every time, the browser ones (a Chromium session
    each) only when `browsers` - the loop asks for those at most every 20 minutes while scans wait."""
    global _last_browser
    n = 0
    for platform in ("telegram", "youtube"):
        if db.setting(c, f"{platform}.enabled") != "1" or db.stopped(c, platform):
            continue
        for a in due_accounts(c, platform, 3):
            try:
                n += poll_account(c, a)
            except pace.Stop as e:
                pace.halt(c, e)
                break
            except Exception as e:  # noqa: BLE001
                _account_error(c, a, e)
    if not browsers:
        return n
    _last_browser = time.time()
    if db.setting(c, "facebook.enabled") == "1" and not db.stopped(c, "facebook") and due_accounts(c, "facebook", 1):
        n += browser_round(c, "facebook")
    # Instagram: the monitor makes no requests of its own (the collector's young account is rate-limited);
    # it reads only what the collector ingested into the backend (repost_seeds). INSTAGRAM_DIRECT stays off.
    if INSTAGRAM_DIRECT and db.setting(c, "instagram.enabled") == "1" and not db.stopped(c, "instagram") \
            and instagram.session_exists():
        if due_accounts(c, "instagram", 1) or not db.setting(c, "instagram.following_synced"):
            n += browser_round(c, "instagram")
    if db.setting(c, "tiktok.enabled") == "1" and not db.stopped(c, "tiktok") and tiktok.session_exists() \
            and due_accounts(c, "tiktok", 1):
        n += browser_round(c, "tiktok", max_accounts=3)
    return n


def browser_round(c, platform: str, max_accounts: int = 4) -> int:
    """One browser session: a few due accounts (and, once a day, the followed list)."""
    n = 0
    try:
        if platform == "facebook":
            with facebook.FacebookDL(c) as fb:
                fb.ensure_session()
                if db.setting(c, "facebook.following_synced") < time.strftime("%Y-%m-%d"):
                    sync_facebook_following(c, fb)
                for a in due_accounts(c, "facebook", max_accounts):
                    try:
                        n += poll_account(c, a, fb=fb)
                    except pace.Stop:
                        raise
                    except Exception as e:  # noqa: BLE001
                        _account_error(c, a, e)
        elif platform == "tiktok":
            with tiktok.TikTok(c) as tt:
                for a in due_accounts(c, "tiktok", max_accounts):
                    try:
                        n += poll_account(c, a, tt=tt)
                    except pace.Stop:
                        raise
                    except Exception as e:  # noqa: BLE001
                        _account_error(c, a, e)
        else:
            with instagram.Instagram(c) as ig:
                if db.setting(c, "instagram.following_synced") < time.strftime("%Y-%m-%d"):
                    sync_instagram_following(c, ig)
                for a in due_accounts(c, "instagram", max_accounts):
                    try:
                        n += poll_account(c, a, ig=ig)
                    except pace.Stop:
                        raise
                    except Exception as e:  # noqa: BLE001
                        _account_error(c, a, e)
    except pace.Stop as e:
        if e.kind == "busy":
            ev("browser_busy", platform=platform, msg=e.msg)
        else:
            pace.halt(c, e)
    except Exception as e:  # noqa: BLE001
        ev("browser_failed", logging.WARNING, platform=platform, error=repr(e)[:400])
        db.stop(c, platform, "error", f"browser failed: {e!r}"[:500], 3600)
    return n


def target_username() -> str:
    if os.environ.get("EE_TARGET"):
        return os.environ["EE_TARGET"].lstrip("@")
    try:
        import boto3
        raw = boto3.client("secretsmanager", region_name=os.environ.get("AWS_REGION", "us-east-1")) \
            .get_secret_value(SecretId="earth-empire/target")["SecretString"]
        return json.loads(raw)["username"].lstrip("@")
    except Exception:  # noqa: BLE001
        return os.environ.get("EE_TARGET", "tapacuk93")


def sync_instagram_following(c, ig) -> int:
    me = target_username()
    users = ig.following(me)
    for u in users:
        if not u.get("username"):
            continue
        sid = "ig_" + registry.slug(u["username"])
        registry.upsert_source(c, sid, u["name"] or u["username"], "followed", "instagram_following",
                               data={"verified": u.get("verified")})
        registry.upsert_account(c, sid, "instagram", u["username"], u.get("id"))
    db.set_setting(c, "instagram.following_synced", time.strftime("%Y-%m-%d"))
    ev("following_synced", platform="instagram", of=me, accounts=len(users))
    return len(users)


def sync_facebook_following(c, fb) -> int:
    me = db.setting(c, "facebook.target_profile") or target_username()
    try:
        pages = facebook.following(c, fb, me)
    except pace.Stop:
        raise
    except Exception as e:  # noqa: BLE001
        ev("following_failed", logging.WARNING, platform="facebook", of=me, error=str(e)[:300])
        pages = []
    for p in pages:
        sid = "fb_" + registry.slug(p["handle"])
        registry.upsert_source(c, sid, p["name"], "followed", "facebook_following")
        registry.upsert_account(c, sid, "facebook", p["handle"])
    db.set_setting(c, "facebook.following_synced", time.strftime("%Y-%m-%d"))
    ev("following_synced", platform="facebook", of=me, accounts=len(pages))
    return len(pages)


# ------------------------------------------------------------------ scanning
def quota_left(c, source_kind: str) -> float:
    """Minutes of audio left today in the quota this kind of video draws on."""
    if source_kind == "recommended":
        return db.fsetting(c, "scan.recommended_daily_audio_minutes") - db.used(c, "audio_min.recommended")
    if source_kind in ("mirror", "reposted"):   # the publication gate has its own quota
        return db.fsetting(c, "scan.mirror_daily_audio_minutes") - db.used(c, "audio_min.mirror")
    return db.fsetting(c, "scan.daily_audio_minutes") - db.used(c, "audio_min.main")


def pick(c):
    stopped = [r["platform"] for r in c.execute("SELECT platform FROM stops") if db.stopped(c, r["platform"])]
    rows = c.execute("""SELECT * FROM videos WHERE state='queued' AND (next_at IS NULL OR next_at<=?)
                        ORDER BY requested DESC, priority DESC,
                        CASE source_kind WHEN 'recommended' THEN 1 ELSE 0 END, posted_at DESC LIMIT 50""",
                     (db.now(),)).fetchall()
    for v in rows:
        if v["platform"] in stopped and not (v["media_url"] or "").startswith(MEDIA_BASE):
            continue
        if quota_left(c, v["source_kind"]) <= 0:
            continue
        maxm = db.fsetting(c, "scan.max_video_minutes")
        if v["duration"] and v["duration"] > maxm * 60 and not v["requested"] \
                and v["source_kind"] not in ("mirror", "reposted"):
            c.execute("UPDATE videos SET state='skipped', error=? WHERE id=?",
                      (f"longer than {maxm:.0f} min; ask for it (fetch) or raise scan.max_video_minutes", v["id"]))
            continue
        return v
    return None


def download(c, v, work: Path) -> Path:
    platform = v["platform"]
    extra = json.loads(v["extra"] or "{}")
    if platform == "youtube":
        return youtube.download_audio(c, dict(v), work, YTDLP)
    url = v["media_url"]
    if platform == "telegram":
        url = telegram.refresh_media_url(c, {**dict(v), "extra": extra}) or url
        if not url and extra.get("post"):
            return telegram_api.download(c, extra["post"], work / "media.mp4")
    if platform == "instagram" and url and not url.startswith(MEDIA_BASE):
        if not INSTAGRAM_DIRECT:
            raise youtube.Blocked("Instagram media is read only from the collector's copies on the media host")
    if INSTAGRAM_DIRECT and platform == "instagram" and url and not url.startswith(MEDIA_BASE) \
            and not instagram.media_url_fresh(dict(v)):
        with instagram.Instagram(c) as ig:
            fresh = ig.media(extra.get("pk"))
            url = (fresh or {}).get("media_url") or url
    if platform == "tiktok":
        with tiktok.TikTok(c) as tt:
            try:
                return tt.download(url, work / "media.mp4")
            except pace.HTTPFail:   # the address expired: read the video's page again
                fresh = [x for x in tt.browse(v["url"], "video") if x["id"] == v["id"]]
                if not fresh or not fresh[0]["media_url"]:
                    raise
                return tt.download(fresh[0]["media_url"], work / "media.mp4")
    if not url:
        raise youtube.Blocked("no media URL for this video")
    out = work / "media.mp4"
    pace.get(c, "media", url, stream_to=out, timeout=300, max_bytes=600 << 20)
    return out


def store_transcript(tr: dict) -> bytes:
    return zlib.compress(json.dumps(tr, ensure_ascii=False, separators=(",", ":")).encode(), 6)


def load_transcript(blob) -> dict | None:
    if not blob:
        return None
    if isinstance(blob, str):
        return json.loads(blob)
    return json.loads(zlib.decompress(blob))


def expected_for(c, v, tr: dict) -> tuple[list[str], str]:
    src = c.execute("SELECT * FROM sources WHERE id=?", (v["source_id"],)).fetchone() if v["source_id"] else None
    exp = json.loads(src["expected_languages"]) if src else []
    if exp:
        return exp, "inferred from earlier scans" if src["languages_inferred"] else "registry"
    langs = transcribe.languages(tr)
    tot = sum(langs.values()) or 1
    main = [k for k, s in langs.items() if s / tot >= 0.5] or list(langs)[:1]
    return main, "this video's main language (the source's languages are not known yet)"


def hit_id(video_id: str, h: dict) -> str:
    key = f"{video_id}|{h['kind']}|{h.get('phrase') or h['language']}|{h['start']:.1f}"
    return "h_" + hashlib.sha1(key.encode()).hexdigest()[:14]


def detect_all(c, v, tr: dict) -> list[dict]:
    tr = tr or {}
    hits = detect.find_name(tr, db.fsetting(c, "name.min_confidence"), compiled_phrases(c))
    exp, basis = expected_for(c, v, tr)
    lh = detect.find_language(tr, exp, db.fsetting(c, "language.min_seconds"), db.fsetting(c, "language.min_prob"))
    for h in lh:
        h["expected_languages"] = exp
        h["expected_basis"] = basis
    return hits + lh


def upload(path: Path, key: str, ctype: str) -> str | None:
    """Private until published (CONTRACT.md "Monitor media"): returns the S3 key."""
    try:
        import boto3
        boto3.client("s3", region_name=os.environ.get("AWS_REGION", "us-east-1")).upload_file(
            str(path), MEDIA_BUCKET, key, ExtraArgs={"ContentType": ctype, "CacheControl": "private, max-age=3600"})
        return key
    except Exception as e:  # noqa: BLE001
        log.warning("upload %s failed: %s", key, e)
        return None


def make_clip(src: Path, hid: str, start: float, end: float, work: Path) -> dict:
    """A short audio clip around the hit (at most 20 s) and a frame from the video, on media.empire.earth."""
    out = {}
    s = max(0.0, start - 3)
    d = min(20.0, max(4.0, end - start + 6))
    mp3 = work / f"{hid}.mp3"
    if subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-y", "-ss", f"{s:.2f}", "-t", f"{d:.2f}", "-i", str(src),
                       "-vn", "-ac", "1", "-b:a", "64k", str(mp3)], timeout=120).returncode == 0 and mp3.exists():
        out["clip_key"] = upload(mp3, f"monitor/clips/{hid}.mp3", "audio/mpeg")
    jpg = work / f"{hid}.jpg"
    if subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-y", "-ss", f"{start:.2f}", "-i", str(src),
                       "-frames:v", "1", "-vf", "scale='min(640,iw)':-2", str(jpg)],
                      timeout=120, capture_output=True).returncode == 0 and jpg.exists():
        out["frame_key"] = upload(jpg, f"monitor/frames/{hid}.jpg", "image/jpeg")
    return out


def save_hits(c, v, hits: list[dict], model: str, keep_media: bool = True) -> int:
    """Replace a video's hits with these (published flags kept for hits that are still found)."""
    old = {r["id"]: r for r in c.execute("SELECT id, published_at, verdict, data FROM hits WHERE video_id=?", (v["id"],))}
    new_ids = set()
    for h in hits:
        hid = hit_id(v["id"], h)
        new_ids.add(hid)
        h["id"] = hid
        h["label"] = detect.label(h["confidence"])
        h["model"] = model
        if hid in old:
            prev = json.loads(old[hid]["data"])
            for k in ("clip_key", "frame_key", "clip", "frame", "excerpt_en", "judge", "suggested_section",
                      "section_reason"):
                if prev.get(k) and not h.get(k):
                    h[k] = prev[k]
        c.execute("""INSERT INTO hits(id, video_id, kind, start, "end", confidence, data, found_at)
                     VALUES (?,?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET confidence=excluded.confidence,
                     data=excluded.data, start=excluded.start, "end"=excluded."end" """,
                  (hid, v["id"], h["kind"], h["start"], h["end"], h["confidence"], db.j(h), db.now()))
    for hid in set(old) - new_ids:
        c.execute("DELETE FROM hits WHERE id=?", (hid,))
    return len(hits)


def scan(c, v) -> None:
    vid = v["id"]
    c.execute("UPDATE videos SET state='running', attempts=attempts+1 WHERE id=?", (vid,))
    set_job(f"scanning a {v['platform']} video", "downloading")
    work = Path(tempfile.mkdtemp(prefix="eemon-", dir=os.environ.get("EE_MONITOR_TMP", None)))
    t0 = time.time()
    try:
        src = download(c, v, work)
        set_job(f"scanning a {v['platform']} video", "transcribing")
        model_name = (db.setting(c, f"whisper.model.source.{v['source_id']}") if v["source_id"] else "") \
            or db.setting(c, "whisper.model")
        tr = transcribe.transcribe(str(src), model_name, int(db.fsetting(c, "whisper.beam_size")))
        minutes = tr["duration"] / 60
        db.add_usage(c, "audio_min.recommended" if v["source_kind"] == "recommended" else
                     "audio_min.mirror" if v["source_kind"] in ("mirror", "reposted") else "audio_min.main", minutes)
        hits = detect_all(c, v, tr)
        if hits:
            from . import judge
            try:
                judge.review(c, dict(v), hits)
            except Exception as e:  # noqa: BLE001
                log.warning("review failed: %s", e)
            for h in hits:
                if h["confidence"] >= 0.03:
                    h.update(make_clip(src, hit_id(vid, h), h["start"], h["end"], work))
        save_hits(c, v, hits, tr["model"])
        if v["source_kind"] in ("mirror", "reposted"):
            from . import learn
            try:
                res = learn.evaluate(c, v, hits, tr)
                if res["misses"]:
                    heartbeat(c, f"missed a mirrored match ({', '.join(res['misses'])}); improved", "learn")
            except Exception as e:  # noqa: BLE001
                log.warning("learn.evaluate failed: %s", e)
        c.execute("""UPDATE videos SET state='done', scanned_at=?, transcript=?, languages=?, audio_s=?, cpu_s=?,
                     model=?, error=NULL, duration=COALESCE(duration, ?) WHERE id=?""",
                  (db.now(), store_transcript(tr), db.j(transcribe.languages(tr)), tr["duration"], tr["cpu_s"],
                   tr["model"], tr["duration"], vid))
        if v["source_id"]:
            registry.infer_languages(c, v["source_id"])
        ev("scanned", video=vid, platform=v["platform"], audio_s=tr["duration"], speech_s=tr["speech_s"],
           wall_s=round(time.time() - t0, 1), transcribe_s=tr["wall_s"], cpu_s=tr["cpu_s"],
           languages=transcribe.languages(tr), hits=len(hits),
           top=[(h["kind"], h["matched"], h["confidence"]) for h in sorted(hits, key=lambda h: -h["confidence"])[:3]])
        best = max((h["confidence"] for h in hits), default=0)
        heartbeat(c, f"scanned a {v['platform']} video ({tr['duration'] / 60:.1f} min): {len(hits)} hits"
                     + (f", best {detect.label(best)}" if hits else ""), "scan")
    except youtube.Blocked as e:
        c.execute("UPDATE videos SET state='blocked', error=? WHERE id=?", (str(e)[:500], vid))
        ev("blocked", logging.WARNING, video=vid, error=str(e)[:300])
    except pace.Stop as e:
        if e.kind == "too_large":
            c.execute("UPDATE videos SET state='skipped', error=? WHERE id=?", (e.msg, vid))
        else:
            c.execute("UPDATE videos SET state='queued', next_at=? WHERE id=?", (db.later(1800), vid))
            if e.kind not in ("busy", "cap"):
                pace.halt(c, e)
    except Exception as e:  # noqa: BLE001
        att = v["attempts"] + 1
        state = "failed" if att >= 4 else "queued"
        c.execute("UPDATE videos SET state=?, error=?, next_at=? WHERE id=?",
                  (state, repr(e)[:500], db.later(900 * 2 ** att), vid))
        ev("scan_failed", logging.WARNING, video=vid, attempt=att, error=repr(e)[:400])
    finally:
        set_job(None)
        shutil.rmtree(work, ignore_errors=True)   # audio and video never kept


def rescan(c) -> dict:
    """Run detection again over every stored transcript (after the phrases changed)."""
    n = h = 0
    for v in c.execute("SELECT * FROM videos WHERE state='done' AND transcript IS NOT NULL").fetchall():
        tr = load_transcript(v["transcript"])
        hits = detect_all(c, v, tr)
        h += save_hits(c, v, hits, tr.get("model", ""))
        n += 1
    ev("rescanned", videos=n, hits=h)
    return {"videos": n, "hits": h}


# ------------------------------------------------------------------ recommendations
def _media_url(u: str) -> str:
    key = u[4:] if u.startswith("key:") else u
    return key if key.startswith("http") else f"{MEDIA_BASE}/{key.lstrip('/')}"


def repost_seeds(c) -> int:
    """The mirror of tapacuk93's Instagram (backend items, read-only) as ground truth and seeds:
    - a repost's original: scanned from its re-hosted copy (`reposted`), its author becomes a source,
      and it seeds recommendations;
    - the owner's own video posts: scanned as `mirror` (not shown among hits by default).
    After each scan learn.evaluate() checks whether the monitor had found it first."""
    import sqlite3
    if not os.path.exists(BACKEND_DB):
        return 0
    b = sqlite3.connect(f"file:{BACKEND_DB}?mode=ro", uri=True, timeout=10)
    b.row_factory = sqlite3.Row
    n = 0
    try:
        has_pub = "published_at" in {x[1] for x in b.execute("PRAGMA table_info(items)")}
        rows = b.execute(f"SELECT id, data, {'published_at' if has_pub else 'NULL AS published_at'} FROM items").fetchall()
    finally:
        b.close()
    from . import gate
    gate.ensure(c)
    for r in rows:
        item = json.loads(r["data"])
        pub = bool(r["published_at"])
        prio = 30 if pub else 2   # the gate: published items first, then the rest, before official scans
        linked = False
        rep = item.get("repost_of") or {}
        if rep:
            ex = rep.get("extra") or {}
            pk = ex.get("pk") or rep.get("shortcode")
            author = rep.get("author")
            for i, m in enumerate(rep.get("media") or []):
                if m.get("type") != "video" or not m.get("url"):
                    continue
                sid = None
                if author:
                    sid = "ig_" + registry.slug(author)
                    registry.upsert_source(c, sid, rep.get("author_name") or author, "reposted_author", "repost")
                    registry.upsert_account(c, sid, "instagram", author, ex.get("author_id"))
                v = {"id": f"mirror:ig:{pk}" + (f"#{i}" if i else ""), "platform": "instagram",
                     "url": rep.get("source_url") or f"https://www.instagram.com/p/{rep.get('shortcode')}/",
                     "media_url": _media_url(m["url"]), "title": (rep.get("caption") or "")[:300] or None,
                     "posted_at": rep.get("taken_at"), "duration": m.get("duration"), "thumbnail": m.get("thumbnail"),
                     "extra": {"pk": ex.get("pk"), "code": rep.get("shortcode"), "author": author,
                               "author_name": rep.get("author_name"), "author_id": ex.get("author_id"),
                               "seed_item": r["id"]}}
                if insert_video(c, v, None, "reposted", via=r["id"], hop=0, source_id=sid, queue=True):
                    n += 1
                gate.link(c, r["id"], f"r{i}", v["id"], pub)
                linked = True
                c.execute("UPDATE videos SET priority=MAX(priority, ?) WHERE id=? AND state IN ('new','queued')",
                          (prio, v["id"]))
        for i, m in enumerate(item.get("media") or []):
            if m.get("type") != "video" or not m.get("url"):
                continue
            v = {"id": f"mirror:{r['id']}#{i}", "platform": "instagram",
                 "url": item.get("source_url") or f"https://empire.earth/items/{r['id']}",
                 "media_url": _media_url(m["url"]), "title": (item.get("caption") or "")[:300] or None,
                 "posted_at": item.get("taken_at"), "duration": m.get("duration"), "thumbnail": None,
                 "extra": {"code": item.get("shortcode"), "item": r["id"], "author": "tapacuk93"}}
            if insert_video(c, v, None, "mirror", via=r["id"], hop=0, queue=True):
                n += 1
            gate.link(c, r["id"], str(i), v["id"], pub)
            linked = True
            c.execute("UPDATE videos SET priority=? WHERE id=? AND state IN ('new','queued')", (prio, v["id"]))
        if not linked:   # no video or audio: only its text can match
            gate.link(c, r["id"], "none", None, pub)
        caps = " ".join(x for x in (item.get("caption"), rep.get("caption")) if x)
        gate.link(c, r["id"], "caption", db.j(gate.caption_hits(c, caps, compiled_phrases(c))), pub)
    if n:
        ev("mirror_seeds", added=n)
    return n


def expand_one(c) -> int:
    """Follow the platform's recommendations around one seed: an owner's repost first, then the most
    confident hit. Found videos are `recommended`, `via` the seed, one hop further."""
    if db.setting(c, "rec.enabled") != "1":
        return 0
    if db.used(c, "rec.expansions") >= db.fsetting(c, "rec.daily_expansions"):
        return 0
    max_hops = int(db.fsetting(c, "rec.max_hops"))
    seed = None if not INSTAGRAM_DIRECT else c.execute("""SELECT v.*, NULL AS hit_id, NULL AS conf FROM videos v WHERE v.source_kind='reposted' AND v.expanded=0 AND v.state='done'
                        AND v.platform IN ('instagram','facebook','tiktok') ORDER BY v.discovered_at LIMIT 1""").fetchone()
    if not seed:
        seed = c.execute("""SELECT v.*, h.id AS hit_id, h.confidence AS conf FROM hits h JOIN videos v ON v.id=h.video_id
                            WHERE v.expanded=0 AND v.hop < ? AND h.confidence >= ? AND v.platform IN ('instagram','facebook','tiktok')
                            AND (v.platform != 'instagram' OR ?) ORDER BY h.confidence DESC LIMIT 1""",
                         (max_hops, db.fsetting(c, "rec.min_seed_confidence"), int(INSTAGRAM_DIRECT))).fetchone()
    if not seed:
        return 0
    platform = seed["platform"]
    if db.stopped(c, platform) or (platform == "instagram" and not (INSTAGRAM_DIRECT and instagram.session_exists())) \
            or (platform == "tiktok" and not tiktok.session_exists()):
        return 0
    extra = json.loads(seed["extra"] or "{}")
    via = seed["hit_id"] or seed["via"] or seed["id"]
    found: list[dict] = []
    try:
        if platform == "instagram":
            with instagram.Instagram(c) as ig:
                if extra.get("code"):
                    found += ig.around(extra["code"])
                if extra.get("author"):
                    found += ig.account_videos(extra["author"], extra.get("author_id"))[0][:4]
        elif platform == "tiktok":
            with tiktok.TikTok(c) as tt:
                found += tiktok.related(c, dict(seed), tt)
                if db.used(c, "rec.foryou") < 2:   # the For You feed, twice a day at most
                    db.add_usage(c, "rec.foryou")
                    found += tiktok.for_you(c, tt)[:4]
        else:
            with facebook.FacebookDL(c) as fb:
                fb.ensure_session()
                found += facebook.related(c, dict(seed) | {"extra": extra}, fb)
    except pace.Stop as e:
        if e.kind != "busy":
            pace.halt(c, e)
        return 0
    except Exception as e:  # noqa: BLE001
        ev("expand_failed", logging.WARNING, seed=seed["id"], error=repr(e)[:300])
        c.execute("UPDATE videos SET expanded=-1 WHERE id=?", (seed["id"],))
        return 0
    per = int(db.fsetting(c, "rec.per_seed"))
    n = 0
    for v in found[: per * 2]:
        if n >= per:
            break
        if insert_video(c, v, None, "recommended", via=via, hop=seed["hop"] + 1, queue=True):
            n += 1
    c.execute("UPDATE videos SET expanded=1 WHERE id=?", (seed["id"],))
    db.add_usage(c, "rec.expansions")
    ev("expanded", seed=seed["id"], via=via, platform=platform, found=len(found), queued=n)
    return n


# ------------------------------------------------------------------ loop
def setup(c) -> None:
    from . import highlights
    highlights.ensure(c)
    ensure_phrases(c)
    me = target_username()
    if db.setting(c, "target.username") != me:   # the archived account changed: read its follows again
        db.set_setting(c, "target.username", me)
        db.set_setting(c, "instagram.following_synced", "")
        db.set_setting(c, "facebook.following_synced", "")
    if telegram_api.session_exists():
        n = c.execute("""UPDATE videos SET state=CASE WHEN posted_at >= ? THEN 'queued' ELSE 'new' END, error=NULL
                         WHERE platform='telegram' AND state='blocked' AND error LIKE 'the Telegram preview%'""",
                      (time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() - 7 * 86400)),)).rowcount
        if n:
            ev("telegram_unblocked", videos=n)
    if registry.FILE.exists():
        mtime = str(int(registry.FILE.stat().st_mtime))
        if db.setting(c, "registry.loaded_mtime") != mtime:
            ev("registry_loaded", **registry.load_file(c))
            db.set_setting(c, "registry.loaded_mtime", mtime)
    c.execute("UPDATE videos SET state='queued' WHERE state='running'")


def loop() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    c = db.conn()
    setup(c)
    _heartbeat_thread()
    heartbeat(c, "monitor worker started", "start")
    last_seed = last_gate = 0.0
    while True:
        try:
            if db.setting(c, "monitor.enabled") != "1":
                time.sleep(60)
                continue
            if db.setting(c, "rescan.requested"):
                db.set_setting(c, "rescan.requested", "")
                rescan(c)
            if time.time() - last_gate > 120:
                last_gate = time.time()
                try:
                    from . import gate
                    gate.refresh(c)
                except Exception as e:  # noqa: BLE001
                    log.warning("gate refresh failed: %s", e)
            if time.time() - last_seed > 900:
                last_seed = time.time()
                setup(c)
                repost_seeds(c)
                try:
                    from . import highlights
                    highlights.suggest_phrases(c)
                except Exception as e:  # noqa: BLE001
                    log.warning("phrase suggestions failed: %s", e)
            busy = c.execute("SELECT 1 FROM videos WHERE state='queued' LIMIT 1").fetchone()
            discover(c, browsers=not busy or time.time() - _last_browser > 1200)
            v = pick(c)
            if v:
                scan(c, v)
                continue
            if expand_one(c):
                continue
            time.sleep(30)
        except Exception as e:  # noqa: BLE001 - the loop never dies
            ev("loop_error", logging.ERROR, error=repr(e)[:500])
            time.sleep(60)


if __name__ == "__main__":
    loop()
