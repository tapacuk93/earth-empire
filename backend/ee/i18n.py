"""Everything public in the visitor's language (CONTRACT.md "Translations"): item texts (summary,
description, caption), highlight names, facet and category names and descriptions, and the site's own
words (web/src/i18n/strings.json). A low-priority job: it runs only once every item has its first
analysis, on the small model, in batches, for the languages visitors ask for (their browser's
language, `?lang=`) and a base set. Until a text is translated, the original is served.
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

from . import aicoin
from .analysis import usd_for
from .db import now, tx
from .logs import event

BASE = ("en", "uk", "ru", "es", "fr", "de", "pt", "it", "pl", "tr", "ar", "zh", "ja", "ko", "hi")
NAMES = {"en": "English", "uk": "Ukrainian", "ru": "Russian", "es": "Spanish", "fr": "French", "de": "German",
         "pt": "Portuguese", "it": "Italian", "pl": "Polish", "tr": "Turkish", "ar": "Arabic", "zh": "Chinese (Simplified)",
         "ja": "Japanese", "ko": "Korean", "hi": "Hindi"}
BATCH = 60
STRINGS = Path(__file__).resolve().parents[2] / "web" / "src" / "i18n" / "strings.json"
ITEM_FIELDS = ("summary", "description", "caption")

SCHEMA = {"type": "object", "additionalProperties": False, "required": ["texts"],
          "properties": {"texts": {"type": "array", "items": {
              "type": "object", "additionalProperties": False, "required": ["n", "text"],
              "properties": {"n": {"type": "integer"}, "text": {"type": "string"}}}}}}

PROMPT = """Translate each text into {language}. They are from Earth Empire, a site that mirrors one
person's Instagram (world politics, diplomacy, his own posts): post captions and descriptions,
highlight names, category names, and the site's own buttons and labels. Keep names of people, places,
@handles, #hashtags, numbers, emoji and line breaks; keep it as short as the original. A text already
in {language} comes back unchanged. Answer with every number.

Texts, one per block as number | text:
{texts}"""


def norm(lang: str | None) -> str | None:
    """A language code from ?lang= or a browser tag ("uk-UA" -> "uk"); None for none or nonsense."""
    m = re.match(r"^\s*([a-zA-Z]{2,3})(?:[-_][A-Za-z0-9]+)*\s*$", lang or "")
    return m.group(1).lower() if m else None


def key(text: str) -> str:
    return hashlib.sha1(text.strip().encode()).hexdigest()[:20]


def ensure(c) -> None:
    c.execute("CREATE TABLE IF NOT EXISTS translations (key TEXT NOT NULL, lang TEXT NOT NULL, text TEXT NOT NULL, "
              "at TEXT NOT NULL, PRIMARY KEY (key, lang))")
    c.execute("CREATE TABLE IF NOT EXISTS translation_demand (lang TEXT PRIMARY KEY, hits INTEGER NOT NULL DEFAULT 0, "
              "last_at TEXT NOT NULL)")


def wanted(c, lang: str | None) -> str | None:
    """Record that a visitor reads in `lang` (the job translates for it); returns the code."""
    lang = norm(lang)
    if not lang:
        return None
    try:
        ensure(c)
        c.execute("INSERT INTO translation_demand(lang, hits, last_at) VALUES (?,1,?) ON CONFLICT(lang) "
                  "DO UPDATE SET hits=hits+1, last_at=excluded.last_at", (lang, now()))
    except Exception:  # noqa: BLE001 - a read-only moment never fails a page
        pass
    return lang


def lookup(c, texts: list[str], lang: str) -> dict[str, str]:
    texts = [t for t in {t for t in texts if t and t.strip()}]
    if not texts:
        return {}
    ensure(c)
    keys = {key(t): t for t in texts}
    out = {}
    ks = list(keys)
    for i in range(0, len(ks), 500):
        part = ks[i:i + 500]
        for r in c.execute(f"SELECT key, text FROM translations WHERE lang=? AND key IN ({','.join('?' * len(part))})",
                           (lang, *part)):
            out[keys[r["key"]]] = r["text"]
    return out


# ------------------------------------------------------------------ applying to API answers
def items(c, ds: list[dict], lang: str | None) -> list[dict]:
    """Rendered items in `lang`: translated fields replace the originals, which stay under `original`."""
    if not lang:
        return ds
    texts = [d.get(f) or "" for d in ds for f in ITEM_FIELDS]
    texts += [h.get("title_full") or h.get("title") or "" for d in ds for h in d.get("highlights") or [] if isinstance(h, dict)]
    tr = lookup(c, texts, lang)
    for d in ds:
        orig = {}
        for f in ITEM_FIELDS:
            v = d.get(f)
            if v and tr.get(v) and tr[v] != v:
                orig[f] = v
                d[f] = tr[v]
        for h in d.get("highlights") or []:
            if isinstance(h, dict):
                src = h.get("title_full") or h.get("title")
                if src and tr.get(src) and tr[src] != src:
                    h["title_translated"] = tr[src]
        if orig:
            d["original"] = orig
        d["lang"] = lang
    return ds


def facets(c, view: dict, lang: str | None) -> dict:
    if not lang:
        return view
    texts = [x for f in view.get("facets") or [] for x in [f.get("name"), f.get("description")] +
             [y for k in f["categories"] for y in (k.get("name"), k.get("description"))]]
    tr = lookup(c, [t or "" for t in texts], lang)
    for f in view.get("facets") or []:
        for obj in [f] + f["categories"]:
            for fld in ("name", "description"):
                if obj.get(fld) and tr.get(obj[fld]):
                    obj[fld] = tr[obj[fld]]
    view["lang"] = lang
    return view


def highlights(c, hls: list[dict], lang: str | None) -> list[dict]:
    if not lang:
        return hls
    tr = lookup(c, [h.get("title_full") or h.get("title") or "" for h in hls], lang)
    for h in hls:
        src = h.get("title_full") or h.get("title")
        if src and tr.get(src) and tr[src] != src:
            h["title_translated"] = tr[src]
    return hls


def ui_strings() -> list[str]:
    try:
        return [s for s in json.loads(STRINGS.read_text()) if isinstance(s, str) and s.strip()]
    except (OSError, ValueError):
        return []


def ui(c, lang: str | None) -> dict:
    """The site's own words in `lang`: {english: translated}."""
    lang = norm(lang)
    if not lang or lang == "en":
        return {"lang": lang or "en", "strings": {}}
    return {"lang": lang, "strings": lookup(c, ui_strings(), lang)}


