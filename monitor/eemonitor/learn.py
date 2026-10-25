"""The self-improvement loop: the mirror of tapacuk93's Instagram is ground truth.

Every mirrored video - the owner's own video posts and the originals of the owner's reposts, both
already re-hosted on media.empire.earth by the collector - is scanned with the same detectors
(source_kind `mirror` / `reposted`). When it has a hit, the monitor asks: had it found that video
on its own first (a hit on the same video reached as official / followed / recommended, earlier)?
Matched by platform id or shortcode, by the original's author and date, or by an audio
fingerprint (the transcript's word shingles). If not, it records a **miss** with its cause and
applies the safe fix within bounds; anything beyond the bounds, or costly, becomes a suggestion
for the owner. Every change is logged in `improvements` with its reason.

Causes: source_not_in_registry, not_scanned_yet, not_reached, download_failed,
transcription_missed, below_threshold, variant_missing, language_id_wrong.
"""
from __future__ import annotations

import json
import logging
import re

from . import db, detect, registry

log = logging.getLogger("ee.monitor.learn")
MIRROR_KINDS = ("mirror", "reposted")
INDEPENDENT = ("official", "followed", "reposted_author", "recommended")
BOUNDS = {"name.min_confidence": (0.01, 0.1), "language.min_prob": (0.25, 0.5), "language.min_seconds": (2.0, 5.0)}
MAX_LEARNED_VARIANTS = 30
MAX_BIG_MODEL_SOURCES = 5


def improve(c, cause: str, change: str, reason: str, applied: bool, **detail) -> None:
    c.execute("INSERT INTO improvements(at, cause, change, reason, applied, detail) VALUES (?,?,?,?,?,?)",
              (db.now(), cause, change, reason, int(applied), db.j(detail)))
    log.info(json.dumps({"event": "monitor.improvement", "cause": cause, "change": change, "reason": reason,
                         "applied": applied}, ensure_ascii=False))


def shingles(tr: dict, n: int = 4) -> set[str]:
    words = [detect.clean(w[0]) for ch in tr.get("chunks", []) for w in ch.get("words") or []]
    words = [w for w in words if w]
    return {" ".join(words[i:i + n]) for i in range(max(0, len(words) - n + 1))}


def similar(a: set, b: set) -> float:
    return len(a & b) / len(a | b) if a and b else 0.0


def find_independent(c, mv, tr: dict):
    """The same video reached on its own: by id/shortcode, by author + date, or by audio fingerprint."""
    ex = json.loads(mv["extra"] or "{}")
    pk, code, author = ex.get("pk"), ex.get("code"), ex.get("author")
    kinds = ",".join("'%s'" % k for k in INDEPENDENT)
    if pk:
        r = c.execute(f"SELECT * FROM videos WHERE id IN (?, ?, ?) AND source_kind IN ({kinds})",
                      (f"ig:{pk}", f"tt:{pk}", f"fb:{pk}")).fetchone()
        if r:
            return r, "platform id"
    if code:
        r = c.execute(f"SELECT * FROM videos WHERE source_kind IN ({kinds}) AND (url LIKE ? OR json_extract(extra,'$.code')=?)",
                      (f"%/{code}/%", code)).fetchone()
        if r:
            return r, "shortcode"
    if author and mv["posted_at"]:
        r = c.execute(f"""SELECT v.* FROM videos v JOIN accounts a ON a.id=v.account_id WHERE a.handle=? AND
                         v.source_kind IN ({kinds}) AND v.posted_at=?""", (author, mv["posted_at"])).fetchone()
        if r:
            return r, "author and date"
    mine = shingles(tr)
    if len(mine) >= 5:
        dur = mv["duration"] or tr.get("duration") or 0
        for r in c.execute(f"""SELECT * FROM videos WHERE state='done' AND transcript IS NOT NULL
                               AND source_kind IN ({kinds}) AND ABS(COALESCE(audio_s, 0) - ?) < 5""", (dur,)):
            from .worker import load_transcript
            if similar(mine, shingles(load_transcript(r["transcript"]))) >= 0.5:
                return r, "audio fingerprint (transcript)"
    return None, None


