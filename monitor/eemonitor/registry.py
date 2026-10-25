"""The source registry: official accounts from monitor/sources.json (data, edited by hand or by PR),
accounts the owner adds (API / CLI), accounts tapacuk93 follows, authors of the owner's reposts,
and one-off sources found through recommendations.

A source is an entity (the Kremlin, the UN); an account is its presence on one platform. Every
source has expected languages; [] means unknown, and those are inferred from scans (see
`infer_languages`).
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from . import db

FILE = Path(__file__).resolve().parents[1] / "sources.json"
PLATFORMS = ("youtube", "telegram", "x", "instagram", "facebook", "tiktok", "vk", "rutube")
SCANNED = ("youtube", "telegram", "x", "instagram", "facebook")


def slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", s.lower()).strip("_")[:60] or "source"


def upsert_source(c, sid: str, name: str, source_kind: str, origin: str, expected=None, kind=None,
                  country=None, source_url=None, data=None, keep_languages=True) -> None:
    row = c.execute("SELECT expected_languages, languages_inferred FROM sources WHERE id=?", (sid,)).fetchone()
    langs = expected or []
    if row and keep_languages and not expected:
        langs = json.loads(row["expected_languages"])
    c.execute("""INSERT INTO sources(id, name, kind, country, source_kind, expected_languages, origin, source_url,
                 data, created_at) VALUES (?,?,?,?,?,?,?,?,?,?)
                 ON CONFLICT(id) DO UPDATE SET name=excluded.name, kind=COALESCE(excluded.kind, kind),
                 country=COALESCE(excluded.country, country), expected_languages=excluded.expected_languages,
                 source_url=COALESCE(excluded.source_url, source_url),
                 source_kind=CASE WHEN sources.source_kind='official' THEN 'official' ELSE excluded.source_kind END""",
              (sid, name, kind, country, source_kind, db.j(langs), origin, source_url, db.j(data or {}), db.now()))


def upsert_account(c, sid: str, platform: str, handle: str, platform_id=None, url=None) -> int:
    handle = handle.lstrip("@").strip()
    c.execute("""INSERT INTO accounts(source_id, platform, handle, platform_id, url, next_poll_at)
                 VALUES (?,?,?,?,?,?) ON CONFLICT(platform, handle) DO UPDATE SET
                 platform_id=COALESCE(excluded.platform_id, platform_id), url=COALESCE(excluded.url, url)""",
              (sid, platform, handle, platform_id, url, db.now()))
    return c.execute("SELECT id FROM accounts WHERE platform=? AND handle=?", (platform, handle)).fetchone()["id"]


def load_file(c, path: Path = FILE) -> dict:
    data = json.loads(path.read_text())
    n_s = n_a = 0
    for s in data.get("sources", []):
        sid = s.get("id") or slug(s["name"])
        upsert_source(c, sid, s["name"], "official", "registry", s.get("expected_languages") or [],
                      s.get("kind"), s.get("country"), s.get("source_url"), keep_languages=False)
        n_s += 1
        for a in s.get("accounts", []):
            if a.get("platform") not in PLATFORMS:
                continue
            handle = a.get("handle") or a.get("channel_id")
            if not handle:
                continue
            pid = a.get("channel_id") if a["platform"] == "youtube" else a.get("id")
            if a["platform"] == "youtube" and not pid:
                continue   # the feed needs the channel id
            upsert_account(c, sid, a["platform"], pid if a["platform"] == "youtube" else handle, pid,
                           a.get("url"))
            n_a += 1
    return {"sources": n_s, "accounts": n_a}


def add_owner_source(c, body: dict) -> dict:
    """{"name", "platform", "handle", "expected_languages"?, "kind"?, "country"?, "channel_id"?}"""
    platform = body.get("platform")
    handle = (body.get("handle") or body.get("channel_id") or "").lstrip("@")
    if platform not in PLATFORMS or not handle or not body.get("name"):
        raise ValueError("needs name, platform (one of %s) and handle" % ", ".join(PLATFORMS))
    sid = body.get("id") or slug(body["name"])
    upsert_source(c, sid, body["name"], body.get("source_kind") or "official", "owner",
                  body.get("expected_languages") or [], body.get("kind"), body.get("country"), body.get("source_url"))
    aid = upsert_account(c, sid, platform, handle, body.get("channel_id") or body.get("platform_id"))
    return {"source_id": sid, "account_id": aid}


def infer_languages(c, source_id: str) -> list[str]:
    """For a source without expected languages: those making up at least a quarter of the speech of
    its scanned videos (at least two videos, or one of over a minute of speech)."""
    rows = c.execute("SELECT languages FROM videos WHERE source_id=? AND state='done' AND languages IS NOT NULL",
                     (source_id,)).fetchall()
    tot: dict[str, float] = {}
    for r in rows:
        for k, v in json.loads(r["languages"]).items():
            tot[k] = tot.get(k, 0) + v
    s = sum(tot.values())
    if not s or (len(rows) < 2 and s < 60):
        return []
    langs = [k for k, v in tot.items() if v / s >= 0.25]
    c.execute("UPDATE sources SET expected_languages=?, languages_inferred=1 WHERE id=? "
              "AND (expected_languages='[]' OR languages_inferred=1)", (db.j(langs), source_id))
    return langs
