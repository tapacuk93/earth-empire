"""The publication gate for the mirrored archive (CONTRACT.md "Detection gate").

Nothing outside the detection criteria may be public - the mirrored trsmslv items included. Every
backend item (post, carousel, reel, story, highlight story, repost) is checked with the monitor's own
detectors: its own videos, and for a repost the original's audio (the collector's copy on the media
host). The result goes to the backend as the item's `detection`; the backend publishes an item only
when `detection.matched` is true. Items with no audio, or whose audio could not be scanned, are
`matched: false` (with `complete: false` when something could not be scanned).

    detection = {"matched", "complete", "checked_at", "model", "reason"?,
                 "media": [{"media": "0" | "r0", "video_id", "state", "error"?}],
                 "hits": [{"kind", "phrase" | null, "lang", "media", "at", "end", "confidence", "label",
                           "excerpt", "translation"}]}
"""
from __future__ import annotations

import json
import logging
import os

from . import db, detect

log = logging.getLogger("ee.monitor.gate")
API = os.environ.get("EE_API_URL", "http://127.0.0.1:8000").rstrip("/")
SCHEMA = """
CREATE TABLE IF NOT EXISTS mirror_items (      -- which videos make up each backend item
  item_id TEXT NOT NULL, media TEXT NOT NULL, video_id TEXT, published INTEGER NOT NULL DEFAULT 0,
  PRIMARY KEY (item_id, media)
);
CREATE TABLE IF NOT EXISTS detections (         -- the gate's result per item, and whether the backend has it
  item_id TEXT PRIMARY KEY, detection TEXT NOT NULL, matched INTEGER NOT NULL, computed_at TEXT NOT NULL,
  synced_at TEXT, sync_error TEXT, signature TEXT
);
"""


def ensure(c) -> None:
    c.executescript(SCHEMA)


def link(c, item_id: str, media: str, video_id: str | None, published: bool) -> None:
    c.execute("""INSERT INTO mirror_items(item_id, media, video_id, published) VALUES (?,?,?,?)
                 ON CONFLICT(item_id, media) DO UPDATE SET video_id=excluded.video_id, published=excluded.published""",
              (item_id, media, video_id, int(published)))


def caption_hits(c, text: str | None, phrases: list[dict]) -> list[dict]:
    """Phrase matches in a caption (a pseudo-transcript with every word certain)."""
    if not text:
        return []
    words, t = [], 0.0
    for w in text.split():
        words.append([" " + w, t, t + 0.3, 1.0])
        t += 0.4
    tr = {"chunks": [{"start": 0, "end": t, "lang": None, "words": words, "text": text}]}
    return [{k: h[k] for k in ("phrase", "matched", "confidence", "excerpt")}
            for h in detect.find_name(tr, db.fsetting(c, "name.min_confidence"), phrases)]


def compute(c, item_id: str) -> dict | None:
    """The item's detection, or None while one of its videos still waits to be scanned."""
    rows = c.execute("SELECT * FROM mirror_items WHERE item_id=? ORDER BY media", (item_id,)).fetchall()
    media, hits, complete, model = [], [], True, None
    for r in rows:
        if r["media"] == "caption":
            for d in json.loads(r["video_id"] or "[]"):
                hits.append({"kind": "name", "phrase": d.get("phrase"), "lang": None, "media": None, "source": "caption",
                             "at": None, "end": None, "confidence": d["confidence"], "label": detect.label(d["confidence"]),
                             "excerpt": d.get("excerpt"), "translation": None, "matched_words": d.get("matched")})
            continue
        if not r["video_id"]:
            continue
        v = c.execute("SELECT id, state, error, model FROM videos WHERE id=?", (r["video_id"],)).fetchone()
        if not v:
            continue
        if v["state"] in ("new", "queued", "running"):
            return None
        rep_ = r["media"].startswith("r")
        idx = int(r["media"].lstrip("r") or 0)
        m = {"media": idx, "repost": rep_, "video_id": v["id"], "state": v["state"]}
        if v["state"] != "done":
            complete = False
            m["error"] = (v["error"] or "")[:200]
        model = model or v["model"]
        media.append(m)
        for h in c.execute("SELECT data FROM hits WHERE video_id=? ORDER BY confidence DESC", (v["id"],)):
            d = json.loads(h["data"])
            hits.append({"kind": d["kind"], "phrase": d.get("phrase"), "lang": d.get("language"),
                         "media": idx, "repost": rep_, "at": d["start"], "end": d["end"], "confidence": d["confidence"],
                         "label": detect.label(d["confidence"]), "excerpt": d.get("excerpt"),
                         "translation": d.get("excerpt_en"), "matched_words": d.get("matched")})
    hits.sort(key=lambda h: -h["confidence"])
    det = {"matched": bool(hits), "complete": complete, "scanned_at": db.now(), "model": model,
           "media": media, "hits": hits}
    if not media and not hits:
        det["reason"] = "no video or audio in this item, and no match in its text"
    elif not hits:
        det["reason"] = "no phrase match and no out-of-place Ukrainian/Russian speech" + \
                        ("" if complete else " (some media could not be scanned)")
    return det