def evaluate(c, mv, hits: list[dict], tr: dict) -> dict:
    """After a mirrored video was scanned: found first, or a miss with its cause and the fix."""
    matched = bool(hits)
    out = {"matched": matched, "found_first": False, "misses": []}
    if not matched:
        c.execute("INSERT OR REPLACE INTO mirror_checks(video_id, item_id, at, matched) VALUES (?,?,?,0)",
                  (mv["id"], mv["via"], db.now()))
        return out
    learn_variants(c, hits)
    iv, how = find_independent(c, mv, tr)
    ihits = []
    if iv:
        ihits = c.execute("SELECT * FROM hits WHERE video_id=? AND found_at <= ?", (iv["id"], mv["discovered_at"])).fetchall()
    found_first = bool(ihits) and any(json.loads(h["data"]).get("kind") in {x["kind"] for x in hits} for h in ihits)
    out["found_first"] = found_first
    c.execute("INSERT OR REPLACE INTO mirror_checks(video_id, item_id, at, matched, found_first, independent_video, detail) "
              "VALUES (?,?,?,?,?,?,?)", (mv["id"], mv["via"], db.now(), 1, int(found_first),
                                          iv["id"] if iv else None, db.j({"matched_by": how})))
    if found_first:
        return out
    for h in sorted(hits, key=lambda h: -h["confidence"])[:3]:
        cause, detail = diagnose(c, mv, iv, h, tr)
        c.execute("INSERT INTO misses(at, video_id, item_id, kind, phrase, cause, detail) VALUES (?,?,?,?,?,?,?)",
                  (db.now(), mv["id"], mv["via"], h["kind"], h.get("phrase") or h.get("language"), cause, db.j(detail)))
        fix(c, cause, mv, iv, h, detail)
        out["misses"].append(cause)
    return out


def diagnose(c, mv, iv, h: dict, tr: dict) -> tuple[str, dict]:
    ex = json.loads(mv["extra"] or "{}")
    author = ex.get("author")
    d = {"hit": {k: h.get(k) for k in ("kind", "phrase", "matched", "confidence", "start")}, "author": author}
    if not iv:
        acc = c.execute("SELECT * FROM accounts WHERE handle=? AND platform=?", (author, mv["platform"])).fetchone() \
            if author else None
        if not acc or acc["source_id"] and c.execute("SELECT origin FROM sources WHERE id=?", (acc["source_id"],)).fetchone()["origin"] == "repost":
            # only known through this very repost: it was not in the registry before
            return "source_not_in_registry", d
        d["account"] = acc["handle"]
        return "not_reached", d
    d["independent_video"] = iv["id"]
    if iv["state"] in ("failed", "blocked"):
        d["error"] = iv["error"]
        return "download_failed", d
    if iv["state"] in ("new", "queued", "running", "skipped"):
        d["state"] = iv["state"]
        return "not_scanned_yet", d
    from .worker import detect_all, load_transcript
    itr = load_transcript(iv["transcript"]) or {}
    if h["kind"] == "name":
        raw = detect.find_name(itr, 0.0, [json.loads(r["compiled"]) for r in c.execute("SELECT compiled FROM phrases")])
        near = [x for x in raw if abs(x["start"] - h["start"]) < 3 or x["matched"].lower() == h["matched"].lower()]
        if near:
            best = max(near, key=lambda x: x["confidence"])
            d["independent_confidence"] = best["confidence"]
            d["independent_matched"] = best["matched"]
            if best["scores"]["sound"] < 0.9:   # it matched only fuzzily: as a variant it would be a form
                return "variant_missing", d
            return "below_threshold", d
        words = {detect.clean(w[0]) for ch in itr.get("chunks", []) for w in ch.get("words") or []}
        if detect.clean(h["matched"].split()[0]) in words:
            return "variant_missing", d
        d["independent_excerpt"] = " ".join(ch.get("text", "") for ch in itr.get("chunks", []))[:300]
        return "transcription_missed", d
    ilangs = json.loads(iv["languages"] or "{}")
    d["independent_languages"] = ilangs
    if h["language"] not in ilangs:
        return "language_id_wrong", d
    lh = [x for x in detect_all(c, iv, itr) if x["kind"] == "language"]
    return ("below_threshold" if not lh else "language_id_wrong"), d


