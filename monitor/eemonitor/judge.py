"""Claude, through the backend's aicoin route (ee.aicoin, the box's own wallet): English translations
of hit excerpts, and a second opinion on borderline name hits. One call per scanned video that has
hits, never per hit; a daily USD cap (claude.daily_usd) stops it, and hits are kept without a
translation then.
"""
from __future__ import annotations

import json
import logging

from . import db

log = logging.getLogger("ee.monitor.judge")
RATES = {"haiku": (1.0, 5.0), "sonnet": (3.0, 15.0), "opus": (5.0, 25.0)}


def _usd(model: str, usage: dict) -> float:
    rate = next((v for k, v in RATES.items() if k in (model or "")), (3.0, 15.0))
    return ((usage.get("input_tokens") or 0) * rate[0] + (usage.get("output_tokens") or 0) * rate[1]) / 1e6


def ask(c, prompt: str, purpose: str, video_id: str | None = None, max_tokens: int = 2000) -> str | None:
    if db.setting(c, "claude.enabled") != "1":
        return None
    spent = db.used(c, "usd.claude")
    if spent >= db.fsetting(c, "claude.daily_usd"):
        log.info("claude: daily cap reached (%.3f USD); skipping %s", spent, purpose)
        return None
    from ee import aicoin
    body = {"max_tokens": max_tokens, "messages": [{"role": "user", "content": prompt}]}
    model = db.setting(c, "claude.model")
    if model:
        body["model"] = model
    try:
        resp, coins = aicoin.claude(body, timeout=120)
    except Exception as e:  # noqa: BLE001
        if model and "model" in str(e).lower():
            body.pop("model")
            resp, coins = aicoin.claude(body, timeout=120)
        else:
            log.warning("claude %s failed: %s", purpose, e)
            return None
    usd = _usd(resp.get("model") or model, resp.get("usage") or {})
    db.add_usage(c, "usd.claude", usd)
    c.execute("INSERT INTO costs(at, purpose, video_id, usd, coins, note) VALUES (?,?,?,?,?,?)",
              (db.now(), purpose, video_id, round(usd, 5), coins, resp.get("model")))
    return "".join(b.get("text", "") for b in resp.get("content") or [] if b.get("type") == "text")


def review(c, video: dict, hits: list[dict]) -> None:
    """Fill each hit's `excerpt_en`, and for borderline name hits Claude's `judge` opinion (in place)."""
    todo = [h for h in hits if h["kind"] == "language" or (h.get("language") or "en") != "en"
            or 0.08 <= h["confidence"] <= 0.75]
    if not todo:
        return
    lines = []
    for i, h in enumerate(todo):
        lines.append(json.dumps({"n": i, "kind": h["kind"], "phrase": h.get("phrase"), "heard": h["matched"],
                                 "language": h.get("language"), "excerpt": h["excerpt"][:700]}, ensure_ascii=False))
    prompt = (
        "These are excerpts from automatic speech recognition of a public video"
        f" (\"{(video.get('title') or '')[:120]}\", {video.get('platform')}, {video.get('url')}).\n"
        "For each line: translate the excerpt into English (keep names as heard). For kind=name, also judge "
        "whether the heard word is plausibly the name/phrase in `phrase` (a person's name, any grammatical form) "
        "rather than a common word or another name: give name_probability 0..1 and a short reason. Recognition "
        "errors are common; do not be certain.\n"
        "Answer only with JSON lines: {\"n\": <n>, \"en\": \"...\", \"name_probability\": <0..1 or null>, "
        "\"reason\": \"...\"}\n\n" + "\n".join(lines))
    text = ask(c, prompt, "review", video.get("id"))
    if not text:
        return
    for line in text.splitlines():
        line = line.strip().strip(",")
        if not line.startswith("{"):
            continue
        try:
            r = json.loads(line)
            h = todo[int(r["n"])]
        except (ValueError, KeyError, IndexError, TypeError):
            continue
        if r.get("en"):
            h["excerpt_en"] = r["en"]
        p = r.get("name_probability")
        if h["kind"] == "name" and isinstance(p, (int, float)):
            h["judge"] = {"by": "claude", "name_probability": round(float(p), 2), "reason": (r.get("reason") or "")[:300]}
            # the context opinion replaces the rule-of-thumb one, never drops the hit
            sc = h["scores"]
            sc["name"] = round(max(0.05, min(0.95, (sc["name"] + 2 * float(p)) / 3)), 3)
            h["confidence"] = round(sc["sound"] * (0.55 + 0.45 * sc["asr"]) * sc["name"], 3)
