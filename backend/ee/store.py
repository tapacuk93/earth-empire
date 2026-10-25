"""Earth Empire's item store - reads and writes: ingest upserts, rendering for the API, search, pipeline steps."""
from __future__ import annotations

import base64
import hashlib
import json
import logging
import re
import sqlite3
from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse

from . import config
from .db import MAX_ATTEMPTS, STEPS, j, now, tx
from .logs import event

BACKEND_FIELDS = ("categories", "summary", "description", "analysis", "published_at")
MEDIA_PREFIX = "key:"   # stored form of a re-hosted URL; the host is added on output


# ------------------------------------------------------------------ media URLs
def to_key(url):
    """A media URL on any of our hosts -> 'key:items/..'. Anything else is kept as it is."""
    if not url or not isinstance(url, str) or url.startswith(MEDIA_PREFIX):
        return url
    u = urlparse(url)
    if u.scheme in ("http", "https") and u.hostname and (
            u.hostname in config.MEDIA_HOSTS or u.hostname.endswith(".cloudfront.net")):
        return MEDIA_PREFIX + u.path.lstrip("/")
    if not u.scheme and not url.startswith("/"):   # a bare key
        return MEDIA_PREFIX + url
    if u.hostname and ("cdninstagram" in u.hostname or "fbcdn" in u.hostname):
        event("ingest.foreign_media_url", logging.WARNING, host=u.hostname)
    return url


def to_url(value):
    if isinstance(value, str) and value.startswith(MEDIA_PREFIX):
        return f"{config.MEDIA_BASE_URL}/{value[len(MEDIA_PREFIX):]}"
    return value


def media_key(value):
    """The S3 key behind a stored or rendered media URL, or None."""
    k = to_key(value)
    return k[len(MEDIA_PREFIX):] if isinstance(k, str) and k.startswith(MEDIA_PREFIX) else None


def _map_media(item: dict, fn) -> dict:
    for m in item.get("media") or []:
        for f in ("url", "thumbnail"):
            if m.get(f):
                m[f] = fn(m[f])
    rep = item.get("repost_of")
    if isinstance(rep, dict):
        for m in rep.get("media") or []:
            for f in ("url", "thumbnail"):
                if m.get(f):
                    m[f] = fn(m[f])
    return item


def content_hash(item: dict) -> str:
    rep = item.get("repost_of") or {}
    basis = {
        "caption": item.get("caption"),
        "media": [m.get("url") for m in item.get("media") or []],
        "repost": [rep.get("caption"), [m.get("url") for m in rep.get("media") or []]],
    }
    return hashlib.sha256(j(basis).encode()).hexdigest()[:24]


# ------------------------------------------------------------------ what may be public
def has_video(d: dict) -> bool:
    media = (d.get("media") or []) + ((d.get("repost_of") or {}).get("media") or [])
    return any((m or {}).get("type") == "video" for m in media)


def publishable(d: dict) -> tuple[bool, str | None]:
    """An image-only repost (someone else's photo, in a post or a story) is never public.
    A repost of a video is, and so is everything the account posted itself."""
    if d.get("repost_of") and not has_video(d):
        return False, "image-only repost: someone else's photo"
    return True, None


