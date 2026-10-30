"""Heard: the short phrase actually spoken in a video, the way the owner names highlights
(CONTRACT.md "Heard").

The owner names Instagram highlights after a phrase said in their videos, often abbreviated ("3"
for "у тебе 3"). For each item with a video, Claude reads the item's cached speech transcripts
(timed segments; never transcribed again here) and its highlight titles, and answers with the short
phrase actually spoken that a title stands for - a few words, in the language and spelling as
spoken - with its media, start/end time and a confidence, or null when nothing in the speech
matches. For items in no highlight the phrase is optional: only a clear short phrase about the
owner/subject. Several items go into one call.

Stored as `items.heard` (JSON or NULL) with `items.heard_sig`, a signature of what it was worked
out from (transcripts and highlight membership/titles): a changed signature means work it out
again. The Instagram highlight title is never touched; per highlight, `heard_label` is the most
common heard phrase among its items, with `heard_reason`.
"""
from __future__ import annotations

import hashlib
import json
import logging
import re
import unicodedata

from . import aicoin, store
from .analysis import usd_for
from .db import j, now, setting, tx
from .logs import event

MAX_TRANSCRIPT_CHARS = 3500   # per item in a prompt; the phrase is short, the speech mostly is too
MAX_PROMPT_CHARS = 30000
MAX_TEXT = 80                 # a highlight name, not a sentence
MIN_LABEL_CONFIDENCE = 0.3

SCHEMA = {
    "type": "object", "additionalProperties": False, "required": ["items"],
    "properties": {"items": {"type": "array", "items": {
        "type": "object", "additionalProperties": False,
        "required": ["n", "text", "highlight_id", "media", "start", "end", "confidence"],
        "properties": {
            "n": {"type": "integer"},
            "text": {"type": ["string", "null"]},
            "highlight_id": {"type": ["string", "null"]},
            "media": {"type": ["integer", "null"]},
            "start": {"type": ["number", "null"]},
            "end": {"type": ["number", "null"]},
            "confidence": {"type": "number"}}}}},
}

SYSTEM = """You find the short phrase actually spoken in the owner's Instagram videos that the owner \
names highlights after. The owner names a highlight after a phrase said in its videos, often \
abbreviated: a highlight "3" may stand for "у тебе 3", "в Тараса 3" for "а в Тараса 3".

You also get the phrases the owner's monitor listens for (with their variants). They come first: in \
every item, highlight or not, when one of them is spoken - as written, as a variant, misheard, or in \
wording you judge similar or related in meaning - the text is that moment, made fuller as it is \
actually spoken around it (a few words), and that wins over a highlight title or a description.

For each item you get its highlight titles (id: title) and the automatic transcripts of its videos, \
segment by segment with times in seconds within that media. Answer per item:
- text: the phrase as actually spoken that the highlight title stands for - as short as a highlight \
name, a few words (at most 6), in the original language and spelling as spoken (do not translate, do \
not normalise numbers to digits or words unless spoken that way; the title's own spelling is fine \
where the speech matches it). It is usually the title made fuller from the speech.
- highlight_id: which of the item's highlights it stands for.
- media, start, end: the media number and the segment times where it is said (as given; null when \
the transcript has no times).
- confidence 0..1: how sure you are this is what is said and what the title stands for.
- If nothing in the speech matches a title, text is null. Never invent words that are not in the \
transcript; automatic transcripts have errors, so a close mishearing of the title counts, a guess \
does not.
- Items in no highlight: the reference is the post's description (given as Description). Give the \
words actually spoken that say what the description says - where in the video it sounds - as short \
as a highlight name, with that media, start and end, and highlight_id null. Null when the \
description is not spoken in the video. Songs, lyrics and speech over music are not phrases.
Answer with the JSON the response format asks for, one entry per item number."""


# ------------------------------------------------------------------ inputs
def _videos(d: dict):
    """(media number, media key) for every video, numbered as the analysis numbers media."""
    n = 0
    for items in (d.get("media") or [], (d.get("repost_of") or {}).get("media") or []):
        for m in items:
            if not m.get("url"):
                continue
            if m.get("type") == "video":
                yield n, store.media_key(m["url"]) or m["url"]
            n += 1