def refresh(c) -> int:
    """Compute detections for items whose videos are all scanned; push new or changed ones."""
    ensure(c)
    n = 0
    for (item_id,) in c.execute("SELECT DISTINCT item_id FROM mirror_items").fetchall():
        det = compute(c, item_id)
        if det is None:
            continue
        sig = json.dumps({k: det[k] for k in ("matched", "complete", "media", "hits")}, sort_keys=True, ensure_ascii=False)
        old = c.execute("SELECT signature FROM detections WHERE item_id=?", (item_id,)).fetchone()
        if old and old["signature"] == sig:
            continue
        c.execute("""INSERT INTO detections(item_id, detection, matched, computed_at, signature) VALUES (?,?,?,?,?)
                     ON CONFLICT(item_id) DO UPDATE SET detection=excluded.detection, matched=excluded.matched,
                     computed_at=excluded.computed_at, signature=excluded.signature, synced_at=NULL""",
                  (item_id, db.j(det), int(det["matched"]), db.now(), sig))
        n += 1
    push(c)
    return n


def push(c) -> int:
    """PUT /v1/ingest/detections to the backend for every unsynced item, 50 at a time."""
    import httpx
    rows = c.execute("SELECT item_id, detection FROM detections WHERE synced_at IS NULL LIMIT 50").fetchall()
    if not rows:
        return 0
    try:
        from ee import config
        tok = config.secret("ingest_token")
        tok = tok.get("token") or tok.get("value") if isinstance(tok, dict) else tok
        r = httpx.put(API + "/v1/ingest/detections", timeout=30, headers={"Authorization": f"Bearer {tok}"},
                      json={"detections": [{"id": x["item_id"], "detection": json.loads(x["detection"])} for x in rows]})
        if r.status_code >= 400:
            raise RuntimeError(f"HTTP {r.status_code}: {r.text[:200]}")
    except Exception as e:  # noqa: BLE001 - kept and retried; the backend may not have the route yet
        c.executemany("UPDATE detections SET sync_error=? WHERE item_id=?", [(str(e)[:300], x["item_id"]) for x in rows])
        log.warning("detections not pushed (%d items): %s", len(rows), e)
        return 0
    c.executemany("UPDATE detections SET synced_at=?, sync_error=NULL WHERE item_id=?",
                  [(db.now(), x["item_id"]) for x in rows])
    log.info(json.dumps({"event": "monitor.detections_pushed", "items": len(rows)}))
    return len(rows)


def summary(c, published_only: bool = False) -> dict:
    ensure(c)
    where = "WHERE item_id IN (SELECT item_id FROM mirror_items WHERE published=1)" if published_only else ""
    tot = c.execute("SELECT COUNT(DISTINCT item_id) n FROM mirror_items" +
                    (" WHERE published=1" if published_only else "")).fetchone()["n"]
    r = c.execute(f"SELECT COUNT(*) n, SUM(matched) m, SUM(synced_at IS NOT NULL) s FROM detections {where}").fetchone()
    return {"items": tot, "checked": r["n"], "matched": r["m"] or 0, "not_matched": (r["n"] or 0) - (r["m"] or 0),
            "pending": tot - (r["n"] or 0), "pushed": r["s"] or 0}