def gate(c, item_id: str) -> tuple[bool, str]:
    """Is this item from the owner's profile public? Every mirrored item of the account is, once analyzed, unless it
    is an image-only repost. A monitor detection is context (shown and used as a start point), never
    a condition. Apply the answer: publish (site step posted, the posters may post) or unpublish
    (site skipped; X/Facebook skipped unless they already posted)."""
    row = c.execute("SELECT data, analysis, detection, published_at FROM items WHERE id=?", (item_id,)).fetchone()
    if not row:
        return False, "no such item"
    ok, why = publishable(json.loads(row["data"]))
    if not row["analysis"]:
        public, why = False, "not analyzed yet"
    elif not ok:
        public = False
    else:
        public, why = True, "analyzed"
    ts = now()
    if public and not row["published_at"]:
        c.execute("UPDATE items SET published_at=? WHERE id=?", (ts, item_id))
    elif not public and row["published_at"]:
        c.execute("UPDATE items SET published_at=NULL WHERE id=?", (item_id,))
        c.execute("DELETE FROM layout WHERE id=?", (item_id,))
        c.execute("DELETE FROM embeddings WHERE id=?", (item_id,))
    states = {r["step"]: r["state"] for r in c.execute("SELECT step, state FROM steps WHERE item_id=?", (item_id,))}
    if public:
        if states.get("site") != "posted":
            _set_step(c, item_id, "site", "posted", remote_id=item_id, note=why)
        for step in ("x", "facebook"):
            if states.get(step) == "skipped":
                _set_step(c, item_id, step, "pending", note=why)
    else:
        target = "pending" if why == "not analyzed yet" else "skipped"
        if states.get("site") != target:
            _set_step(c, item_id, "site", target, note=why)
        for step in ("x", "facebook"):
            if states.get(step) not in ("posted", "running", target):
                _set_step(c, item_id, step, target, note=why)
    return public, why


def delete_item(c, item_id: str, *, media: bool = True) -> dict:
    """Remove an item for good: its rows everywhere and, with media=True, its files under
    items/<id>/ in the media bucket (and the CDN's cached copies)."""
    with tx(c):
        for t in ("items", "items_fts", "embeddings", "layout"):
            c.execute(f"DELETE FROM {t} WHERE id=?", (item_id,))
        for t in ("steps", "item_categories", "item_tags", "item_highlights", "transitions", "costs"):
            c.execute(f"DELETE FROM {t} WHERE item_id=?", (item_id,))
    removed = 0
    if media and re.fullmatch(r"[A-Za-z0-9_\-]+", item_id):
        import boto3
        s3 = boto3.client("s3", region_name=config.REGION)
        prefix = f"items/{item_id}/"
        for page in s3.get_paginator("list_object_versions").paginate(Bucket=config.MEDIA_BUCKET, Prefix=prefix):
            objs = [{"Key": v["Key"], "VersionId": v["VersionId"]}
                    for v in (page.get("Versions") or []) + (page.get("DeleteMarkers") or [])]
            for k in range(0, len(objs), 1000):
                s3.delete_objects(Bucket=config.MEDIA_BUCKET, Delete={"Objects": objs[k:k + 1000], "Quiet": True})
            removed += len(objs)
        dist = config.env("EE_MEDIA_DISTRIBUTION_ID")
        if removed and dist:
            try:
                boto3.client("cloudfront").create_invalidation(DistributionId=dist, InvalidationBatch={
                    "Paths": {"Quantity": 1, "Items": [f"/{prefix}*"]}, "CallerReference": f"del-{item_id}-{now()}"})
            except Exception as e:
                event("delete.invalidation_failed", logging.WARNING, item=item_id, error=str(e))
    event("item.deleted", item=item_id, media_objects=removed)
    return {"id": item_id, "media_objects_removed": removed}


