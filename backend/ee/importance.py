"""Importance scoring in the background: items without a score, scored by an older rubric version, or
scored before scoring used the full inputs. One multimodal Claude call per item (images, frames,
cached transcripts, metadata, the earlier description), with the current rubric. Also fills
categories that came out empty."""
from __future__ import annotations

import json
import logging

from . import aicoin, store
from .analysis import MAX_NEW_CATEGORIES, slugify, usd_for
from .db import j, now, tx
from .logs import event

SCHEMA = {
    "type": "object", "additionalProperties": False,
    "properties": {
        "importance": {"type": "number"},
        "categories": {"type": "array", "items": {"type": "string"}},
        "new_categories": {"type": "array", "items": {"type": "object", "additionalProperties": False, "properties": {
            "slug": {"type": "string"}, "name": {"type": "string"}, "description": {"type": "string"}},
            "required": ["slug", "name", "description"]}},
    },
    "required": ["importance", "categories", "new_categories"],
}

PROMPT = """This is the stored analysis of one item from the owner's Instagram, published by Earth Empire. Judge:
- importance, 0 to 1, by this rubric (version {rv}):
{rubric}
- categories: 1 to 4 slugs. Reuse the existing ones whenever one fits; add one in new_categories
  (at most 2, broad topics, lowercase-ascii-with-hyphens) only when nothing fits.

Existing categories (JSON): {cats}

The item (JSON): {item}"""


SCORE_SYSTEM = """You score the importance (0 to 1) of one item from the owner's Instagram, published by
Earth Empire, by the importance rubric below. You see the item's images, frames sampled across its
videos (with their times), the transcripts of its speech (for a repost, the original's audio too),
its on-screen text and metadata, and the description written earlier. Judge what the item actually
shows and says. Also give 1 to 4 category slugs when the item has none yet (reuse existing ones;
add at most 2 in new_categories only when nothing fits).

Importance rubric (version {rv}):
{rubric}"""

SCORE_SCHEMA = {
    "type": "object", "additionalProperties": False,
    "properties": {
        "importance": {"type": "number"}, "reason": {"type": "string"},
        "categories": {"type": "array", "items": {"type": "string"}},
        "new_categories": SCHEMA["properties"]["new_categories"],
    },
    "required": ["importance", "reason", "categories", "new_categories"],
}


def backfill_one(c, item_id: str, job: str | None = None) -> dict:
    """Score importance from the full inputs (multimodal), with the current rubric."""
    import shutil
    import tempfile
    from pathlib import Path
    from . import analysis, rubric
    row = c.execute("SELECT * FROM items WHERE id=?", (item_id,)).fetchone()
    a = json.loads(row["analysis"] or "{}")
    rub = rubric.current(c)
    work = Path(tempfile.mkdtemp(prefix="ee-score-"))
    try:
        body, info = analysis.build_request(c, item_id, work, job)
        content = body["messages"][0]["content"][:-1]   # without "Analyze this item now."
        content.append({"type": "text", "text": "Written earlier about this item (JSON):\n" + j({
            "summary": row["summary"], "description": row["description"], "what": a.get("what"),
            "on_screen_text": a.get("on_screen_text"), "context": a.get("context"),
            "categories": json.loads(row["categories"] or "[]")})})
        content.append({"type": "text", "text": "Score its importance now."})
        if job:
            store.job_progress(c, job, f"asking Claude ({info['images']} images, {info['frames']} frames)")
        req = {"model": aicoin.model_for(c, "importance"), "max_tokens": 3000, "system": SCORE_SYSTEM.format(rv=rub["version"], rubric=rub["text"]),
               "output_config": {"effort": "low", "format": {"type": "json_schema", "schema": SCORE_SCHEMA}},
               "messages": [{"role": "user", "content": content}]}
        resp, coins = aicoin.claude(req, timeout=300)
    finally:
        shutil.rmtree(work, ignore_errors=True)
    usage = resp.get("usage") or {}
    model = resp.get("model") or ""
    c.execute("INSERT INTO costs(at, item_id, purpose, model, input_tokens, output_tokens, coins, usd, ok) "
              "VALUES (?,?,?,?,?,?,?,?,1)", (now(), item_id, "importance", model, usage.get("input_tokens"),
                                            usage.get("output_tokens"), coins, usd_for(model, usage)))
    out = json.loads("".join(b.get("text", "") for b in resp.get("content") or [] if b.get("type") == "text"))
    imp = min(1.0, max(0.0, float(out.get("importance", 0.5))))
    with tx(c):
        existing = {r["slug"] for r in c.execute("SELECT slug FROM categories")}
        added = []
        old = json.loads(row["categories"] or "[]")
        if not old:
            for nc in (out.get("new_categories") or [])[:MAX_NEW_CATEGORIES]:
                s = slugify(nc.get("slug") or nc.get("name") or "")
                if s and s not in existing:
                    c.execute("INSERT INTO categories(slug, name, description, created_at, created_by_item) VALUES (?,?,?,?,?)",
                              (s, (nc.get("name") or s)[:60], (nc.get("description") or "")[:300], now(), item_id))
                    existing.add(s)
                    added.append(s)
        new = [s for s in dict.fromkeys(slugify(x) for x in out.get("categories") or []) if s in existing]
        cats_final = old if old else new
        a["importance_reason"] = (out.get("reason") or "")[:500]
        c.execute("UPDATE items SET importance=?, importance_version=?, importance_method=2, categories=?, analysis=? "
                  "WHERE id=?", (imp, rub["version"], j(cats_final), j(a), item_id))
        if cats_final != old:
            c.execute("DELETE FROM item_categories WHERE item_id=?", (item_id,))
            for s in cats_final:
                c.execute("INSERT INTO item_categories VALUES (?,?)", (item_id, s))
                c.execute("INSERT OR IGNORE INTO item_tags VALUES (?,?,?)", (item_id, s, "category"))
            store.index_item(c, item_id)
    res = {"item": item_id, "importance": imp, "rubric": rub["version"], "categories": cats_final, "added": added,
           "coins": coins + info.get("coins", 0), "reason": (out.get("reason") or "")[:160]}
    event("importance.done", **res)
    return res


def pending(c, limit: int = 1000) -> list[str]:
    """Analyzed items without a score, or scored by an older rubric (re-scored in the background)."""
    from . import rubric
    v = rubric.current(c)["version"]
    return [r["id"] for r in c.execute(
        """SELECT id FROM items WHERE analysis IS NOT NULL AND (importance IS NULL OR importance_version IS NULL
           OR importance_version < ? OR importance_method IS NULL OR importance_method < 2)
           ORDER BY importance IS NOT NULL, published_at IS NULL, priority DESC, taken_at DESC LIMIT ?""",
        (v, limit))]


def run(c, limit: int = 1000) -> list[dict]:
    out = []
    for i in pending(c, limit):
        try:
            out.append(backfill_one(c, i))
        except aicoin.OutOfCoins:
            raise
        except Exception as e:
            event("importance.failed", logging.WARNING, item=i, error=repr(e)[:300])
    return out