def _bounded(c, key: str, target: float, cause: str, reason: str):
    lo, hi = BOUNDS[key]
    cur = db.fsetting(c, key)
    new = min(hi, max(lo, target))
    if abs(new - cur) < 1e-9:
        if target < lo or target > hi:
            improve(c, cause, f"set {key} to {target:.3f}", reason + f" (beyond the bounds {lo}-{hi}; owner's call)", False)
        return
    db.set_setting(c, key, f"{new:.3f}")
    improve(c, cause, f"{key}: {cur:.3f} -> {new:.3f}", reason, True)


def fix(c, cause: str, mv, iv, h: dict, d: dict) -> None:
    ex = json.loads(mv["extra"] or "{}")
    author = ex.get("author")
    if cause in ("source_not_in_registry", "not_reached") and author:
        sid = "ig_" + registry.slug(author)
        registry.upsert_source(c, sid, ex.get("author_name") or author, "reposted_author", "mirror_miss")
        aid = registry.upsert_account(c, sid, mv["platform"], author, ex.get("author_id"))
        c.execute("UPDATE accounts SET priority=MIN(priority+1, 3), next_poll_at=?, backfill_done=0 WHERE id=?",
                  (db.now(), aid))
        c.execute("UPDATE videos SET expanded=0 WHERE id=?", (mv["id"],))   # seed recommendations from it
        improve(c, cause, f"source @{author} added/raised (priority), polled now, its video seeds recommendations",
                f"the owner's mirror had a {h['kind']} hit ({h['matched']!r}) the monitor had not found", True,
                video=mv["id"])
    elif cause == "not_scanned_yet" and iv:
        c.execute("UPDATE videos SET state='queued', requested=1, priority=10 WHERE id=? AND state IN ('new','skipped')",
                  (iv["id"],))
        if iv["account_id"]:
            c.execute("UPDATE accounts SET priority=MIN(priority+1, 3) WHERE id=?", (iv["account_id"],))
        improve(c, cause, f"queued {iv['id']} first and raised its account's priority",
                "a mirrored video had a hit while the monitor's copy waited in the queue", True)
    elif cause == "below_threshold":
        conf = d.get("independent_confidence")
        if h["kind"] == "name" and conf is not None:
            _bounded(c, "name.min_confidence", conf * 0.9, cause,
                     f"the monitor's own copy scored {conf:.3f}, under name.min_confidence")
        elif h["kind"] == "language":
            _bounded(c, "language.min_prob", db.fsetting(c, "language.min_prob") - 0.05, cause,
                     "the monitor's own copy was not flagged as uk/ru")
    elif cause == "variant_missing":
        word = (d.get("independent_matched") or h["matched"]).split()[0]
        added = add_variant(c, h.get("phrase"), word)
        h = {**h, "matched": word}
        improve(c, cause, f"variant {h['matched'].split()[0]!r} added to {h.get('phrase')!r}" if added else
                f"add variant {h['matched'].split()[0]!r} to {h.get('phrase')!r}",
                "the word was in the monitor's own transcript but did not match", added)
    elif cause == "transcription_missed" and iv and iv["source_id"]:
        key = f"whisper.model.source.{iv['source_id']}"
        n_big = c.execute("SELECT COUNT(*) n FROM settings WHERE key LIKE 'whisper.model.source.%'").fetchone()["n"]
        if n_big < MAX_BIG_MODEL_SOURCES and not db.setting(c, key):
            db.set_setting(c, key, "medium")
            improve(c, cause, f"{key} = medium", "the monitor's transcript of this source missed the words "
                    "a scan of the mirror heard (medium is ~3x the CPU of small)", True)
        else:
            improve(c, cause, f"use a bigger Whisper model for {iv['source_id']} (or everywhere)",
                    f"transcription missed it; {MAX_BIG_MODEL_SOURCES} sources already use medium", False)
    elif cause == "language_id_wrong":
        _bounded(c, "language.min_seconds", db.fsetting(c, "language.min_seconds") - 0.5, cause,
                 "language ID disagreed between the monitor's copy and the mirror")
    elif cause == "download_failed":
        improve(c, cause, f"give the monitor access to {iv['platform'] if iv else '?'} videos like {iv['id'] if iv else '?'}",
                f"download failed: {(d.get('error') or '')[:200]}", False)


