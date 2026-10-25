"""Claude through the Anthropic API directly, and speech-to-text on the box (CONTRACT.md "AI").

- Key: the secret earth-empire/claude, {"anthropic_api_key": "sk-ant-…", "model"?: "claude-sonnet-5-5"}.
  Until it exists every AI lane waits ("waiting for Anthropic API key" in GET /v1/status), and it is
  picked up within a minute of being added.
- Cost guard in dollars: at most `ai.daily_budget_usd` a day, from the API's own usage numbers.
- The system prompt is sent with prompt caching.
- Speech: faster-whisper (MIT, open source) on the box, no paid API.
"""
from __future__ import annotations

import json
import logging
import os
import threading
import time
from datetime import datetime, timezone

from . import config
from .logs import event

API = "https://api.anthropic.com/v1/messages"
DEFAULT_MODEL = "claude-sonnet-5-5"
KEY_TTL_FOUND, KEY_TTL_MISSING = 300, 30

# USD per million tokens (input, output) - Anthropic's list prices; most specific prefix first.
RATES = [("claude-sonnet-5-5", (2.0, 10.0)), ("claude-sonnet-5", (2.0, 10.0)), ("claude-opus-5-5", (4.0, 20.0)),
         ("claude-opus", (5.0, 25.0)), ("claude-haiku-5-5", (0.10, 0.50)), ("claude-haiku", (1.0, 5.0)),
         ("claude-sonnet", (3.0, 15.0))]


class LLMError(Exception):
    def __init__(self, msg, status=None, body=None):
        super().__init__(msg)
        self.status, self.body = status, body


class AIUnavailable(LLMError):
    """Nothing to do but wait: no key, a rejected key, no credit, or today's budget is spent."""


class NoApiKey(AIUnavailable):
    pass


class ProviderOutOfCredit(AIUnavailable):
    pass


# the names the rest of the code (and the monitor) has used
AicoinError, OutOfCoins = LLMError, AIUnavailable

_lock = threading.Lock()
_key: tuple[float, str | None] = (0.0, None)


def usd_for(model: str, usage: dict) -> float:
    rin, rout = next((v for k, v in RATES if (model or "").startswith(k)), (3.0, 15.0))
    tin = usage.get("input_tokens", 0) + 1.25 * usage.get("cache_creation_input_tokens", 0) \
        + 0.1 * usage.get("cache_read_input_tokens", 0)
    return (tin * rin + usage.get("output_tokens", 0) * rout) / 1e6


def secret() -> dict:
    s = config.secret("claude", fresh=True)
    return s if isinstance(s, dict) else {}


def api_key() -> str | None:
    global _key
    env = os.environ.get("EE_ANTHROPIC_API_KEY")
    if env:
        return env
    with _lock:
        at, k = _key
        if time.time() - at < (KEY_TTL_FOUND if k else KEY_TTL_MISSING):
            return k
        k = (secret().get("anthropic_api_key") or "").strip() or None
        _key = (time.time(), k)
        return k


def settings() -> dict:
    s = secret() if not os.environ.get("EE_ANTHROPIC_API_KEY") else {}
    return {"model": os.environ.get("EE_CLAUDE_MODEL") or s.get("model") or DEFAULT_MODEL}


def _state(state: str, reason: str | None = None):
    """For GET /v1/status: what the AI lanes are doing about Claude right now."""
    try:
        from . import db
        db.set_setting(db.conn(), "ai.state", json.dumps({"state": state, "reason": reason,
                                                          "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}))
    except Exception:
        pass


def spent_today() -> float:
    from . import db
    day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    r = db.conn().execute("SELECT COALESCE(SUM(usd), 0) s FROM costs WHERE at >= ? AND ok=1", (day,)).fetchone()
    return float(r["s"] or 0)


def budget() -> float:
    from . import db
    return float(db.setting(db.conn(), "ai.daily_budget_usd") or 10)


def claude(body: dict, timeout: float = 300) -> tuple[dict, float]:
    """POST /v1/messages. Returns (response, 0.0) - the second value was aicoin coins and stays 0."""
    import httpx
    key = api_key()
    if not key:
        _state("waiting", "waiting for Anthropic API key (earth-empire/claude)")
        raise NoApiKey("waiting for Anthropic API key: put {\"anthropic_api_key\": \"sk-ant-…\"} in earth-empire/claude")
    if spent_today() >= budget():
        _state("waiting", f"daily AI budget of ${budget():.2f} reached")
        raise AIUnavailable(f"the daily AI budget (${budget():.2f}) is spent; continuing tomorrow")
    body = dict(body)
    body.setdefault("model", settings()["model"])
    if isinstance(body.get("system"), str) and body["system"]:
        body["system"] = [{"type": "text", "text": body["system"], "cache_control": {"type": "ephemeral"}}]
    headers = {"x-api-key": key, "anthropic-version": "2023-06-01", "content-type": "application/json"}
    for attempt in range(4):
        r = httpx.post(API, json=body, timeout=timeout, headers=headers)
        text = r.text or ""
        if r.status_code == 401:
            _state("error", "Anthropic API key rejected (401): check earth-empire/claude")
            global _key
            _key = (time.time(), None)   # read the secret again soon
            raise AIUnavailable(f"Anthropic API key rejected (401): {text[:200]}", 401, text[:500])
        if r.status_code in (400, 403) and ("credit balance" in text.lower() or "billing" in text.lower()):
            _state("error", "the Anthropic account is out of credit")
            raise ProviderOutOfCredit(f"Anthropic account out of credit: {text[:200]}", r.status_code, text[:500])
        if r.status_code in (429, 500, 502, 503, 529) and attempt < 3:
            wait = int(r.headers.get("retry-after") or 0) or 15 * (attempt + 1)
            event("claude.retry", logging.WARNING, status=r.status_code, wait=wait, body=text[:200])
            time.sleep(min(wait, 120))
            continue
        if r.status_code >= 400:
            raise LLMError(f"claude: HTTP {r.status_code}: {text[:500]}", r.status_code, text[:2000])
        out = r.json()
        out["provider"] = "anthropic"
        _state("ok")
        return out, 0.0
    raise LLMError("claude: retries exhausted")


# ------------------------------------------------------------------ speech, on the box
_whisper = None


def transcribe(audio_path: str, timeout: float = 600) -> tuple[dict, float]:
    """faster-whisper (small, int8) on the box: {"language", "text", "segments": [{"start","end","text"}]}."""
    global _whisper
    with _lock:
        if _whisper is None:
            from faster_whisper import WhisperModel
            models = config.DATA_DIR / "models"
            models.mkdir(parents=True, exist_ok=True)
            _whisper = WhisperModel(os.environ.get("EE_WHISPER_MODEL", "small"), device="cpu", compute_type="int8",
                                    download_root=str(models), cpu_threads=2)
    segs, info = _whisper.transcribe(audio_path, beam_size=1, vad_filter=True)
    segs = [{"start": round(s.start, 2), "end": round(s.end, 2), "text": s.text.strip()} for s in segs]
    return {"language": info.language, "text": " ".join(s["text"] for s in segs), "segments": segs}, 0.0
