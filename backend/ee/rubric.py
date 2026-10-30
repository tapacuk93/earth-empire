"""The importance rubric: plain text that tells Claude how to score `importance` (0-1). Versioned in
the `rubrics` table; the owner edits it in Settings, and a daily job lets Claude refine it from
what it has seen (CONTRACT.md "Home layout"). A new applied version re-scores items in the background."""
from __future__ import annotations

import json
import logging

FIRST = """Importance (0 to 1) is how much this item matters in the owner's life and work, judged from its
content alone.
- 0.9-1.0: a milestone - a major life event, a big move, a launch, an award, a historic moment the
  owner took part in.
- 0.7-0.8: notable - a trip, an event, an achievement, a creation, a strong idea or statement, a
  meeting with someone significant, a moment the owner clearly cared to keep.
- 0.4-0.6: an ordinary but meaningful moment - daily life, work in progress, a shared opinion, news
  the owner engages with.
- 0.1-0.3: trivial - routine, filler, a passing joke.
Never lower the score for the kind of item (story, reel, post), for being a repost of someone else's
video, or for likes and views. Raise it when the owner comes back to the same subject, saves it to a
highlight, or adds their own words."""


def current(c) -> dict:
    r = c.execute("SELECT * FROM rubrics WHERE applied=1 ORDER BY version DESC LIMIT 1").fetchone()
    return dict(r) if r else {"version": 1, "text": FIRST, "reason": "the first rubric", "by": "backend"}


def history(c) -> list[dict]:
    return [dict(r) for r in c.execute("SELECT * FROM rubrics ORDER BY version DESC")]


def add(c, text: str, reason: str, by: str, applied: bool = True) -> int:
    from .db import now
    v = (c.execute("SELECT MAX(version) v FROM rubrics").fetchone()["v"] or 0) + 1
    c.execute("INSERT INTO rubrics(version, text, reason, by, applied, created_at) VALUES (?,?,?,?,?,?)",
              (v, text.strip(), reason.strip()[:1000], by, 1 if applied else 0, now()))
    return v


REVIEW_SCHEMA = {"type": "object", "additionalProperties": False,
                 "required": ["refinement", "text", "reason"],
                 "properties": {"refinement": {"type": "boolean"}, "text": {"type": "string"},
                                "reason": {"type": "string"}}}

REVIEW = """You maintain the rubric Claude uses to score the importance (0-1) of items on Earth Empire, the
site that publishes the owner's Instagram. Below are the current rubric and a sample of public items
with the scores they got. Propose an improved rubric, if the content shows a way to judge it better
(clearer bands, the subjects that matter most to this owner, cases the rubric misses).

It counts as a refinement only if it keeps the rubric's intent and its rules (never lower the
score for the kind of item, for a repost or for likes), and makes the scoring clearer or more
accurate. If nothing should change, return the current text with refinement false. Keep it under 250
words, in plain text.

Current rubric (version {version}):
{text}

Items (score | date | summary):
{items}"""


def review(c) -> dict | None:
    """Claude's daily look at the rubric. Applies a refinement as a new version; records it either way."""
    from . import aicoin, store
    from .analysis import usd_for
    from .db import now
    from .logs import event
    cur = current(c)
    rows = c.execute("""SELECT importance, taken_at, summary FROM items WHERE published_at IS NOT NULL
                        AND importance IS NOT NULL ORDER BY RANDOM() LIMIT 60""").fetchall()
    if len(rows) < 10:
        return None
    items = "\n".join(f"{r['importance']:.2f} | {r['taken_at'][:10]} | {(r['summary'] or '')[:150]}" for r in rows)
    body = {"max_tokens": 4000, "output_config": {"effort": "medium", "format": {"type": "json_schema", "schema": REVIEW_SCHEMA}},
            "messages": [{"role": "user", "content": REVIEW.format(version=cur["version"], text=cur["text"], items=items)}]}
    resp, coins = aicoin.claude(body, timeout=300, purpose="rubric")
    usage = resp.get("usage") or {}
    c.execute("INSERT INTO costs(at, purpose, model, input_tokens, output_tokens, coins, usd, ok) VALUES (?,?,?,?,?,?,?,1)",
              (now(), "rubric", resp.get("model"), usage.get("input_tokens"), usage.get("output_tokens"), coins,
               usd_for(resp.get("model") or "", usage)))
    out = json.loads("".join(b.get("text", "") for b in resp.get("content") or [] if b.get("type") == "text"))
    text = (out.get("text") or "").strip()
    changed = text and text != cur["text"].strip()
    applied = bool(out.get("refinement")) and changed and len(text) < 4000
    v = None
    if changed:
        v = add(c, text, out.get("reason") or "", "claude", applied)
        store.record(c, "analyzer", "rubric", f"importance rubric v{v} {'applied' if applied else 'proposed, not applied'}: "
                     f"{(out.get('reason') or '')[:200]}")
    event("rubric.review", proposed=v, applied=applied, coins=coins)
    return {"version": v, "applied": applied, "reason": out.get("reason")}