def _highlights(c, item_id: str) -> list[dict]:
    return [{"id": r["id"], "title": r["title"] or ""} for r in c.execute(
        "SELECT h.id, h.title FROM item_highlights ih JOIN highlights h ON h.id=ih.highlight_id "
        "WHERE ih.item_id=? ORDER BY h.position, h.id", (item_id,))]


def _speech_fallback(row) -> str:
    """Items analyzed before transcripts were cached: the analysis's own transcript (no times)."""
    try:
        sp = (json.loads(row["analysis"] or "{}").get("speech") or {})
    except ValueError:
        return ""
    return (sp.get("transcript") or "").strip() if isinstance(sp, dict) else ""


def monitor_phrases() -> list[str]:
    """The phrases the monitor listens for, each with a few of its variants ("тарас маслов (taras maslov, …)")."""
    from .home import monitor_conn
    m = monitor_conn()
    if not m:
        return []
    try:
        out = []
        for text, compiled in m.execute("SELECT text, compiled FROM phrases ORDER BY position"):
            try:
                v = [x for x in (json.loads(compiled or "{}").get("variants") or []) if x and x != text][:4]
            except ValueError:
                v = []
            out.append(f"{text} ({', '.join(v)})" if v else text)
        return out
    except Exception:
        return []
    finally:
        m.close()


def description(row) -> str:
    """The post's own description (web: describe): the caption's first line without hashtags or
    mentions, else the first sentence of the item's description."""
    d = json.loads(row["data"])
    for line in (d.get("caption") or "").splitlines():
        line = " ".join(re.sub(r"[#@][\w.]+", "", line).split())
        if line:
            return line
    text = (row["description"] or row["summary"] or "").strip()
    return re.split(r"(?<=[.!?])\s", text, maxsplit=1)[0] if text else ""


def signature(c, row) -> str | None:
    """What the phrase is worked out from; None when the item has no speech to read."""
    d = json.loads(row["data"])
    vids = list(_videos(d))
    if not vids:
        return None
    trs = []
    for n, key in vids:
        t = c.execute("SELECT created_at, LENGTH(text) l FROM transcripts WHERE media=?", (key,)).fetchone()
        if t:
            trs.append([n, key, t["created_at"], t["l"]])
    fb = "" if trs else _speech_fallback(row)
    if not trs and not fb:
        return None
    hls = [[h["id"], h["title"]] for h in _highlights(c, row["id"])]
    desc = "" if hls else description(row)
    phrases = _phrases_cached()
    return hashlib.sha1(j([trs, fb, hls] + ([desc] if desc else []) + ([phrases] if phrases else [])).encode()).hexdigest()[:16]


_phrases = {"at": 0.0, "list": []}


def _phrases_cached() -> list[str]:
    """monitor_phrases(), read again at most once a minute (the queue computes many signatures)."""
    import time
    if time.time() - _phrases["at"] > 60:
        _phrases["list"], _phrases["at"] = monitor_phrases(), time.time()
    return _phrases["list"]


def inputs(c, row) -> dict:
    d = json.loads(row["data"])
    parts = []
    timed = False
    for n, key in _videos(d):
        t = c.execute("SELECT language, text, segments FROM transcripts WHERE media=?", (key,)).fetchone()
        if not t:
            continue
        segs = json.loads(t["segments"] or "[]")
        lines = [f"[{s.get('start', 0):.1f}-{s.get('end', 0):.1f}] {(s.get('text') or '').strip()}" for s in segs
                 if (s.get("text") or "").strip()]
        body = "\n".join(lines) or (t["text"] or "").strip()
        timed = timed or bool(lines)
        parts.append(f"media {n} (language guess {t['language'] or '?'}):\n{body or '(no speech)'}")
    if not parts:
        fb = _speech_fallback(row)
        if fb:
            parts.append(f"(transcript without times, from the item's analysis):\n{fb}")
    text = "\n".join(parts)
    if len(text) > MAX_TRANSCRIPT_CHARS:
        text = text[:MAX_TRANSCRIPT_CHARS] + " …"
    hls = _highlights(c, row["id"])
    return {"id": row["id"], "kind": row["kind"], "highlights": hls, "transcript": text, "timed": timed,
            "description": "" if hls else description(row)}


