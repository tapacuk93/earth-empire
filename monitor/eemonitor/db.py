"""The monitor's own SQLite: sources, accounts, videos, hits, fetch requests, costs, stops.

Kept apart from the backend's database (its own file under /var/lib/earth-empire/monitor/) so the
monitor can be redeployed, wiped or moved without touching the archive.
"""
from __future__ import annotations

import json
import os
import sqlite3
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path

DATA_DIR = Path(os.environ.get("EE_MONITOR_DIR", "/var/lib/earth-empire/monitor"))
DB_PATH = Path(os.environ.get("EE_MONITOR_DB", str(DATA_DIR / "monitor.sqlite3")))

SCHEMA = """
CREATE TABLE IF NOT EXISTS sources (
  id TEXT PRIMARY KEY, name TEXT NOT NULL, kind TEXT, country TEXT,
  source_kind TEXT NOT NULL,             -- official | followed | reposted_author | recommended
  expected_languages TEXT NOT NULL DEFAULT '[]',   -- [] = unknown, inferred from scans
  languages_inferred INTEGER NOT NULL DEFAULT 0,
  origin TEXT NOT NULL,                  -- registry | owner | instagram_following | repost | recommendation
  source_url TEXT, data TEXT NOT NULL DEFAULT '{}', created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS accounts (
  id INTEGER PRIMARY KEY, source_id TEXT NOT NULL, platform TEXT NOT NULL, handle TEXT NOT NULL,
  platform_id TEXT, url TEXT, enabled INTEGER NOT NULL DEFAULT 1,
  next_poll_at TEXT, last_polled_at TEXT, backfill_cursor TEXT, backfill_done INTEGER NOT NULL DEFAULT 0,
  polls INTEGER NOT NULL DEFAULT 0, last_error TEXT,
  UNIQUE(platform, handle)
);
CREATE TABLE IF NOT EXISTS videos (
  id TEXT PRIMARY KEY,                   -- <platform>:<platform id>
  platform TEXT NOT NULL, account_id INTEGER, source_id TEXT,
  source_kind TEXT NOT NULL, via TEXT, hop INTEGER NOT NULL DEFAULT 0,
  url TEXT NOT NULL, media_url TEXT, title TEXT, posted_at TEXT, duration REAL, thumbnail TEXT,
  state TEXT NOT NULL DEFAULT 'new',     -- new | queued | running | done | failed | blocked | skipped
  priority INTEGER NOT NULL DEFAULT 0, requested INTEGER NOT NULL DEFAULT 0,
  attempts INTEGER NOT NULL DEFAULT 0, next_at TEXT, error TEXT,
  discovered_at TEXT NOT NULL, scanned_at TEXT,
  transcript TEXT, languages TEXT, audio_s REAL, cpu_s REAL, model TEXT,
  expanded INTEGER NOT NULL DEFAULT 0, extra TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS videos_state ON videos(state, priority DESC, posted_at DESC);
CREATE INDEX IF NOT EXISTS videos_account ON videos(account_id, posted_at DESC);
CREATE TABLE IF NOT EXISTS hits (
  id TEXT PRIMARY KEY, video_id TEXT NOT NULL, kind TEXT NOT NULL, start REAL, "end" REAL,
  confidence REAL NOT NULL, data TEXT NOT NULL, found_at TEXT NOT NULL,
  published_at TEXT, verdict TEXT
);
CREATE INDEX IF NOT EXISTS hits_conf ON hits(confidence DESC);
CREATE INDEX IF NOT EXISTS hits_video ON hits(video_id);
CREATE TABLE IF NOT EXISTS requests (
  id INTEGER PRIMARY KEY, n INTEGER NOT NULL, remaining INTEGER NOT NULL, filters TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL, done_at TEXT
);
CREATE TABLE IF NOT EXISTS costs (
  id INTEGER PRIMARY KEY, at TEXT NOT NULL, purpose TEXT, video_id TEXT, usd REAL, coins REAL, note TEXT
);
CREATE TABLE IF NOT EXISTS usage (            -- per day and counter: requests, audio seconds
  day TEXT NOT NULL, counter TEXT NOT NULL, value REAL NOT NULL DEFAULT 0, PRIMARY KEY(day, counter)
);
CREATE TABLE IF NOT EXISTS stops (            -- a platform paused: checkpoint, warning, billing, login
  platform TEXT PRIMARY KEY, kind TEXT NOT NULL, message TEXT, at TEXT NOT NULL, until TEXT
);
CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS mirror_checks (       -- every mirrored item (the owner's posts, reposts' originals) checked
  video_id TEXT PRIMARY KEY, item_id TEXT, at TEXT NOT NULL, matched INTEGER NOT NULL,
  found_first INTEGER NOT NULL DEFAULT 0, independent_video TEXT, detail TEXT NOT NULL DEFAULT '{}'
);
CREATE TABLE IF NOT EXISTS misses (
  id INTEGER PRIMARY KEY, at TEXT NOT NULL, video_id TEXT, item_id TEXT, kind TEXT, phrase TEXT,
  cause TEXT NOT NULL, detail TEXT NOT NULL DEFAULT '{}'
);
CREATE TABLE IF NOT EXISTS improvements (
  id INTEGER PRIMARY KEY, at TEXT NOT NULL, cause TEXT, change TEXT NOT NULL, reason TEXT NOT NULL,
  applied INTEGER NOT NULL,          -- 1 made automatically (within bounds), 0 a suggestion for the owner
  detail TEXT NOT NULL DEFAULT '{}'
);
CREATE TABLE IF NOT EXISTS phrases (            -- what to listen for; variants generated on save
  text TEXT PRIMARY KEY, position INTEGER NOT NULL DEFAULT 0, compiled TEXT NOT NULL,
  claude_variants TEXT NOT NULL DEFAULT '[]', updated_at TEXT NOT NULL
);
"""

