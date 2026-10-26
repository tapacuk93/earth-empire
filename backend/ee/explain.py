"""What is happening in an item, in the viewer's language (CONTRACT.md "Explain"): the "?" of the
apps' and the site's fullscreen viewer.

A post with a caption is explained by its own description, translated faithfully (nothing added).
Anything else (a story, a repost, a post without a caption) by Claude from the item's analysis: who
appears, what happens, where, what is said. One answer per item, language and analysis, kept in
`explanations`; new answers are capped per day (`explain.daily_cap`), since the endpoint is public.
"""
from __future__ import annotations

import hashlib
import json
import re

from . import aicoin
from .analysis import usd_for
from .db import now, setting
from .logs import event

TABLE = """CREATE TABLE IF NOT EXISTS explanations (
  item_id TEXT NOT NULL, lang TEXT NOT NULL, source TEXT NOT NULL, text TEXT NOT NULL, mode TEXT NOT NULL,
  model TEXT, created_at TEXT NOT NULL, PRIMARY KEY(item_id, lang, source))"""

DAILY_CAP = 300
LANG = re.compile(r"^[a-z]{2,3}$")

PROMPT = """You write the "?" of a fullscreen video viewer: a short explanation of what is happening in \
this Instagram item, for a viewer who reads {language}.

{task}

Write in {language} only, two to four plain sentences, no heading, no lists, no emoji, no quotation \
marks around the whole text. Names of people and places stay as they are. Say only what the material \
below supports.

{material}"""

TASK_CAPTION = """This is the owner's own post: explain it with the post's own description (the caption \
below), translated faithfully into {language}. Keep its meaning and tone; add nothing, drop nothing \
important. If the caption is already in {language}, return it as it is, tidied only of hashtags."""

TASK_ANALYSIS = """Explain who appears, what happens, where and when, and what is said, from the \
analysis below."""


def normalize(lang: str | None) -> str | None:
    """`uk-UA` -> `uk`; None for anything that is not a language subtag."""
    code = (lang or "").strip().lower().replace("_", "-").split("-")[0]
    return code if LANG.match(code) else None


def language_name(code: str) -> str:
    try:
        from babel import Locale  # optional
        return Locale("en").languages.get(code) or code
    except Exception:
        return {"en": "English", "uk": "Ukrainian", "ru": "Russian", "de": "German", "fr": "French", "es": "Spanish",
                "it": "Italian", "pl": "Polish", "pt": "Portuguese", "tr": "Turkish", "hu": "Hungarian", "ja": "Japanese",
                "zh": "Chinese", "ko": "Korean", "ar": "Arabic", "nl": "Dutch", "cs": "Czech", "ro": "Romanian",
                "sr": "Serbian", "fi": "Finnish", "sv": "Swedish", "uz": "Uzbek", "be": "Belarusian"}.get(code, code)


def caption_of(row) -> str | None:
    """The owner's own description: a post (not a story, not a repost) with a caption."""
    d = json.loads(row["data"] or "{}")
    cap = (d.get("caption") or "").strip()
    return cap if row["kind"] in ("post", "carousel", "reel") and not d.get("repost_of") and cap else None


def material(row) -> tuple[str, str]:
    """(mode, text) for the prompt: the caption for a post, else the analysis."""
    cap = caption_of(row)
    if cap:
        return "caption", f"Caption:\n{cap}"
    a = json.loads(row["analysis"] or "{}")
    keep = {k: a.get(k) for k in ("what", "people", "events", "when", "where", "speech", "on_screen_text", "context", "mood")
            if a.get(k)}
    parts = [f"Summary: {row['summary']}" if row["summary"] else "", f"Description: {row['description']}" if row["description"] else "",
             f"Taken: {row['taken_at']}", f"Analysis: {json.dumps(keep, ensure_ascii=False)[:6000]}"]
    return "analysis", "\n".join(p for p in parts if p)


def source_hash(mode: str, text: str) -> str:
    return hashlib.sha256(f"{mode}\n{text}".encode()).hexdigest()[:16]


def cached(c, item_id: str, lang: str, source: str):
    c.execute(TABLE)
    return c.execute("SELECT * FROM explanations WHERE item_id=? AND lang=? AND source=?", (item_id, lang, source)).fetchone()


def made_today(c) -> int:
    c.execute(TABLE)
    return c.execute("SELECT COUNT(*) FROM explanations WHERE created_at >= ?", (now()[:10],)).fetchone()[0]


class CapReached(Exception):
    pass


def explain(c, row, lang: str) -> dict:
    """{"lang", "mode": "caption" | "analysis", "text", "model", "cached"}; raises CapReached past the daily cap."""
    mode, text = material(row)
    src = source_hash(mode, text)
    hit = cached(c, row["id"], lang, src)
    if hit:
        return {"lang": lang, "mode": hit["mode"], "text": hit["text"], "model": hit["model"], "cached": True}
    if made_today(c) >= int(setting(c, "explain.daily_cap") or DAILY_CAP):
        raise CapReached()
    language = language_name(lang)
    task = (TASK_CAPTION if mode == "caption" else TASK_ANALYSIS).replace("{language}", language)
    prompt = PROMPT.replace("{language}", language).replace("{task}", task).replace("{material}", text)
    body = {"max_tokens": 700, "messages": [{"role": "user", "content": prompt}]}
    resp, coins = aicoin.claude(body, timeout=90)
    usage = resp.get("usage") or {}
    model = resp.get("model") or ""
    out = "".join(b.get("text", "") for b in resp.get("content") or [] if b.get("type") == "text").strip()
    c.execute("INSERT INTO costs(at, item_id, purpose, model, input_tokens, output_tokens, coins, usd, ok) VALUES (?,?,?,?,?,?,?,?,?)",
              (now(), row["id"], "explain", model, usage.get("input_tokens"), usage.get("output_tokens"), coins,
               usd_for(model, usage), 1 if out else 0))
    if not out:
        raise RuntimeError("empty explanation")
    c.execute("INSERT OR REPLACE INTO explanations(item_id, lang, source, text, mode, model, created_at) VALUES (?,?,?,?,?,?,?)",
              (row["id"], lang, src, out, mode, model, now()))
    event("explain.made", item=row["id"], lang=lang, mode=mode, coins=coins)
    return {"lang": lang, "mode": mode, "text": out, "model": model, "cached": False}