# ------------------------------------------------------------------ ingest
def upsert_items(c: sqlite3.Connection, items: list[dict]) -> dict:
    counts = {"inserted": 0, "updated": 0, "changed": 0, "unchanged": 0}
    for raw in items:
        if not isinstance(raw, dict) or not raw.get("id") or not raw.get("kind") or not raw.get("taken_at"):
            raise ValueError("every item needs id, kind and taken_at")
        item = {k: v for k, v in raw.items() if k not in BACKEND_FIELDS and k not in ("updated_at", "priority")}
        prio = 1 if raw.get("priority") == "new" or (raw.get("priority") is None and _recent(raw.get("taken_at"))) else 0
        _map_media(item, to_key)
        h = content_hash(item)
        ts = now()
        with tx(c):
            old = c.execute("SELECT content_hash, data FROM items WHERE id = ?", (item["id"],)).fetchone()
            if old is None:
                c.execute("""INSERT INTO items(id, kind, taken_at, data, content_hash, collected_at, updated_at, priority)
                             VALUES (?,?,?,?,?,?,?,?)""",
                          (item["id"], item["kind"], item["taken_at"], j(item), h, item.get("collected_at") or ts, ts, prio))
                for step in STEPS:
                    _set_step(c, item["id"], step, "pending", note="downloaded")
                counts["inserted"] += 1
            else:
                same = old["data"] == j(item)
                c.execute("UPDATE items SET kind=?, taken_at=?, data=?, content_hash=?, updated_at=?, "
                          "priority=MAX(priority, ?) WHERE id=?",
                          (item["kind"], item["taken_at"], j(item), h, ts, prio, item["id"]))
                if old["content_hash"] != h:
                    # Caption or media changed: the old categories no longer describe it.
                    c.execute("""UPDATE items SET categories='[]', summary=NULL, description=NULL, analysis=NULL,
                                 published_at=NULL, covers='{}', thumbs=NULL WHERE id=?""", (item["id"],))
                    c.execute("DELETE FROM item_categories WHERE item_id=?", (item["id"],))
                    c.execute("DELETE FROM item_tags WHERE item_id=?", (item["id"],))
                    _set_step(c, item["id"], "analyze", "pending", note="caption or media changed")
                    _set_step(c, item["id"], "site", "pending", note="caption or media changed")
                    counts["changed"] += 1
                elif same:
                    counts["unchanged"] += 1
                else:
                    counts["updated"] += 1
            c.execute("DELETE FROM item_highlights WHERE item_id=?", (item["id"],))
            for hl in item.get("highlights") or []:
                if isinstance(hl, dict) and hl.get("id"):
                    c.execute("INSERT OR IGNORE INTO item_highlights VALUES (?,?)", (item["id"], hl["id"]))
            index_item(c, item["id"])
    event("ingest.items", **counts)
    return counts


def upsert_highlights(c: sqlite3.Connection, highlights: list[dict]) -> int:
    ts = now()
    with tx(c):
        for pos, hl in enumerate(highlights):
            if not hl.get("id"):
                raise ValueError("every highlight needs an id")
            data = {k: v for k, v in hl.items() if k not in ("id", "title", "cover", "item_ids", "updated_at")}
            c.execute("""INSERT INTO highlights(id, title, cover, item_ids, position, data, updated_at)
                         VALUES (?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET title=excluded.title,
                         cover=excluded.cover, item_ids=excluded.item_ids, position=excluded.position,
                         data=excluded.data, updated_at=excluded.updated_at""",
                      (hl["id"], hl.get("title"), to_key(hl.get("cover")), j(hl.get("item_ids") or []), pos,
                       j(data), ts))
            for item_id in hl.get("item_ids") or []:
                c.execute("INSERT OR IGNORE INTO item_highlights VALUES (?,?)", (item_id, hl["id"]))
    event("ingest.highlights", count=len(highlights))
    return len(highlights)


def put_profile(c: sqlite3.Connection, profile: dict) -> None:
    p = dict(profile)
    p["avatar"] = to_key(p.get("avatar"))
    ts = now()
    c.execute("INSERT INTO profile(id, data, updated_at) VALUES (1, ?, ?) "
              "ON CONFLICT(id) DO UPDATE SET data=excluded.data, updated_at=excluded.updated_at", (j(p), ts))
    event("ingest.profile", username=p.get("username"))


def add_run(c: sqlite3.Connection, run: dict) -> int:
    cur = c.execute("INSERT INTO runs(started_at, finished_at, ok, counts, log_url, received_at) VALUES (?,?,?,?,?,?)",
                    (run.get("started_at"), run.get("finished_at"), 1 if run.get("ok") else 0,
                     j(run.get("counts") or {}), run.get("log_url"), now()))
    return cur.lastrowid


# ------------------------------------------------------------------ search
def _flatten(v, out):
    if isinstance(v, str):
        out.append(v)
    elif isinstance(v, dict):
        for x in v.values():
            _flatten(x, out)
    elif isinstance(v, list):
        for x in v:
            _flatten(x, out)


