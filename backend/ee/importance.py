"""Backfill `importance` (and categories that came out empty) for items analyzed before
importance existed: one short, text-only Claude call per item, from its stored analysis.
New items get importance in their full analysis (analysis.py)."""
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

PROMPT = """This is the stored analysis of one item from the owner's Instagram archive. Judge:
- importance, 0 to 1: how significant the moment or content is in the owner's life and in this
  archive. About 0.1 something trivial, 0.3-0.5 an everyday moment, 0.7 a notable trip, event,
  achievement, creation or idea, 0.9-1 a milestone (a wedding, a birth, a big move, a major launch).
  Judge the content only: a story, a reel and a post count the same, and a repost of someone else's
  video counts as much as the owner's own when its content matters as much. Never lower it for the
  kind of item, for being a repost, or for the number of likes.
- categories: 1 to 4 slugs. Reuse the existing ones whenever one fits; add one in new_categories
  (at most 2, broad topics, lowercase-ascii-with-hyphens) only when nothing fits.

Existing categories (JSON): {cats}

The item (JSON): {item}"""


def backfill_one(c, item_id: str) -> dict:
    row = c.execute("SELECT * FROM items WHERE id=?", (item_id,)).fetchone()
    d = json.loads(row["data"])
    a = json.loads(row["analysis"] or "{}")
    item = {"taken_at": row["taken_at"], "caption": (d.get("caption") or "")[:1500],
            "summary": row["summary"], "description": row["description"], "categories": json.loads(row["categories"]),
            "what": a.get("what"), "where": a.get("where"), "when": a.get("when"), "context": a.get("context"),
            "keywords": a.get("keywords"), "highlights": [h.get("title") for h in d.get("highlights") or []
                                                         if isinstance(h, dict)]}
    cats = [dict(r) for r in c.execute("SELECT slug, name, description FROM categories ORDER BY slug")]
    body = {"max_tokens": 2000, "output_config": {"effort": "low", "format": {"type": "json_schema", "schema": SCHEMA}},
            "messages": [{"role": "user", "content": PROMPT.format(cats=j(cats), item=j(item))}]}
    resp, coins = aicoin.claude(body, timeout=120)
    usage = resp.get("usage") or {}
    model = resp.get("model") or ""
    c.execute("INSERT INTO costs(at, item_id, purpose, model, input_tokens, output_tokens, coins, usd, ok) "
              "VALUES (?,?,?,?,?,?,?,?,1)", (now(), item_id, "importance", model, usage.get("input_tokens"),
                                            usage.get("output_tokens"), coins, usd_for(model, usage)))
    text = "".join(b.get("text", "") for b in resp.get("content") or [] if b.get("type") == "text")
    out = json.loads(text)
    imp = min(1.0, max(0.0, float(out.get("importance", 0.5))))
    with tx(c):
        existing = {r["slug"] for r in c.execute("SELECT slug FROM categories")}
        added = []
        for nc in (out.get("new_categories") or [])[:MAX_NEW_CATEGORIES]:
            s = slugify(nc.get("slug") or nc.get("name") or "")
            if s and s not in existing:
                c.execute("INSERT INTO categories(slug, name, description, created_at, created_by_item) VALUES (?,?,?,?,?)",
                          (s, (nc.get("name") or s)[:60], (nc.get("description") or "")[:300], now(), item_id))
                existing.add(s)
                added.append(s)
        old = json.loads(row["categories"])
        new = [s for s in dict.fromkeys(slugify(x) for x in out.get("categories") or []) if s in existing]
        cats_final = old if old else new   # keep categories an item already has; fill empty ones
        c.execute("UPDATE items SET importance=?, categories=? WHERE id=?", (imp, j(cats_final), item_id))
        if cats_final != old:
            c.execute("DELETE FROM item_categories WHERE item_id=?", (item_id,))
            for s in cats_final:
                c.execute("INSERT INTO item_categories VALUES (?,?)", (item_id, s))
            for s in cats_final:
                c.execute("INSERT OR IGNORE INTO item_tags VALUES (?,?,?)", (item_id, s, "category"))
            store.index_item(c, item_id)
    res = {"item": item_id, "importance": imp, "categories": cats_final, "added": added, "coins": coins}
    event("importance.done", **res)
    return res


def pending(c, limit: int = 1000) -> list[str]:
    return [r["id"] for r in c.execute("SELECT id FROM items WHERE analysis IS NOT NULL AND importance IS NULL "
                                       "ORDER BY taken_at LIMIT ?", (limit,))]


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