# ------------------------------------------------------------------ the queue
def pending(c, limit: int = 1000) -> list[str]:
    """Items with a video and speech to read whose phrase was never worked out, or was worked out from
    other transcripts or highlights. Items in highlights first, then public, new, newest."""
    out = []
    for r in c.execute("""SELECT i.*, (SELECT COUNT(*) FROM item_highlights ih WHERE ih.item_id=i.id) nh FROM items i
                          WHERE i.data LIKE '%"type":"video"%'
                          ORDER BY nh > 0 DESC, i.published_at IS NULL, i.priority DESC, i.taken_at DESC"""):
        if owned(r):
            continue
        sig = signature(c, r)
        if sig and sig != r["heard_sig"]:
            out.append(r["id"])
            if len(out) >= limit:
                break
    return out


def counts(c) -> dict:
    """For GET /v1/status: how far the backfill is."""
    with_speech = done = heard = 0
    for r in c.execute("SELECT * FROM items WHERE data LIKE '%\"type\":\"video\"%'"):
        sig = signature(c, r)
        if not sig:
            continue
        with_speech += 1
        if sig == r["heard_sig"]:
            done += 1
            heard += r["heard"] is not None
    return {"with_speech": with_speech, "done": done, "queue": with_speech - done, "heard": heard}


# ------------------------------------------------------------------ one batch
def _num(v):
    return round(float(v), 2) if isinstance(v, (int, float)) and v >= 0 else None


def clean(entry: dict, inp: dict, model: str) -> dict | None:
    text = re.sub(r"\s+", " ", (entry.get("text") or "")).strip().strip("\"'«»“”")
    if not text or len(text) > MAX_TEXT:
        return None
    hl_ids = {h["id"] for h in inp["highlights"]}
    hid = entry.get("highlight_id") if entry.get("highlight_id") in hl_ids else None
    if hid is None and len(hl_ids) == 1:   # in one highlight: the phrase stands for its title
        hid = next(iter(hl_ids))
    conf = entry.get("confidence")
    conf = round(min(1.0, max(0.0, float(conf))), 2) if isinstance(conf, (int, float)) else 0.5
    start, end = (_num(entry.get("start")), _num(entry.get("end"))) if inp["timed"] else (None, None)
    if start is not None and end is not None and end < start:
        start, end = end, start
    media = entry.get("media") if isinstance(entry.get("media"), int) and inp["timed"] else None
    return {"text": text, "highlight_id": hid, "media": media, "start": start, "end": end, "confidence": conf,
            "model": model, "at": now()}


def batch(c, ids: list[str], batch_size: int = 8) -> list[str]:
    """The next items that fit one call."""
    out, size = [], 0
    for i in ids:
        row = c.execute("SELECT * FROM items WHERE id=?", (i,)).fetchone()
        if not row:
            continue
        inp = inputs(c, row)
        n = len(inp["transcript"]) + 200
        if out and (len(out) >= batch_size or size + n > MAX_PROMPT_CHARS):
            break
        out.append(i)
        size += n
    return out