def index_item(c: sqlite3.Connection, item_id: str) -> None:
    row = c.execute("SELECT * FROM items WHERE id=?", (item_id,)).fetchone()
    if not row:
        return
    d = json.loads(row["data"])
    parts = [d.get("caption") or "", row["summary"] or "", row["description"] or "",
             " ".join(d.get("hashtags") or []), " ".join(d.get("mentions") or [])]
    loc = d.get("location") or {}
    parts.append(loc.get("name") or "" if isinstance(loc, dict) else "")
    parts += [h.get("title") or "" for h in d.get("highlights") or [] if isinstance(h, dict)]
    for r in c.execute("SELECT h.title FROM item_highlights ih JOIN highlights h ON h.id=ih.highlight_id "
                       "WHERE ih.item_id=?", (item_id,)):
        parts.append(r["title"] or "")
    rep = d.get("repost_of") or {}
    if isinstance(rep, dict):
        parts += [rep.get("author") or "", rep.get("author_name") or "", rep.get("caption") or ""]
    parts += [t.get("username", "") for t in d.get("tagged_users") or [] if isinstance(t, dict)]
    parts += json.loads(row["categories"] or "[]")
    if row["analysis"]:
        a = json.loads(row["analysis"])
        a.pop("model", None)
        a.pop("analyzed_at", None)
        _flatten(a, parts)
    c.execute("DELETE FROM items_fts WHERE id=?", (item_id,))
    c.execute("INSERT INTO items_fts(id, body) VALUES (?, ?)", (item_id, "\n".join(p for p in parts if p)))


def fts_query(q: str) -> str:
    """User text -> a safe FTS5 query: every word must match, as a prefix."""
    words = [w for w in "".join(ch if ch.isalnum() else " " for ch in q).split() if w]
    return " ".join(f'"{w}"*' for w in words[:12])


# ------------------------------------------------------------------ rendering
def render_item(c: sqlite3.Connection, row: sqlite3.Row) -> dict:
    d = json.loads(row["data"])
    _map_media(d, to_url)
    d["categories"] = json.loads(row["categories"] or "[]")
    d["summary"] = row["summary"]
    d["description"] = row["description"]
    d["importance"] = row["importance"] if "importance" in row.keys() else None
    if "detection" in row.keys():
        d["detection"] = json.loads(row["detection"]) if row["detection"] else None
    if "curation" in row.keys():
        d["placement"] = d["curation"] = row["curation"]
        d["placement_reason"] = d["curation_reason"] = row["curation_reason"]
    d["analysis"] = json.loads(row["analysis"]) if row["analysis"] else None
    d["published_at"] = row["published_at"]
    covers = json.loads(row["covers"] or "{}")
    thumbs = json.loads(row["thumbs"] or "{}") if "thumbs" in row.keys() else {}
    for prefix, media in (("", d.get("media") or []), ("r", (d.get("repost_of") or {}).get("media") or [])):
        for n, m in enumerate(media):
            if not m.get("thumbnail") and thumbs.get(f"{prefix}{n}"):
                m["thumbnail"] = to_url(MEDIA_PREFIX + thumbs[f"{prefix}{n}"])
            if m.get("type") == "video":
                cv = covers.get(f"{prefix}{n}") or {}
                m["cover"] = to_url(MEDIA_PREFIX + cv["cover"]) if cv.get("cover") else None
                m["cover_at"] = cv.get("cover_at")
    d["updated_at"] = row["updated_at"]
    d.setdefault("collected_at", row["collected_at"])
    hl_ids = {h.get("id") for h in d.get("highlights") or [] if isinstance(h, dict)}
    extra = c.execute("SELECT h.id, h.title FROM item_highlights ih JOIN highlights h ON h.id=ih.highlight_id "
                      "WHERE ih.item_id=? ORDER BY h.position", (row["id"],)).fetchall()
    for r in extra:
        if r["id"] not in hl_ids:
            d.setdefault("highlights", []).append({"id": r["id"], "title": r["title"]})
    for h in d.get("highlights") or []:
        if isinstance(h, dict) and not h.get("title"):
            t = next((r["title"] for r in extra if r["id"] == h.get("id")), None)
            if t:
                h["title"] = t
    return d


