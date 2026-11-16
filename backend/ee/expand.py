"""Highlight names written out in full: the owner often shortens them on Instagram ("плнт" for
"планета", "прзд" for "президент"). Claude writes each name out once (and again when it is renamed);
cards show the full name and the monitor listens for it. A name that is not shortened stays as it is.
"""
from __future__ import annotations

import json
import re
from collections import Counter

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
"президент"), or uses a common abbreviation. The owner is Тарас Маслов: "Трс" is "Тарас" (or "Тараса"
after "у"/"в"), "ТМ" may be his initials. Write each name out in full, in the same language and
word order, keeping numbers, emoji and everything that is not shortened exactly as it is. When a name
is not shortened, or you cannot tell what it stands for, return it unchanged. Never translate or
explain.

Names, one per line as number | name:
{names}"""


# ------------------------------------------------------------------ without AI
# A word written without its vowels ("Трс") is written out from the owner's own highlight names:
# the same consonants in a word spelled in full elsewhere ("Тарас", "у Тараса"). It needs no AI, so
# it works while the wallet is empty; a name Claude has written out wins.
VOWELS = set("аеєиіїоуюяыэёaeiouy")
WORD = re.compile(r"[^\W\d_]+")
_vocab: tuple = (None, {})


def skeleton(w: str) -> str:
    return "".join(ch for ch in w.lower() if ch not in VOWELS)


def build_vocab(names) -> dict:
    """skeleton -> {"word": the base form (the shortest spelling, "Тарас" over "Тараса", then the
    commonest), "after": {preceding word: the form most often written after it ("у" -> "Тараса")}}."""
    seen, after = Counter(), Counter()
    for n in names:
        ws = WORD.findall(n or "")
        for i, w in enumerate(ws):
            if len(w) >= 3 and set(w.lower()) & VOWELS and len(skeleton(w)) >= 2:
                seen[w] += 1
                if i:
                    after[(ws[i - 1].lower(), w)] += 1
    out: dict = {}
    for w, n in seen.items():
        e = out.setdefault(skeleton(w), {"word": w, "n": n, "after": {}})
        if (len(w), -n) < (len(e["word"]), -e["n"]):
            e["word"], e["n"] = w, n
    best: dict = {}
    for (prev, w), n in after.items():
        k = (skeleton(w), prev)
        if n > best.get(k, ("", 0))[1]:
            best[k] = (w, n)
    for (k, prev), (w, _) in best.items():
        out[k]["after"][prev] = w
    return out


def vocab(c) -> dict:
    global _vocab
    sig = tuple(c.execute("SELECT COUNT(*), MAX(updated_at), MAX(title_full_of) FROM highlights").fetchone())
    if _vocab[0] != sig:
        rows = c.execute("SELECT title, title_full FROM highlights").fetchall()
        _vocab = (sig, build_vocab([r["title"] for r in rows] + [r["title_full"] for r in rows]))
    return _vocab[1]


def write_out(name: str, voc: dict) -> str:
    """Vowel-less words (three letters or more, not an all-caps abbreviation) the vocabulary knows, written out."""
    out, last, prev = [], 0, ""
    for m in WORD.finditer(name):
        w, full = m.group(0), None
        if len(w) >= 3 and not set(w.lower()) & VOWELS and not w.isupper():
            e = voc.get(skeleton(w))
            if e:
                full = e["after"].get(prev) or e["word"]
        if full and len(full) > len(w):
            full = full[0].upper() + full[1:] if w[0].isupper() else full[0].lower() + full[1:]
            out.append(name[last:m.start()] + full)
            last = m.end()
        prev = w.lower()
    return "".join(out) + name[last:]


def written(c, title, title_full=None, title_full_of=None):
    """The name to show for a highlight: Claude's written-out name for its current title, else the
    title with its vowel-less words written out; None when that is the title itself."""
    if not title:
        return None
    base = title_full if title_full and title_full_of == title else title
    out = write_out(base, vocab(c))
    return None if out.strip() == title.strip() else out


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