DEFAULTS = {
    "monitor.enabled": "1",
    # Transcription on the box's CPU (faster-whisper). Caps are in minutes of audio per UTC day.
    "whisper.model": "small",
    "whisper.beam_size": "1",
    "scan.daily_audio_minutes": "240",           # official + followed + reposted
    "scan.recommended_daily_audio_minutes": "60",  # recommendations, their own quota
    "scan.mirror_daily_audio_minutes": "600",     # the publication gate over the mirrored archive
    "scan.max_video_minutes": "40",               # longer videos wait for an explicit request
    "scan.auto_latest_per_account": "2",          # on first sight, queue only the newest N of an account
    "fetch.max_n": "50",
    # Claude (through the aicoin proxy): translations of excerpts and judging borderline name hits.
    "claude.enabled": "1",
    "claude.daily_usd": "0.50",
    "claude.model": "claude-haiku-4-5",
    # Detection thresholds: recall over precision; low hits are kept and labelled.
    "name.min_confidence": "0.03",
    "language.min_seconds": "3",
    "language.min_prob": "0.35",
    # Polling and pacing per platform.
    "poll.minutes": "90",
    "telegram.enabled": "1", "telegram.daily_requests": "600", "telegram_api.daily_downloads": "60",
    "youtube.enabled": "0", "youtube.daily_requests": "400",
    "x.enabled": "0", "x.daily_requests": "50",
    "instagram.enabled": "1", "instagram.daily_requests": "300",
    "facebook.enabled": "1", "facebook.daily_requests": "200",
    "tiktok.enabled": "1", "tiktok.daily_requests": "120",
    # Recommendations around seeds (hits and the owner's reposts).
    "rec.enabled": "1", "rec.max_hops": "2", "rec.daily_expansions": "20",
    "rec.min_seed_confidence": "0.25", "rec.per_seed": "8",
}

_local = threading.local()


def now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def later(seconds: float) -> str:
    return (datetime.now(timezone.utc) + timedelta(seconds=seconds)).strftime("%Y-%m-%dT%H:%M:%SZ")


def today() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def connect(path: Path | None = None) -> sqlite3.Connection:
    path = Path(path or DB_PATH)
    path.parent.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(path, timeout=30, isolation_level=None, check_same_thread=False)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA journal_mode=WAL")
    c.execute("PRAGMA synchronous=NORMAL")
    c.executescript(SCHEMA)
    for k, v in DEFAULTS.items():
        c.execute("INSERT OR IGNORE INTO settings(key, value) VALUES (?, ?)", (k, v))
    cols = {r["name"] for r in c.execute("PRAGMA table_info(accounts)")}
    if "priority" not in cols:
        c.execute("ALTER TABLE accounts ADD COLUMN priority INTEGER NOT NULL DEFAULT 0")
    hcols = {r["name"] for r in c.execute("PRAGMA table_info(hits)")}
    if "section" not in hcols:
        c.execute("ALTER TABLE hits ADD COLUMN section TEXT")   # no longer used (kept for older readers)
    if "ai_level" not in hcols:
        c.execute("ALTER TABLE hits ADD COLUMN ai_level INTEGER")   # 1 (highest) .. 4, judged by Claude
    if "level" not in hcols:
        c.execute("ALTER TABLE hits ADD COLUMN level INTEGER")      # the level it was approved at (owner override or AI)
    return c


def conn() -> sqlite3.Connection:
    c = getattr(_local, "conn", None)
    if c is None:
        c = _local.conn = connect()
    return c


def setting(c, key: str) -> str:
    r = c.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
    return r["value"] if r else DEFAULTS.get(key, "")


def fsetting(c, key: str) -> float:
    try:
        return float(setting(c, key))
    except ValueError:
        return float(DEFAULTS.get(key, "0") or 0)


def set_setting(c, key: str, value) -> None:
    c.execute("INSERT INTO settings(key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
              (key, str(value)))


def used(c, counter: str, day: str | None = None) -> float:
    r = c.execute("SELECT value FROM usage WHERE day=? AND counter=?", (day or today(), counter)).fetchone()
    return r["value"] if r else 0.0


def add_usage(c, counter: str, amount: float = 1.0) -> None:
    c.execute("INSERT INTO usage(day, counter, value) VALUES (?, ?, ?) "
              "ON CONFLICT(day, counter) DO UPDATE SET value = value + excluded.value", (today(), counter, amount))


def j(v) -> str:
    return json.dumps(v, ensure_ascii=False, separators=(",", ":"))


def stopped(c, platform: str):
    """The platform's stop record when it is paused now, else None."""
    r = c.execute("SELECT * FROM stops WHERE platform=?", (platform,)).fetchone()
    if not r:
        return None
    if r["until"] and r["until"] <= now():
        c.execute("DELETE FROM stops WHERE platform=?", (platform,))
        return None
    return r


def stop(c, platform: str, kind: str, message: str, seconds: float | None = None) -> None:
    c.execute("INSERT INTO stops(platform, kind, message, at, until) VALUES (?,?,?,?,?) ON CONFLICT(platform) "
              "DO UPDATE SET kind=excluded.kind, message=excluded.message, at=excluded.at, until=excluded.until",
              (platform, kind, message[:1000], now(), later(seconds) if seconds else None))
