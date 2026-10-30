"""Highlight names written out in full: the owner often shortens them on Instagram ("плнт" for
"планета", "прзд" for "президент"). Claude writes each name out once (and again when it is renamed);
cards show the full name and the monitor listens for it. A name that is not shortened stays as it is.
"""
from __future__ import annotations

import json

from . import aicoin
from .analysis import usd_for
from .db import now, tx
from .logs import event

BATCH = 100

SCHEMA = {"type": "object", "additionalProperties": False, "required": ["names"],
          "properties": {"names": {"type": "array", "items": {
              "type": "object", "additionalProperties": False, "required": ["n", "full"],
              "properties": {"n": {"type": "integer"}, "full": {"type": "string"}}}}}}

PROMPT = """These are names of Instagram highlights, mostly Ukrainian or Russian. The owner sometimes
shortens a word - drops its vowels ("плнт" for "планета"), keeps only its start ("през" for
"президент"), or uses a common abbreviation. Write each name out in full, in the same language and
word order, keeping numbers, emoji and everything that is not shortened exactly as it is. When a name
is not shortened, or you cannot tell what it stands for, return it unchanged. Never translate or
explain.

Names, one per line as number | name:
{names}"""


def pending(c) -> list:
    return c.execute("SELECT id, title FROM highlights WHERE title IS NOT NULL AND TRIM(title) != '' "
                     "AND title_full_of IS NOT title ORDER BY position LIMIT ?", (BATCH,)).fetchall()


def run(c) -> int:
    """Write out the names not done yet (new or renamed). Returns how many were done."""
    rows = pending(c)
    if not rows:
        return 0
    prompt = PROMPT.replace("{names}", "\n".join(f"{n} | {r['title']}" for n, r in enumerate(rows)))
    body = {"model": aicoin.model_for(c, "expand"), "max_tokens": 4000, "output_config": {"format": {"type": "json_schema", "schema": SCHEMA}},
            "messages": [{"role": "user", "content": prompt}]}
    resp, coins = aicoin.claude(body, timeout=120, purpose="expand")
    usage = resp.get("usage") or {}
    model = resp.get("model") or ""
    c.execute("INSERT INTO costs(at, purpose, model, input_tokens, output_tokens, coins, usd, ok) VALUES (?,?,?,?,?,?,?,1)",
              (now(), "expand", model, usage.get("input_tokens"), usage.get("output_tokens"), coins, usd_for(model, usage)))
    out = json.loads("".join(b.get("text", "") for b in resp.get("content") or [] if b.get("type") == "text"))
    full = {x["n"]: " ".join((x.get("full") or "").split())[:120] for x in out.get("names") or [] if isinstance(x.get("n"), int)}
    changed = 0
    with tx(c):
        for n, r in enumerate(rows):
            f = full.get(n) or r["title"]
            f = None if f == r["title"].strip() else f
            changed += f is not None
            c.execute("UPDATE highlights SET title_full=?, title_full_of=? WHERE id=?", (f, r["title"], r["id"]))
    event("highlights.expanded", names=len(rows), expanded=changed, coins=coins)
    return len(rows)
