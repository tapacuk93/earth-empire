"""Facets: the groupings the site browses by (places, themes, people, ...), defined by Claude from
the public content, never fixed and never from visitors (CONTRACT.md "Facets").

A run gives Claude a compact summary of every public item (date, summary, keywords, place,
categories) and the current facets. Claude returns the facets worth browsing by now, the
categories within each, and which items belong where. It keeps existing ids and names unless they
no longer fit, so the site does not reshuffle. Items beyond what one call can hold are assigned by
embedding similarity to the categories Claude filled.

Runs: when something changed, spaced so that `facets.daily_cap` runs (the cost guard) cover the
whole day, through the server's aicoin wallet. Between runs every newly published video (and found
clip) joins, per facet, the category its members are most like, so new videos show in their
category at once.

Improving: each run Claude writes notes to itself (what worked, what to change, what to watch), and
the next run reads them along with how the last categories fared: their sizes, how many videos
joined each by similarity since, and how many fit nowhere.
"""
from __future__ import annotations

import json
import logging
import re

from . import aicoin
from .analysis import slugify, usd_for
from .db import j, now, set_setting, setting, tx
from .logs import event

MAX_ITEMS_IN_PROMPT = 400

SCHEMA = {
    "type": "object", "additionalProperties": False, "required": ["facets", "notes"],
    "properties": {"notes": {"type": "string"}, "facets": {"type": "array", "items": {
        "type": "object", "additionalProperties": False, "required": ["id", "name", "description", "categories"],
        "properties": {
            "id": {"type": "string"}, "name": {"type": "string"}, "description": {"type": "string"},
            "categories": {"type": "array", "items": {
                "type": "object", "additionalProperties": False, "required": ["id", "name", "description", "items"],
                "properties": {"id": {"type": "string"}, "name": {"type": "string"}, "description": {"type": "string"},
                               "items": {"type": "array", "items": {"type": "integer"}}}}}}}}},
}

PROMPT = """You organise the public content of Earth Empire, a site that publishes the owner's Instagram
(posts, reels, stories, highlights), for browsing. Define the facets a visitor would want to
browse by now - dimensions such as places, themes, people, projects, occasions, languages, moods or
whatever this content actually calls for - and within each facet its categories, then put every
item in the categories it belongs to (an item may be in several categories, and in none of a facet).

Rules:
- 3 to 7 facets; 3 to 15 categories per facet; every category holds at least 2 items, except where
  a single item is clearly its own important thing.
- Stability: these are the current facets and categories. Keep their ids and names unless they no
  longer fit the content; add, merge, split or drop only when the content calls for it.
- People: name a person only as the items' own summaries name them; never guess identities.
- ids are short lowercase-ascii-with-hyphens; names are short, in English, as shown on the site.
- Items are given as numbers; answer with those numbers.

- Improve every run. Your notes from earlier runs are below with how the categories fared since:
  act on them (merge what stays tiny, split what grew into a catch-all, rename what misleads, make a
  category for what keeps fitting nowhere). Then write `notes` for your next run: what you changed
  and why, what to watch, ideas still to try. Rewrite the whole notebook each time, keeping what still
  holds; at most 400 words.

Your notes from earlier runs: {notes}

How the current categories fared since the last run (JSON): {fared}

Current facets (JSON): {current}

Public items, one per line: number | date | summary | keywords | place | categories
{items}"""


def _line(n, r) -> str:
    a = json.loads(r["analysis"] or "{}")
    kw = ", ".join((a.get("keywords") or [])[:6])
    place = (a.get("where") or {}).get("place") or ""
    cats = ", ".join(json.loads(r["categories"] or "[]"))
    summ = re.sub(r"\s+", " ", (r["summary"] or ""))[:160]
    return f"{n} | {r['taken_at'][:10]} | {summ} | {kw} | {place[:40]} | {cats}"


def current(c) -> dict:
    raw = setting(c, "facets.current")
    return json.loads(raw) if raw else {"facets": [], "generated_at": None}


def gap_seconds(c) -> float:
    """The daily cap spread over the day: 12 runs -> at most one every 2 hours."""
    return max(600.0, 86400.0 / max(1, int(setting(c, "facets.daily_cap") or 12)))


