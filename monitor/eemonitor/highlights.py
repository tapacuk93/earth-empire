"""tapacuk93's highlights, as the monitor uses them:

- **Phrase suggestions.** Claude reads the highlight titles (and a few of their items' summaries)
  and suggests further phrases worth listening for - names, places, terms - with how they sound in
  uk/ru/en. They wait in `phrase_suggestions` until the owner accepts (then they become phrases) or
  rejects them. Nothing is added without acceptance.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os

from . import db

log = logging.getLogger("ee.monitor.highlights")
API = os.environ.get("EE_API_URL", "http://127.0.0.1:8000").rstrip("/")

SCHEMA = """
CREATE TABLE IF NOT EXISTS phrase_suggestions (
  text TEXT PRIMARY KEY, why TEXT, sounds TEXT NOT NULL DEFAULT '{}', source TEXT,
  state TEXT NOT NULL DEFAULT 'suggested',      -- suggested | accepted | rejected
  created_at TEXT NOT NULL, decided_at TEXT
);
"""


def ensure(c) -> None:
    c.executescript(SCHEMA)
    cols = {r["name"] for r in c.execute("PRAGMA table_info(hits)")}
    if "section" not in cols:
        c.execute("ALTER TABLE hits ADD COLUMN section TEXT")


def fetch_highlights() -> list[dict]:
    import httpx
    r = httpx.get(API + "/v1/highlights", timeout=20)
    r.raise_for_status()
    hls = r.json().get("highlights", [])
    for h in hls:
        h["summaries"] = []
        for iid in (h.get("item_ids") or [])[:4]:
            try:
                it = httpx.get(f"{API}/v1/items/{iid}", timeout=10)
                if it.status_code == 200:
                    s = it.json().get("summary") or (it.json().get("caption") or "")[:160]
                    if s:
                        h["summaries"].append(s)
            except Exception:  # noqa: BLE001
                pass
    return hls


def suggest_phrases(c, force: bool = False) -> int:
    """Ask Claude, once per change of the highlights, what else is worth listening for."""
    from . import judge
    ensure(c)
    hls = fetch_highlights()
    sig = hashlib.sha1(db.j([(h["id"], h.get("title")) for h in hls]).encode()).hexdigest()[:12]
    if not hls or (db.setting(c, "highlights.suggested_sig") == sig and not force):
        return 0
    current = [r["text"] for r in c.execute("SELECT text FROM phrases")]
    known = current + [r["text"] for r in c.execute("SELECT text FROM phrase_suggestions")]
    lines = "\n".join(f"- {h.get('title')}: " + "; ".join(h["summaries"][:3]) for h in hls)
    prompt = (
        "A person (Instagram tapacuk93) keeps these highlights on their profile (title: example summaries):\n"
        f"{lines}\n\nA monitor listens to public videos of governments and international organisations for "
        f"phrases that matter to this person. It already listens for: {', '.join(current)}.\n"
        "Suggest up to 15 further phrases worth detecting that these highlight topics imply: names of people, "
        "places, organisations or specific terms. For each, how it sounds or is written in Ukrainian, Russian "
        "and English. Skip anything already listed or too generic to be useful.\n"
        "Answer only with JSON lines: {\"text\": \"<the phrase, lowercase, in the language most likely spoken>\", "
        "\"why\": \"<which highlight and why, briefly>\", \"uk\": \"...\", \"ru\": \"...\", \"en\": \"...\"}")
    text = judge.ask(c, prompt, "phrase-suggestions", max_tokens=1500)
    if text is None:
        return 0
    n = 0
    for line in text.splitlines():
        line = line.strip().strip(",")
        if not line.startswith("{"):
            continue
        try:
            s = json.loads(line)
        except ValueError:
            continue
        t = (s.get("text") or "").strip().lower()
        if not t or len(t) > 60 or t in known:
            continue
        c.execute("INSERT OR IGNORE INTO phrase_suggestions(text, why, sounds, source, created_at) VALUES (?,?,?,?,?)",
                  (t, (s.get("why") or "")[:300], db.j({k: s.get(k) for k in ("uk", "ru", "en") if s.get(k)}),
                   "highlights", db.now()))
        n += 1
    db.set_setting(c, "highlights.suggested_sig", sig)
    log.info(json.dumps({"event": "monitor.phrase_suggestions", "added": n}))
    return n


def list_suggestions(c, state: str = "suggested") -> list[dict]:
    ensure(c)
    return [{"text": r["text"], "why": r["why"], "sounds": json.loads(r["sounds"]), "source": r["source"],
             "state": r["state"], "created_at": r["created_at"]}
            for r in c.execute("SELECT * FROM phrase_suggestions WHERE state=? ORDER BY created_at", (state,))]


def decide(c, text: str, accept: bool) -> bool:
    from .worker import list_phrases, set_phrases
    ensure(c)
    r = c.execute("SELECT * FROM phrase_suggestions WHERE text=?", (text.lower(),)).fetchone()
    if not r:
        return False
    c.execute("UPDATE phrase_suggestions SET state=?, decided_at=? WHERE text=?",
              ("accepted" if accept else "rejected", db.now(), r["text"]))
    if accept:
        sounds = json.loads(r["sounds"])
        cur = [p["text"] for p in list_phrases(c)]
        if r["text"] not in cur:
            set_phrases(c, cur + [r["text"]], use_claude=True)
            row = c.execute("SELECT * FROM phrases WHERE text=?", (r["text"],)).fetchone()
            if row and sounds:   # the suggested spellings join the phrase's variants
                from . import phrases as ph
                extra = list(dict.fromkeys(json.loads(row["claude_variants"]) + [v.lower() for v in sounds.values()]))
                c.execute("UPDATE phrases SET claude_variants=?, compiled=? WHERE text=?",
                          (db.j(extra), db.j(ph.variants(r["text"], extra)), r["text"]))
            db.set_setting(c, "rescan.requested", db.now())
    return True