# ------------------------------------------------------------------ the job
def sources(c) -> list[str]:
    """Every public text to translate: the site's words and names first (short, seen by everyone), then items newest first."""
    from .facets import public_view
    out = list(ui_strings())
    for f in public_view(c)["facets"]:
        out += [f["name"], f.get("description") or ""]
        for k in f["categories"]:
            out += [k["name"], k.get("description") or ""]
    for r in c.execute("SELECT title, title_full, title_full_of FROM highlights ORDER BY position"):
        out.append(r["title_full"] if r["title_full"] and r["title_full_of"] == r["title"] else r["title"] or "")
    for r in c.execute("SELECT summary, description, data FROM items WHERE published_at IS NOT NULL ORDER BY taken_at DESC"):
        out += [r["summary"] or "", r["description"] or "", (json.loads(r["data"]).get("caption") or "")[:2000]]
    seen, uniq = set(), []
    for t in out:
        t = (t or "").strip()
        if t and t not in seen:
            seen.add(t)
            uniq.append(t)
    return uniq


def languages(c) -> list[str]:
    """Visitors' languages first (most read), then the base set."""
    ensure(c)
    asked = [r["lang"] for r in c.execute("SELECT lang FROM translation_demand ORDER BY hits DESC")]
    return list(dict.fromkeys(asked + list(BASE)))


def next_batch(c) -> tuple[str, list[str]] | None:
    src = sources(c)
    if not src:
        return None
    for lang in languages(c):
        have = lookup(c, src, lang)
        todo = [t for t in src if t not in have]
        if todo:
            return lang, todo[:BATCH]
    return None


def run(c) -> int:
    """Translate one batch for the language most in need. Returns how many texts were done."""
    nb = next_batch(c)
    if not nb:
        return 0
    lang, texts = nb
    name = NAMES.get(lang, f"the language with ISO 639 code '{lang}'")
    prompt = PROMPT.replace("{language}", name).replace(
        "{texts}", "\n\n".join(f"{n} | {t}" for n, t in enumerate(texts)))
    body = {"model": aicoin.model_for(c, "translate"), "max_tokens": 16000,
            "output_config": {"effort": "low", "format": {"type": "json_schema", "schema": SCHEMA}},
            "messages": [{"role": "user", "content": prompt}]}
    resp, coins = aicoin.claude(body, timeout=300)
    usage = resp.get("usage") or {}
    model = resp.get("model") or body["model"]
    c.execute("INSERT INTO costs(at, purpose, model, input_tokens, output_tokens, coins, usd, ok, note) VALUES (?,?,?,?,?,?,?,1,?)",
              (now(), "translate", model, usage.get("input_tokens"), usage.get("output_tokens"), coins, usd_for(model, usage), lang))
    out = json.loads("".join(b.get("text", "") for b in resp.get("content") or [] if b.get("type") == "text"))
    got = {x["n"]: x.get("text") or "" for x in out.get("texts") or [] if isinstance(x.get("n"), int)}
    ts = now()
    done = 0
    with tx(c):
        for n, t in enumerate(texts):
            # a text left out comes back as itself, so one odd text never holds the queue
            c.execute("INSERT OR REPLACE INTO translations(key, lang, text, at) VALUES (?,?,?,?)",
                      (key(t), lang, (got.get(n) or "").strip() or t, ts))
            done += bool((got.get(n) or "").strip())
    event("i18n.translated", lang=lang, texts=len(texts), done=done, coins=coins)
    return done