def due(c) -> tuple[bool, str]:
    if setting(c, "analysis.enabled") != "1":
        return False, "analysis off"
    day = now()[:10]
    runs = c.execute("SELECT COUNT(*) n FROM costs WHERE purpose='facets' AND at >= ?", (day,)).fetchone()["n"]
    if runs >= int(setting(c, "facets.daily_cap") or 12):
        return False, "daily cap"
    last = setting(c, "facets.last_run") or ""
    public = c.execute("SELECT COUNT(*) n, MAX(published_at) t FROM items WHERE published_at IS NOT NULL").fetchone()
    if not public["n"]:
        return False, "nothing public"
    seen = int(setting(c, "facets.public_seen") or 0)
    new = c.execute("SELECT COUNT(*) n FROM items WHERE published_at > ?", (last,)).fetchone()["n"] if last else public["n"]
    from datetime import datetime, timezone
    age = (datetime.now(timezone.utc) - datetime.strptime(last, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
           ).total_seconds() if last else 1e9
    gap = gap_seconds(c)
    if age < gap:
        return False, f"ran in the last {gap / 60:.0f} minutes"
    if new or public["n"] != seen:
        return True, f"{new} newly published" if new else "content changed"
    return False, "nothing new"


def run(c) -> dict:
    rows = c.execute("""SELECT id, taken_at, summary, analysis, categories FROM items WHERE published_at IS NOT NULL
                        ORDER BY taken_at DESC""").fetchall()
    in_prompt = rows[:MAX_ITEMS_IN_PROMPT]
    cur = current(c)
    cur_brief = [{"id": f["id"], "name": f["name"], "categories": [{"id": k["id"], "name": k["name"]}
                                                                    for k in f["categories"]]} for f in cur["facets"]]
    prompt = PROMPT.replace("{notes}", cur.get("notes") or "(none yet: this is the first run with notes)").replace(
        "{fared}", j(fared(c, cur))).replace("{current}", j(cur_brief)).replace(
        "{items}", "\n".join(_line(n, r) for n, r in enumerate(in_prompt)))
    body = {"max_tokens": 16000, "output_config": {"effort": "medium", "format": {"type": "json_schema", "schema": SCHEMA}},
            "messages": [{"role": "user", "content": prompt}]}
    resp, coins = aicoin.claude(body, timeout=600)
    usage = resp.get("usage") or {}
    model = resp.get("model") or ""
    c.execute("INSERT INTO costs(at, purpose, model, input_tokens, output_tokens, coins, usd, ok) VALUES (?,?,?,?,?,?,?,1)",
              (now(), "facets", model, usage.get("input_tokens"), usage.get("output_tokens"), coins, usd_for(model, usage)))
    if resp.get("stop_reason") not in ("end_turn", "stop_sequence", None):
        raise RuntimeError(f"facets answer ended with {resp.get('stop_reason')}")
    out = json.loads("".join(b.get("text", "") for b in resp.get("content") or [] if b.get("type") == "text"))

    facets = []
    seen_f = set()
    for f in out.get("facets") or []:
        fid = slugify(f.get("id") or f.get("name") or "")
        if not fid or fid in seen_f:
            continue
        seen_f.add(fid)
        cats, seen_c = [], set()
        for k in f.get("categories") or []:
            cid = slugify(k.get("id") or k.get("name") or "")
            if not cid or cid in seen_c:
                continue
            seen_c.add(cid)
            ids = sorted({in_prompt[n]["id"] for n in k.get("items") or [] if isinstance(n, int) and 0 <= n < len(in_prompt)})
            cats.append({"id": cid, "name": (k.get("name") or cid)[:60], "description": (k.get("description") or "")[:300],
                         "item_ids": ids})
        if cats:
            facets.append({"id": fid, "name": (f.get("name") or fid)[:60], "description": (f.get("description") or "")[:300],
                           "categories": cats})

    rest = [r["id"] for r in rows[MAX_ITEMS_IN_PROMPT:]] + ["hit:" + h for h in published_hit_ids()]
    _assign_by_similarity(c, facets, rest)

    notes = (out.get("notes") or "").strip()[:4000]
    doc = {"facets": facets, "generated_at": now(), "model": model, "items": len(rows), "notes": notes,
           "considered": [r["id"] for r in in_prompt] + rest, "joined": []}
    with tx(c):
        set_setting(c, "facets.current", j(doc))
        set_setting(c, "facets.last_run", now())
        set_setting(c, "facets.public_seen", str(len(rows)))
    if notes:
        c.execute("INSERT INTO facet_notes(at, notes) VALUES (?,?)", (now(), notes))
    event("facets.generated", notes=len(notes), facets=[f["id"] for f in facets], categories=sum(len(f["categories"]) for f in facets),
          items=len(rows), coins=coins, input_tokens=usage.get("input_tokens"), output_tokens=usage.get("output_tokens"))
    return doc


def _key(i: str) -> str:
    """A category member's id as the site knows it: an item's id, or a found clip's without "hit:"."""
    return i[4:] if i.startswith("hit:") else i


def _assign_by_similarity(c, facets, ids, threshold: float = 0.45, vec=None) -> list[str]:
    """Videos Claude has not seen (beyond one call, or new since): each joins, per facet, the category
    whose members it is most like. `ids` are embedding ids ("hit:<id>" for found clips). Returns the
    "<facet>:<category>" each joined."""
    if not ids:
        return []
    import numpy as np
    from .home import vectors
    vec = vec if vec is not None else vectors(c)
    joined = []
    for f in facets:
        cents = []
        for k in f["categories"]:
            vs = [vec[i] for i in k["item_ids"] if i in vec] + [vec["hit:" + i] for i in k["item_ids"] if "hit:" + i in vec]
            if vs:
                m = np.mean(vs, axis=0)
                cents.append((k, m / (np.linalg.norm(m) + 1e-9)))
        for i in ids:
            if i not in vec or not cents:
                continue
            k, sim = max(((k, float(m @ vec[i])) for k, m in cents), key=lambda t: t[1])
            if sim >= threshold and _key(i) not in k["item_ids"]:
                k["item_ids"].append(_key(i))
                joined.append(f"{f['id']}:{k['id']}")
    return joined


def published_hit_ids() -> list[str]:
    from .home import published_hits
    return [h["id"] for h in published_hits()]


def place_new(c) -> int:
    """Between runs: every video published since (and every found clip) joins its nearest categories,
    once it has an embedding. Free (no AI). Returns how many were placed."""
    doc = current(c)
    if not doc.get("facets"):
        return 0
    from .home import vectors
    vec = vectors(c)
    done = set(doc.get("considered") or [])
    for f in doc["facets"]:
        for k in f["categories"]:
            done.update(k["item_ids"])
    ids = [r["id"] for r in c.execute("SELECT id FROM items WHERE published_at IS NOT NULL ORDER BY taken_at DESC")]
    ids += ["hit:" + h for h in published_hit_ids()]
    todo = [i for i in ids if _key(i) not in done and i not in done and i in vec]
    if not todo:
        return 0
    joined = _assign_by_similarity(c, doc["facets"], todo, vec=vec)
    doc["considered"] = sorted(set(doc.get("considered") or []) | set(todo))
    doc["joined"] = (doc.get("joined") or []) + joined
    doc["placed_at"] = now()
    set_setting(c, "facets.current", j(doc))
    event("facets.placed", videos=len(todo), joined=len(joined))
    return len(todo)


def fared(c, doc: dict) -> dict:
    """How the current categories did since they were made: what the next run's notes act on."""
    public = {r["id"] for r in c.execute("SELECT id FROM items WHERE published_at IS NOT NULL")} | set(published_hit_ids())
    joined: dict[str, int] = {}
    for x in doc.get("joined") or []:
        joined[x] = joined.get(x, 0) + 1
    inside = set()
    cats = []
    for f in doc.get("facets") or []:
        for k in f["categories"]:
            ids = [i for i in k["item_ids"] if i in public]
            inside.update(ids)
            cats.append({"category": f"{f['id']}:{k['id']}", "videos": len(ids),
                         "joined_by_similarity_since": joined.get(f"{f['id']}:{k['id']}", 0)})
    return {"public_videos": len(public), "in_no_category": len(public - inside), "categories": cats}


def public_view(c) -> dict:
    """The facets with only the items that are public right now, and their counts."""
    doc = current(c)
    public = {r["id"] for r in c.execute("SELECT id FROM items WHERE published_at IS NOT NULL")} | set(published_hit_ids())
    facets = []
    for f in doc.get("facets") or []:
        cats = []
        for k in f["categories"]:
            ids = [i for i in k["item_ids"] if i in public]
            if ids:
                cats.append({"id": k["id"], "name": k["name"], "description": k.get("description"),
                             "count": len(ids), "item_ids": ids})
        cats.sort(key=lambda k: (-k["count"], k["name"]))
        if cats:
            facets.append({"id": f["id"], "name": f["name"], "description": f.get("description"), "categories": cats})
    return {"facets": facets, "generated_at": doc.get("generated_at")}


def item_ids_for(c, ref: str) -> set[str]:
    """`facet:category` -> the public item ids in it."""
    fid, _, cid = ref.partition(":")
    for f in public_view(c)["facets"]:
        if f["id"] == fid:
            for k in f["categories"]:
                if k["id"] == cid:
                    return set(k["item_ids"])
    return set()