def run_batch(c, ids: list[str]) -> dict:
    """One Claude call for these items; stores each item's phrase (or null) and refreshes their
    highlights' labels. Raises aicoin.OutOfCoins for the lane to wait on."""
    rows = {r["id"]: r for r in c.execute(f"SELECT * FROM items WHERE id IN ({','.join('?' * len(ids))})", ids)}
    ins = [inputs(c, rows[i]) for i in ids if i in rows]
    sigs = {i: signature(c, rows[i]) for i in rows}
    blocks = []
    for n, inp in enumerate(ins):
        hl = "; ".join(f"{h['id']}: {h['title']!r}" for h in inp["highlights"]) or "none"
        desc = f"\nDescription: {inp['description']}" if inp.get("description") else ""
        blocks.append(f"### Item {n} ({inp['kind']})\nHighlights: {hl}{desc}\n{inp['transcript']}")
    phrases = _phrases_cached()
    if phrases:
        blocks.insert(0, "Phrases the monitor listens for:\n" + "\n".join(f"- {p}" for p in phrases))
    body = {"model": aicoin.model_for(c, "heard"), "max_tokens": 400 + 200 * len(ins), "system": SYSTEM,
            "output_config": {"effort": "low", "format": {"type": "json_schema", "schema": SCHEMA}},
            "messages": [{"role": "user", "content": "\n\n".join(blocks)}]}
    model_pref = setting(c, "heard.model")
    if model_pref:
        body["model"] = model_pref
    resp, coins = aicoin.claude(body, timeout=180, purpose="heard")
    usage = resp.get("usage") or {}
    model = resp.get("model") or model_pref or ""
    c.execute("INSERT INTO costs(at, item_id, purpose, model, input_tokens, output_tokens, coins, usd, ok, note) "
              "VALUES (?,?,?,?,?,?,?,?,1,?)", (now(), ins[0]["id"] if len(ins) == 1 else None, "heard", model,
                                              usage.get("input_tokens"), usage.get("output_tokens"), coins,
                                              usd_for(model, usage), f"{len(ins)} items"))
    if resp.get("stop_reason") not in ("end_turn", "stop_sequence", None):
        raise RuntimeError(f"heard answer ended with {resp.get('stop_reason')}")
    out = json.loads("".join(b.get("text", "") for b in resp.get("content") or [] if b.get("type") == "text"))
    answers = {e.get("n"): e for e in out.get("items") or [] if isinstance(e, dict)}
    done, found = [], []
    with tx(c):
        for n, inp in enumerate(ins):
            if n not in answers:
                continue
            h = clean(answers[n], inp, model)
            if owned(c.execute("SELECT heard FROM items WHERE id=?", (inp["id"],)).fetchone()):
                done.append(inp["id"])   # the owner's label stands
                continue
            c.execute("UPDATE items SET heard=?, heard_sig=? WHERE id=?",
                      (j(h) if h else None, sigs[inp["id"]], inp["id"]))
            done.append(inp["id"])
            if h:
                found.append([inp["id"], h["text"]])
        refresh_labels(c, {h["id"] for inp in ins for h in inp["highlights"]})
    res = {"items": len(ins), "answered": len(done), "heard": found, "coins": coins,
           "input_tokens": usage.get("input_tokens"), "output_tokens": usage.get("output_tokens")}
    event("heard.done", **res)
    missing = [inp["id"] for inp in ins if inp["id"] not in done]
    if missing:
        raise PartialAnswer(missing)
    return res


def owned(row) -> bool:
    """The owner set this item's label: the job never changes it."""
    try:
        return bool(row["heard"]) and (json.loads(row["heard"]) or {}).get("by") == "owner"
    except (ValueError, TypeError):
        return False


def set_by_owner(c, item_id: str, text: str | None) -> dict | None:
    """The owner's label for an item (`by: "owner"`, kept over Claude's). Empty text hands it back to the job."""
    row = c.execute("SELECT * FROM items WHERE id=?", (item_id,)).fetchone()
    if not row:
        raise KeyError(item_id)
    text = " ".join((text or "").split())[:MAX_TEXT]
    old = json.loads(row["heard"]) if row["heard"] else {}
    with tx(c):
        if not text:
            c.execute("UPDATE items SET heard=NULL, heard_sig=NULL WHERE id=?", (item_id,))
            h = None
        else:
            hls = _highlights(c, item_id)
            h = {"text": text, "highlight_id": old.get("highlight_id") or (hls[0]["id"] if hls else None),
                 "media": old.get("media"), "start": old.get("start"), "end": old.get("end"),
                 "confidence": 1.0, "by": "owner", "model": None, "at": now()}
            c.execute("UPDATE items SET heard=?, heard_sig=? WHERE id=?", (j(h), signature(c, row), item_id))
        refresh_labels(c, {x["id"] for x in _highlights(c, item_id)})
    event("heard.owner", item=item_id, text=text or None)
    return h