def render_highlight(row: sqlite3.Row) -> dict:
    d = json.loads(row["data"] or "{}")
    d.update({"id": row["id"], "title": row["title"], "cover": to_url(row["cover"]),
              "item_ids": json.loads(row["item_ids"]), "updated_at": row["updated_at"]})
    return d


def encode_cursor(taken_at: str, item_id: str) -> str:
    return base64.urlsafe_b64encode(f"{taken_at}|{item_id}".encode()).decode().rstrip("=")


def decode_cursor(s: str):
    """A cursor from `next`, or a plain ISO time."""
    try:
        raw = base64.urlsafe_b64decode(s + "=" * (-len(s) % 4)).decode()
        if "|" in raw:
            t, i = raw.split("|", 1)
            return t, i
    except Exception:
        pass
    return s, None


# ------------------------------------------------------------------ pipeline steps
def _set_step(c, item_id, step, state, *, note=None, error=None, remote_id=None, remote_url=None,
              detail=None, attempts=None, next_at=None):
    old = c.execute("SELECT state, attempts FROM steps WHERE item_id=? AND step=?", (item_id, step)).fetchone()
    ts = now()
    if old is None:
        c.execute("""INSERT INTO steps(item_id, step, state, attempts, next_at, last_error, remote_id, remote_url,
                     detail, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?)""",
                  (item_id, step, state, attempts or 0, next_at, error, remote_id, remote_url,
                   j(detail) if detail is not None else None, ts))
    else:
        if state == "pending" and old["state"] in ("posted",) and step in ("x", "facebook"):
            return  # never post twice, whatever changed
        c.execute("""UPDATE steps SET state=?, attempts=COALESCE(?, attempts), next_at=?, last_error=?,
                     remote_id=COALESCE(?, remote_id), remote_url=COALESCE(?, remote_url),
                     detail=COALESCE(?, detail), updated_at=? WHERE item_id=? AND step=?""",
                  (state, 0 if state == "pending" else attempts, next_at, error, remote_id, remote_url,
                   j(detail) if detail is not None else None, ts, item_id, step))
    from_state = old["state"] if old else None
    if from_state != state or error:
        c.execute("INSERT INTO transitions(at, item_id, step, from_state, to_state, note) VALUES (?,?,?,?,?,?)",
                  (ts, item_id, step, from_state, state, (error or note or "")[:2000]))
        event("pipeline.transition", logging.WARNING if state == "failed" else logging.INFO,
              item=item_id, step=step, from_state=from_state, to_state=state, note=note, error=error,
              remote=remote_url or remote_id)


def set_step(c, item_id, step, state, **kw):
    with tx(c):
        _set_step(c, item_id, step, state, **kw)


def fail_step(c, item_id, step, error: str, *, permanent=False):
    """Failed; retried with exponential backoff (2 min .. ~4 h) up to MAX_ATTEMPTS."""
    with tx(c):
        row = c.execute("SELECT attempts FROM steps WHERE item_id=? AND step=?", (item_id, step)).fetchone()
        attempts = (row["attempts"] if row else 0) + 1
        delay = min(2 * 2 ** (attempts - 1), 240)
        next_at = None if permanent or attempts >= MAX_ATTEMPTS else \
            (datetime.now(timezone.utc) + timedelta(minutes=delay)).strftime("%Y-%m-%dT%H:%M:%SZ")
        _set_step(c, item_id, step, "failed", error=error[:4000], attempts=attempts, next_at=next_at)


PRIORITY_ORDER = ("i.priority DESC, CASE WHEN i.priority = 1 THEN i.taken_at END DESC, "
                  "i.taken_at ASC, i.id ASC")


def _recent(taken_at, days: int = 3) -> bool:
    try:
        return (datetime.now(timezone.utc) - datetime.strptime(taken_at[:19], "%Y-%m-%dT%H:%M:%S")
                .replace(tzinfo=timezone.utc)).days < days
    except (TypeError, ValueError):
        return False


