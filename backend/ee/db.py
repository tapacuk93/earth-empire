"""SQLite: the archive, its pipeline states, runs and costs.

One file on the box's disk, WAL mode, backed up to S3 daily (ee backup). Every item's own fields
are kept as the JSON the collector sent (media URLs reduced to keys); what the backend adds lives in
columns beside it.
"""
from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path

from . import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS items (
  id TEXT PRIMARY KEY,
  kind TEXT NOT NULL,
  taken_at TEXT NOT NULL,
  data TEXT NOT NULL,            -- the item as ingested, media as keys
  content_hash TEXT NOT NULL,    -- caption + media; a change means analyze again
  categories TEXT NOT NULL DEFAULT '[]',
  summary TEXT, description TEXT, analysis TEXT,
  published_at TEXT,             -- when it went public (analysis done)
  covers TEXT NOT NULL DEFAULT '{}',  -- {"0": {"cover": key, "cover_at": s}, "r0": ...} for videos
  thumbs TEXT,                   -- {"0": key, "r0": key}: generated thumbnails; NULL = not made yet
  collected_at TEXT, updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS items_taken ON items(taken_at DESC, id DESC);
CREATE INDEX IF NOT EXISTS items_kind ON items(kind, taken_at DESC);

CREATE TABLE IF NOT EXISTS item_categories (item_id TEXT, slug TEXT, PRIMARY KEY(item_id, slug));
CREATE INDEX IF NOT EXISTS item_categories_slug ON item_categories(slug);
CREATE TABLE IF NOT EXISTS item_highlights (item_id TEXT, highlight_id TEXT, PRIMARY KEY(item_id, highlight_id));
CREATE INDEX IF NOT EXISTS item_highlights_hl ON item_highlights(highlight_id);

CREATE TABLE IF NOT EXISTS item_tags (item_id TEXT, tag TEXT, kind TEXT, PRIMARY KEY(item_id, tag, kind));
CREATE INDEX IF NOT EXISTS item_tags_tag ON item_tags(tag);

CREATE TABLE IF NOT EXISTS categories (
  slug TEXT PRIMARY KEY, name TEXT NOT NULL, description TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL, created_by_item TEXT
);
CREATE TABLE IF NOT EXISTS highlights (
  id TEXT PRIMARY KEY, title TEXT, cover TEXT, item_ids TEXT NOT NULL DEFAULT '[]',
  position INTEGER NOT NULL DEFAULT 0, data TEXT NOT NULL DEFAULT '{}', updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS profile (id INTEGER PRIMARY KEY CHECK (id = 1), data TEXT NOT NULL, updated_at TEXT NOT NULL);

-- The pipeline: one row per item and step. step: analyze | site | x | facebook.
-- state: pending | running | done (analyze) | posted | failed | skipped
CREATE TABLE IF NOT EXISTS steps (
  item_id TEXT NOT NULL, step TEXT NOT NULL, state TEXT NOT NULL,
  attempts INTEGER NOT NULL DEFAULT 0, next_at TEXT, last_error TEXT,
  remote_id TEXT, remote_url TEXT, detail TEXT,
  updated_at TEXT NOT NULL,
  PRIMARY KEY (item_id, step)
);
CREATE INDEX IF NOT EXISTS steps_state ON steps(step, state, next_at);

CREATE TABLE IF NOT EXISTS transitions (
  id INTEGER PRIMARY KEY, at TEXT NOT NULL, item_id TEXT, step TEXT, from_state TEXT, to_state TEXT, note TEXT
);
CREATE TABLE IF NOT EXISTS runs (            -- collector runs
  id INTEGER PRIMARY KEY, started_at TEXT, finished_at TEXT, ok INTEGER, counts TEXT, log_url TEXT,
  received_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS costs (           -- every paid call
  id INTEGER PRIMARY KEY, at TEXT NOT NULL, item_id TEXT, purpose TEXT, model TEXT,
  input_tokens INTEGER, output_tokens INTEGER, coins REAL, usd REAL, ok INTEGER, note TEXT
);
CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
-- Home layout: one embedding per published item or hit ("hit:<id>"), and its place in its half.
CREATE TABLE IF NOT EXISTS embeddings (
  id TEXT PRIMARY KEY, kind TEXT NOT NULL, text_hash TEXT NOT NULL, vec BLOB NOT NULL, updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS layout (
  id TEXT PRIMARY KEY, half TEXT NOT NULL, x REAL NOT NULL, y REAL NOT NULL, placed TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
-- What runs right now (one row per lane or reporting part), for GET /v1/status.
CREATE TABLE IF NOT EXISTS jobs (
  id TEXT PRIMARY KEY, component TEXT NOT NULL, what TEXT NOT NULL, item_id TEXT,
  progress TEXT, started_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
-- Heartbeats from the parts (collector, monitor, ...): POST /v1/ingest/heartbeat.
CREATE TABLE IF NOT EXISTS heartbeats (
  component TEXT PRIMARY KEY, at TEXT NOT NULL, ok INTEGER NOT NULL, detail TEXT NOT NULL DEFAULT '{}',
  last_ok_at TEXT, last_error_at TEXT, last_error TEXT
);
-- Notable events that are not pipeline transitions (backups, pauses, site builds, ...).
CREATE TABLE IF NOT EXISTS events (
  id INTEGER PRIMARY KEY, at TEXT NOT NULL, component TEXT NOT NULL, kind TEXT NOT NULL,
  text TEXT NOT NULL, item_id TEXT, ok INTEGER NOT NULL DEFAULT 1
);
CREATE INDEX IF NOT EXISTS events_at ON events(at);
CREATE VIRTUAL TABLE IF NOT EXISTS items_fts USING fts5(id UNINDEXED, body, tokenize='unicode61 remove_diacritics 2');
"""

DEFAULT_SETTINGS = {
    # The cost guard: at most this many analyses a day. Raised by the owner (ee settings set ...)
    # once the backlog estimate is approved.
    "analysis.daily_cap": "20",
    "analysis.enabled": "1",
    "x.enabled": "0",           # turned on once earth-empire/x holds real keys
    "x.dry_run": "1",
    "x.interval_minutes": "30",
    "x.daily_cap": "40",
    "facebook.enabled": "0",    # turned on once earth-empire/facebook-session holds a session
    "facebook.dry_run": "1",
    "facebook.daily_cap": "4",
    "facebook.min_gap_minutes": "120",
    "facebook.max_gap_minutes": "300",
    "facebook.active_hours": "9-22",
    "facebook.timezone": "Europe/Kyiv",
    "facebook.paused_until": "",
    "x.paused_until": "",
    "site.auto_build": "1",     # rebuild and publish the site when items go public
    "site.built_at": "",
}

STEPS = ("analyze", "site", "x", "facebook")
MAX_ATTEMPTS = 8

_local = threading.local()


def now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def connect(path: Path | None = None) -> sqlite3.Connection:
    path = Path(path or config.DB_PATH)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, timeout=30, isolation_level=None, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.executescript(SCHEMA)
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(items)")}
    if "thumbs" not in cols:   # added 2026-10-25
        conn.execute("ALTER TABLE items ADD COLUMN thumbs TEXT")
    if "importance" not in cols:   # added 2026-10-25: 0-1, judged by Claude
        conn.execute("ALTER TABLE items ADD COLUMN importance REAL")
    for k, v in DEFAULT_SETTINGS.items():
        conn.execute("INSERT OR IGNORE INTO settings(key, value) VALUES (?, ?)", (k, v))
    return conn


def conn() -> sqlite3.Connection:
    """One connection per thread."""
    c = getattr(_local, "conn", None)
    if c is None:
        c = _local.conn = connect()
    return c


def reset_thread_conn() -> None:
    c = getattr(_local, "conn", None)
    if c is not None:
        c.close()
        _local.conn = None


class tx:
    """BEGIN IMMEDIATE ... COMMIT, so a read-modify-write cannot interleave with another writer."""

    def __init__(self, c: sqlite3.Connection):
        self.c = c

    def __enter__(self):
        self.c.execute("BEGIN IMMEDIATE")
        return self.c

    def __exit__(self, typ, *_):
        self.c.execute("ROLLBACK" if typ else "COMMIT")


def setting(c: sqlite3.Connection, key: str) -> str:
    row = c.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else DEFAULT_SETTINGS.get(key, "")


def set_setting(c: sqlite3.Connection, key: str, value: str) -> None:
    c.execute("INSERT INTO settings(key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
              (key, str(value)))


def j(value) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))
