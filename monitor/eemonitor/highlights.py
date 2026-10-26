"""tapacuk93's highlights, as the monitor uses them:

- **Phrase suggestions.** Claude reads the highlight titles (and a few of their items' summaries)
  and suggests further phrases worth listening for - names, places, terms - with how they sound in
  uk/ru/en. They wait in `phrase_suggestions` until the owner accepts (then they become phrases) or
  rejects them. Nothing is added without acceptance.
- **Highlight names as phrases** (setting `phrases.from_highlights`, on by default). The owner's
  highlight titles are what he hears in the videos he saves and reposts ("в Тараса три", "має цих
  трьох"), so every title ever seen - current ones and archived ones that left the profile - is
  listened for, with all its variants, beside the owner's own phrases (`phrases.owner`). Titles are
  kept in `highlight_titles`; a changed list rescans the stored transcripts.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import re

from . import db

log = logging.getLogger("ee.monitor.highlights")
API = os.environ.get("EE_API_URL", "http://127.0.0.1:8000").rstrip("/")

SCHEMA = """
CREATE TABLE IF NOT EXISTS phrase_suggestions (
  text TEXT PRIMARY KEY, why TEXT, sounds TEXT NOT NULL DEFAULT '{}', source TEXT,
  state TEXT NOT NULL DEFAULT 'suggested',      -- suggested | accepted | rejected
  created_at TEXT NOT NULL, decided_at TEXT
);
CREATE TABLE IF NOT EXISTS highlight_titles (   -- every highlight title seen; current=0 once it left the profile
  title TEXT PRIMARY KEY, phrase TEXT, items INTEGER NOT NULL DEFAULT 0, current INTEGER NOT NULL DEFAULT 1,
  first_seen TEXT NOT NULL, last_seen TEXT NOT NULL
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


NUMBERS = {"3": "три", "lll": "три", "iii": "три"}


def phrase_of(title: str | None) -> str | None:
    """A title as a phrase the matcher can use: lowercase words, numbers as words, and no words under
    three letters ("у", "в", "ці" are too short to match on their own)."""
    words = [NUMBERS.get(w, w) for w in re.findall(r"\w+", (title or "").lower())]
    words = [w for w in words if len(w) >= 3 and not w.isdigit()]
    return " ".join(words) or None


def sync_titles(c, hls: list[dict] | None = None) -> int:
    """Record the profile's current highlight titles; titles no longer there stay, as archived."""
    import httpx
    ensure(c)
    if hls is None:
        r = httpx.get(API + "/v1/highlights", timeout=20)
        r.raise_for_status()
        hls = r.json().get("highlights", [])
    now, seen = db.now(), {}
    for h in hls:
        t = (h.get("title") or "").strip()
        if t:
            seen[t] = seen.get(t, 0) + len(h.get("item_ids") or [])
    if not seen:
        return 0   # an empty answer is a failure, not every highlight archived
    for t, n in seen.items():
        c.execute("""INSERT INTO highlight_titles(title, phrase, items, current, first_seen, last_seen) VALUES (?,?,?,1,?,?)
                     ON CONFLICT(title) DO UPDATE SET items=excluded.items, current=1, last_seen=excluded.last_seen,
                     phrase=excluded.phrase""", (t, phrase_of(t), n, now, now))
    c.execute(f"UPDATE highlight_titles SET current=0 WHERE title NOT IN ({','.join('?' * len(seen))})", list(seen))
    return len(seen)


def titles(c) -> list[dict]:
    ensure(c)
    return [dict(r) | {"current": bool(r["current"])} for r in
            c.execute("SELECT * FROM highlight_titles ORDER BY current DESC, items DESC, title")]


def owner_phrases(c) -> list[str]:
    from .phrases import DEFAULT_PHRASES
    try:
        return json.loads(db.setting(c, "phrases.owner") or "null") or list(DEFAULT_PHRASES)
    except ValueError:
        return list(DEFAULT_PHRASES)


def effective(c) -> list[str]:
    """The owner's phrases, then (when on) every highlight title's phrase, without repeats."""
    out = [p.strip().lower() for p in owner_phrases(c) if p.strip()]
    if db.setting(c, "phrases.from_highlights") == "1":
        out += [r["phrase"] for r in c.execute(
            "SELECT phrase FROM highlight_titles WHERE phrase IS NOT NULL ORDER BY current DESC, items DESC")]
    return list(dict.fromkeys(out))


def apply(c, owner: list[str] | None = None, use_claude: bool = False) -> bool:
    """Make the listened-for phrases the effective list; rescan when it changed."""
    from .worker import set_phrases
    ensure(c)
    if owner is not None:
        db.set_setting(c, "phrases.owner", db.j(list(dict.fromkeys(p.strip().lower() for p in owner if p.strip()))))
    want = effective(c)
    have = [r["text"] for r in c.execute("SELECT text FROM phrases ORDER BY position")]
    if want == have:
        return False
    new_owner = set(owner_phrases(c))
    set_phrases(c, want, use_claude=lambda t: use_claude and t in new_owner)
    db.set_setting(c, "rescan.requested", db.now())
    log.info(json.dumps({"event": "monitor.phrases_applied", "phrases": len(want)}, ensure_ascii=False))
    return True


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
    ensure(c)
    r = c.execute("SELECT * FROM phrase_suggestions WHERE text=?", (text.lower(),)).fetchone()
    if not r:
        return False
    c.execute("UPDATE phrase_suggestions SET state=?, decided_at=? WHERE text=?",
              ("accepted" if accept else "rejected", db.now(), r["text"]))
    if accept:
        sounds = json.loads(r["sounds"])
        cur = owner_phrases(c)
        if r["text"] not in cur:
            apply(c, cur + [r["text"]], use_claude=True)
            row = c.execute("SELECT * FROM phrases WHERE text=?", (r["text"],)).fetchone()
            if row and sounds:   # the suggested spellings join the phrase's variants
                from . import phrases as ph
                extra = list(dict.fromkeys(json.loads(row["claude_variants"]) + [v.lower() for v in sounds.values()]))
                c.execute("UPDATE phrases SET claude_variants=?, compiled=? WHERE text=?",
                          (db.j(extra), db.j(ph.variants(r["text"], extra)), r["text"]))
            db.set_setting(c, "rescan.requested", db.now())
    return True