def claim_next(c, step: str, *, requires_analysis: bool = False, newest_first: bool = False):
    """The next item whose step is due, marked running: new items first (newest first), then the
    backlog (oldest first). Each call is a step boundary, so a newly arrived item goes next."""
    ts = now()
    need = "AND i.published_at IS NOT NULL" if requires_analysis else ""
    with tx(c):
        row = c.execute(f"""SELECT s.item_id FROM steps s JOIN items i ON i.id = s.item_id
            WHERE s.step=? AND (s.state='pending' OR (s.state='failed' AND s.next_at IS NOT NULL AND s.next_at <= ?))
            {need} ORDER BY {PRIORITY_ORDER} LIMIT 1""", (step, ts)).fetchone()
        if not row:
            return None
        _set_step(c, row["item_id"], step, "running", note="started")
        return row["item_id"]


def recover_running(c) -> int:
    """After a restart, a step left 'running' was interrupted: put it back in the queue."""
    with tx(c):
        rows = c.execute("SELECT item_id, step FROM steps WHERE state='running'").fetchall()
        for r in rows:
            # A post interrupted mid-flight may have gone out; the poster checks before re-posting.
            _set_step(c, r["item_id"], r["step"], "pending", note="interrupted, requeued")
    return len(rows)


def pipeline_status(c, failures: int = 20) -> dict:
    counts: dict = {s: {} for s in STEPS}
    for r in c.execute("SELECT step, state, COUNT(*) n FROM steps GROUP BY step, state"):
        counts.setdefault(r["step"], {})[r["state"]] = r["n"]
    total = c.execute("SELECT COUNT(*) n FROM items").fetchone()["n"]
    fails = [dict(r) for r in c.execute(
        """SELECT item_id, step, attempts, next_at, last_error, updated_at FROM steps WHERE state='failed'
           ORDER BY updated_at DESC LIMIT ?""", (failures,))]
    last_run = c.execute("SELECT * FROM runs ORDER BY id DESC LIMIT 1").fetchone()
    spend = c.execute("""SELECT COUNT(*) n, COALESCE(SUM(coins),0) coins, COALESCE(SUM(usd),0) usd FROM costs
                         WHERE at >= ?""", ((datetime.now(timezone.utc) - timedelta(days=1)).strftime("%Y-%m-%dT%H:%M:%SZ"),)).fetchone()
    from .db import setting
    return {
        "items": total,
        "steps": counts,
        "failures": fails,
        "last_collector_run": dict(last_run) if last_run else None,
        "spend_24h": dict(spend),
        "settings": {r["key"]: r["value"] for r in c.execute("SELECT key, value FROM settings ORDER BY key")},
    }


# ------------------------------------------------------------------ activity (GET /v1/status)
def job_start(c, job_id: str, component: str, what: str, item_id: str | None = None, progress: str = ""):
    ts = now()
    c.execute("""INSERT INTO jobs(id, component, what, item_id, progress, started_at, updated_at) VALUES (?,?,?,?,?,?,?)
                 ON CONFLICT(id) DO UPDATE SET component=excluded.component, what=excluded.what,
                 item_id=excluded.item_id, progress=excluded.progress, started_at=excluded.started_at,
                 updated_at=excluded.updated_at""", (job_id, component, what, item_id, progress, ts, ts))


def job_progress(c, job_id: str, progress: str):
    c.execute("UPDATE jobs SET progress=?, updated_at=? WHERE id=?", (progress, now(), job_id))


def job_end(c, job_id: str):
    c.execute("DELETE FROM jobs WHERE id=?", (job_id,))


def record(c, component: str, kind: str, text: str, item_id: str | None = None, ok: bool = True):
    c.execute("INSERT INTO events(at, component, kind, text, item_id, ok) VALUES (?,?,?,?,?,?)",
              (now(), component, kind, text[:500], item_id, 1 if ok else 0))
    c.execute("DELETE FROM events WHERE id < (SELECT MAX(id) - 5000 FROM events)")