class PartialAnswer(RuntimeError):
    def __init__(self, missing):
        super().__init__(f"no answer for {len(missing)} items")
        self.missing = missing


def give_up(c, ids: list[str]) -> None:
    """Items that failed twice: done for what they are now (no phrase); a new transcript or highlight retries."""
    for i in ids:
        row = c.execute("SELECT * FROM items WHERE id=?", (i,)).fetchone()
        if row:
            c.execute("UPDATE items SET heard_sig=? WHERE id=?", (signature(c, row), i))


# ------------------------------------------------------------------ per highlight
def _norm(s: str) -> str:
    s = unicodedata.normalize("NFKC", s).casefold().replace("’", "'")
    return re.sub(r"\s+", " ", re.sub(r"[^\w' ]+", " ", s)).strip()


def label_for(title: str | None, heards: list[dict], videos: int) -> tuple[str | None, str | None]:
    """The most representative phrase among a highlight's items: the one heard in most of them (ties:
    the surer), spelled as in its surest item."""
    groups: dict[str, list[dict]] = {}
    for h in heards:
        if h.get("text") and (h.get("confidence") or 0) >= MIN_LABEL_CONFIDENCE:
            groups.setdefault(_norm(h["text"]), []).append(h)
    if not groups:
        return None, (f"nothing matching the title heard in its {videos} video{'s' * (videos != 1)} with speech"
                      if videos else None)
    key, members = max(groups.items(), key=lambda kv: (len(kv[1]), sum(h["confidence"] for h in kv[1])))
    best = max(members, key=lambda h: h["confidence"])
    k = len(members)
    why = f"heard in {k} of its {videos} video{'s' * (videos != 1)} with speech"
    if len(groups) > 1:
        why += f", the most common of {len(groups)} phrases"
    if title and _norm(title) != key:
        why += f'; the title "{title}" is short for it'
    return best["text"], why


def refresh_labels(c, highlight_ids=None) -> int:
    """heard_label/heard_reason of these highlights (all when None) from their items' phrases."""
    if highlight_ids is None:
        highlight_ids = [r["id"] for r in c.execute("SELECT id FROM highlights")]
    n = 0
    for hid in highlight_ids:
        hl = c.execute("SELECT id, title, heard_label FROM highlights WHERE id=?", (hid,)).fetchone()
        if not hl:
            continue
        heards, videos = [], 0
        for r in c.execute("SELECT i.* FROM item_highlights ih JOIN items i ON i.id=ih.item_id WHERE ih.highlight_id=?",
                           (hid,)):
            sig = signature(c, r)
            if not sig or sig != r["heard_sig"]:
                continue
            videos += 1
            h = json.loads(r["heard"]) if r["heard"] else None
            if h and h.get("highlight_id") == hid:
                heards.append(h)
        label, why = label_for(hl["title"], heards, videos)
        c.execute("UPDATE highlights SET heard_label=?, heard_reason=?, heard_at=? WHERE id=?",
                  (label, why, now() if videos else None, hid))
        n += label != hl["heard_label"]
    return n


def run(c, limit: int = 1000) -> list[dict]:
    """By hand (ee heard run): work through the queue now."""
    out = []
    ids = pending(c, limit)
    size = int(setting(c, "heard.batch_size") or 8)
    while ids:
        b = batch(c, ids, size)
        try:
            out.append(run_batch(c, b))
        except aicoin.OutOfCoins:
            raise
        except Exception as e:
            event("heard.failed", logging.WARNING, items=b, error=repr(e)[:300])
            give_up(c, getattr(e, "missing", b))
        ids = [i for i in ids if i not in b]
    return out