def add_variant(c, phrase: str | None, word: str) -> bool:
    """A word that matched only fuzzily on a mirrored item becomes a learned variant (bounded)."""
    from . import phrases as ph
    if not phrase:
        return False
    w = re.sub(r"[^\w'’-]+", "", word.lower())
    if not w or detect.clean(w) in detect.LOOKALIKES:
        return False
    r = c.execute("SELECT * FROM phrases WHERE text=?", (phrase,)).fetchone()
    if not r:
        return False
    extra = json.loads(r["claude_variants"])
    if w in extra or len(extra) >= MAX_LEARNED_VARIANTS:
        return False
    if len(phrase.split()) > 1:
        return False   # one word of a multi-word phrase: the single-word phrase learns it
    extra.append(w)
    c.execute("UPDATE phrases SET claude_variants=?, compiled=?, updated_at=? WHERE text=?",
              (db.j(extra), db.j(ph.variants(phrase, extra)), db.now(), phrase))
    return True


def learn_variants(c, hits: list[dict]) -> None:
    for h in hits:
        if h["kind"] != "name" or h["confidence"] < 0.3 or len(h["matched"].split()) != 1:
            continue
        if h["scores"]["sound"] < 0.9 and add_variant(c, h.get("phrase"), h["matched"]):
            improve(c, "variant_missing", f"variant {h['matched']!r} added to {h['phrase']!r}",
                    "it matched only fuzzily on a mirrored item (ground truth)", True)


def report(c) -> dict:
    by_cause = {r["cause"]: r["n"] for r in c.execute("SELECT cause, COUNT(*) n FROM misses GROUP BY cause ORDER BY n DESC")}
    days = [dict(r) for r in c.execute("""SELECT substr(at,1,10) day, SUM(matched) matched, SUM(found_first) found_first
                                          FROM mirror_checks GROUP BY day ORDER BY day DESC LIMIT 30""")]
    for d in days:
        d["recall"] = round(d["found_first"] / d["matched"], 3) if d["matched"] else None
    tot = c.execute("SELECT COUNT(*) n, SUM(matched) m, SUM(found_first) f FROM mirror_checks").fetchone()
    return {
        "checked": tot["n"], "matched": tot["m"] or 0, "found_first": tot["f"] or 0,
        "recall": round((tot["f"] or 0) / tot["m"], 3) if tot["m"] else None,
        "misses_by_cause": by_cause, "recall_by_day": days,
        "improvements": [dict(r) | {"detail": json.loads(r["detail"])} for r in
                         c.execute("SELECT * FROM improvements ORDER BY id DESC LIMIT 50")],
        "misses": [dict(r) | {"detail": json.loads(r["detail"])} for r in
                   c.execute("SELECT * FROM misses ORDER BY id DESC LIMIT 50")],
    }
