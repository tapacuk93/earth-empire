"""Reaching Claude (and transcription) through the aicoin proxy with the box's own wallet.

The server wallet is an Ed25519 key generated on the box (`ee wallet init`) and kept only in the
secret earth-empire/claude: {"proxy_url", "model", "wallet_address", "wallet_private_key"}. The
backend mints itself a short-lived API token from it per hour, exactly as the aicoin CLI does
(base64url(payload) "." base64url(sig over the encoded payload)), so no long-lived token exists.

For local tests, EE_AICOIN_TOKEN (e.g. from `aicoin token -days 1`) is used instead of a key.
"""
from __future__ import annotations

import base64
import json
import logging
import os
import threading
import time

from . import config
from .logs import event

DEFAULT_PROXY = "https://proxy.aicoin.oeaio.com"
DEFAULT_MODEL = "claude-sonnet-5-5"
# Routine per-item work (describing, scoring, labels) on the small model; Sonnet only where it reasons
# over everything at once (facets, the rubric). Each purpose can be set: setting ai.model.<purpose>.
CHEAP_MODEL = "claude-haiku-5-5"
SMART_PURPOSES = ("facets", "rubric")


def model_for(c, purpose: str) -> str:
    from .db import setting
    return (setting(c, f"ai.model.{purpose}") or "").strip() or (
        settings()["model"] if purpose in SMART_PURPOSES else CHEAP_MODEL)
TOKEN_LIFETIME = 3600

_lock = threading.Lock()
_token: tuple[float, str] | None = None


class AicoinError(Exception):
    def __init__(self, msg, status=None, body=None):
        super().__init__(msg)
        self.status, self.body = status, body


class OutOfCoins(AicoinError):
    """Nothing to do here but wait: an empty wallet, the app's daily cap, providers out of credit."""


class ProviderOutOfCredit(OutOfCoins):
    """Every provider that could serve the call is out of credit or failing."""


class CapReached(OutOfCoins):
    """The proxy's per-app daily cap (or our own dollar budget) is reached; wait until `reset_at`."""
    def __init__(self, msg, reset_at: str, status=None, body=None):
        super().__init__(msg, status, body)
        self.reset_at = reset_at


APP_ID = "earth-empire"   # sent as X-AICoin-App on every call: the proxy's per-app daily cap counts it


class ProviderOutOfCredit(OutOfCoins):
    """The proxy's own provider account is out of credit: nothing can be done here but wait."""


def _b64(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).decode().rstrip("=")


def settings() -> dict:
    s = config.secret("claude") or {}
    if not isinstance(s, dict):
        s = {}
    return {"proxy_url": (os.environ.get("EE_AICOIN_PROXY") or s.get("proxy_url") or DEFAULT_PROXY).rstrip("/"),
            "model": os.environ.get("EE_CLAUDE_MODEL") or s.get("model") or DEFAULT_MODEL,
            "transcribe_model": s.get("transcribe_model") or "whisper-1",
            "address": s.get("wallet_address"), "key": s.get("wallet_private_key")}


def mint_token(private_hex: str, address: str, lifetime: int = TOKEN_LIFETIME) -> str:
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    key = Ed25519PrivateKey.from_private_bytes(bytes.fromhex(private_hex))
    now = int(time.time())
    payload = _b64(json.dumps({"addr": address, "iat": now, "exp": now + lifetime}, separators=(",", ":")).encode())
    return payload + "." + _b64(key.sign(payload.encode()))


def token() -> str:
    global _token
    env_tok = os.environ.get("EE_AICOIN_TOKEN")
    if env_tok:
        return env_tok.strip()
    with _lock:
        if _token and _token[0] - time.time() > 300:
            return _token[1]
        s = settings()
        if not s["key"] or not s["address"]:
            raise AicoinError("no server wallet: run `ee wallet init` on the box")
        _token = (time.time() + TOKEN_LIFETIME, mint_token(s["key"], s["address"]))
        return _token[1]


def new_wallet() -> tuple[str, str]:
    """(address hex, private key hex) of a fresh Ed25519 key."""
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    from cryptography.hazmat.primitives import serialization as ser
    k = Ed25519PrivateKey.generate()
    priv = k.private_bytes(ser.Encoding.Raw, ser.PrivateFormat.Raw, ser.NoEncryption()).hex()
    pub = k.public_key().public_bytes(ser.Encoding.Raw, ser.PublicFormat.Raw).hex()
    return pub, priv


def balance(address: str | None = None) -> dict:
    import httpx
    s = settings()
    address = address or s["address"]
    r = httpx.get(f"{s['proxy_url']}/wallet/api/reputation/{address}", timeout=20)
    r.raise_for_status()
    return r.json()


PROVIDER_BILLING = ("credit balance is too low", "insufficient_quota", "billing", "exceeded your current quota")


PROVIDER_BILLING = ("credit balance is too low", "insufficient_quota", "exceeded your current quota")


def _reset_at(r) -> str:
    """When a cap resets: the body's reset_at/resets_at, Retry-After, else the next UTC midnight."""
    try:
        d = r.json()
        for k in ("reset_at", "resets_at", "reset", "retry_at"):
            if isinstance(d.get(k), str):
                return d[k]
    except ValueError:
        pass
    ra = r.headers.get("retry-after")
    if ra and ra.isdigit():
        return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() + int(ra)))
    t = time.gmtime(time.time() + 86400)
    return time.strftime("%Y-%m-%dT00:00:00Z", t)


def _hhmm(iso: str) -> str:
    return f"{iso[11:16]} UTC" if iso and len(iso) >= 16 else str(iso)


def _check(r, what: str):
    text = (r.text or "").lower()
    if r.status_code in (402, 403, 429) and "cap" in text and ("daily" in text or "app" in text or "budget" in text):
        reset = _reset_at(r)
        raise CapReached(f"waiting for budget: app cap, resets {_hhmm(reset)}", reset, r.status_code, r.text[:500])
    if r.status_code in (400, 403, 429, 503) and any(p in text for p in PROVIDER_BILLING):
        raise ProviderOutOfCredit(f"waiting for budget: provider credit ({what})", r.status_code, r.text[:500])
    if r.status_code == 402:
        raise OutOfCoins("waiting for budget: wallet empty", 402, r.text[:500])
    if r.status_code >= 400:
        raise AicoinError(f"{what}: HTTP {r.status_code}: {r.text[:500]}", r.status_code, r.text[:2000])


def _state(state: str, reason: str | None = None, **extra):
    """For GET /v1/status: what the AI lanes are doing right now (any process may write it)."""
    try:
        from . import db
        db.set_setting(db.conn(), "ai.state", json.dumps({"state": state, "reason": reason, **extra,
                                                          "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}))
    except Exception:
        pass


def _paused_until() -> str | None:
    try:
        from . import db
        until = db.setting(db.conn(), "ai.paused_until") or ""
        return until if until > time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()) else None
    except Exception:
        return None


def _guard():
    """Our own second limit, in dollars (the proxy's per-app cap is the first)."""
    until = _paused_until()
    if until:
        raise CapReached(f"waiting for budget: app cap, resets {_hhmm(until)}", until)
    try:
        from . import db
        c = db.conn()
        day = time.strftime("%Y-%m-%d", time.gmtime())
        spent = c.execute("SELECT COALESCE(SUM(usd), 0) s FROM costs WHERE at >= ? AND ok=1", (day,)).fetchone()["s"]
        budget = float(db.setting(c, "ai.daily_budget_usd") or 30)
    except Exception:
        return
    if spent >= budget:
        reset = time.strftime("%Y-%m-%dT00:00:00Z", time.gmtime(time.time() + 86400))
        e = CapReached(f"waiting for budget: Earth Empire's own ${budget:.0f}/day, resets {_hhmm(reset)}", reset)
        e.own = True
        raise e


def _pause(e: "CapReached"):
    try:
        from . import db
        db.set_setting(db.conn(), "ai.paused_until", e.reset_at)
    except Exception:
        pass
    _state("waiting", str(e)[:300], resets_at=e.reset_at)


FALLBACKS = [("google", "gemini-3.5-flash"), ("openai", "gpt-5")]
_skip_until: dict[str, float] = {}


def _headers(provider: str) -> dict:
    h = {"X-AI": provider, "X-Api-Key": token(), "X-AICoin-App": APP_ID}
    if provider == "anthropic":
        h["anthropic-version"] = "2023-06-01"
    return h


def _post(path: str, provider: str, payload: dict, timeout: float):
    import httpx
    s = settings()
    for attempt in range(3):
        r = httpx.post(f"{s['proxy_url']}{path}", json=payload, timeout=timeout,
                       headers={**_headers(provider), "content-type": "application/json"})
        text = (r.text or "").lower()
        if r.status_code in (429, 500, 502, 503, 529) and attempt < 2 and "cap" not in text and not any(
                p in text for p in PROVIDER_BILLING):
            wait = 10 * (attempt + 1)
            event("aicoin.retry", logging.WARNING, provider=provider, status=r.status_code, wait=wait, body=r.text[:200])
            time.sleep(wait)
            continue
        _check(r, provider)
        return r.json(), float(r.headers.get("X-Aicoin-Charged") or 0)
    raise AicoinError("unreachable")


def _schema(body):
    return ((body.get("output_config") or {}).get("format") or {}).get("schema")


def _blocks(body):
    for m in body.get("messages") or []:
        content = m.get("content")
        if isinstance(content, str):
            yield {"type": "text", "text": content}
        else:
            yield from content or []


def _system_text(body) -> str:
    s = body.get("system")
    return s if isinstance(s, str) else "\n".join(b.get("text", "") for b in s or [])


def _via_google(body, model, timeout):
    parts = []
    for b in _blocks(body):
        if b.get("type") == "text":
            parts.append({"text": b["text"]})
        elif b.get("type") == "image":
            parts.append({"inline_data": {"mime_type": b["source"]["media_type"], "data": b["source"]["data"]}})
    cfg = {"maxOutputTokens": max(int(body.get("max_tokens") or 8000), 8000), "responseMimeType": "application/json"}
    if _schema(body):
        cfg["responseJsonSchema"] = _schema(body)
    payload = {"contents": [{"role": "user", "parts": parts}], "generationConfig": cfg}
    if _system_text(body):
        payload["systemInstruction"] = {"parts": [{"text": _system_text(body)}]}
    out, coins = _post(f"/v1beta/models/{model}:generateContent", "google", payload, timeout)
    cand = (out.get("candidates") or [{}])[0]
    text = "".join(p.get("text", "") for p in (cand.get("content") or {}).get("parts") or [] if not p.get("thought"))
    u = out.get("usageMetadata") or {}
    return {"content": [{"type": "text", "text": text}], "model": out.get("modelVersion") or model, "provider": "google",
            "stop_reason": "max_tokens" if cand.get("finishReason") == "MAX_TOKENS" else "end_turn",
            "usage": {"input_tokens": u.get("promptTokenCount", 0),
                      "output_tokens": u.get("candidatesTokenCount", 0) + u.get("thoughtsTokenCount", 0)}}, coins


def _via_openai(body, model, timeout):
    parts = []
    for b in _blocks(body):
        if b.get("type") == "text":
            parts.append({"type": "text", "text": b["text"]})
        elif b.get("type") == "image":
            parts.append({"type": "image_url",
                          "image_url": {"url": f"data:{b['source']['media_type']};base64,{b['source']['data']}"}})
    msgs = ([{"role": "system", "content": _system_text(body)}] if _system_text(body) else []) + \
        [{"role": "user", "content": parts}]
    payload = {"model": model, "messages": msgs, "max_completion_tokens": max(int(body.get("max_tokens") or 8000), 8000)}
    if _schema(body):
        payload["response_format"] = {"type": "json_schema",
                                      "json_schema": {"name": "result", "schema": _schema(body), "strict": False}}
    out, coins = _post("/v1/chat/completions", "openai", payload, timeout)
    ch = (out.get("choices") or [{}])[0]
    u = out.get("usage") or {}
    return {"content": [{"type": "text", "text": (ch.get("message") or {}).get("content") or ""}],
            "model": out.get("model") or model, "provider": "openai",
            "stop_reason": "max_tokens" if ch.get("finish_reason") == "length" else "end_turn",
            "usage": {"input_tokens": u.get("prompt_tokens", 0), "output_tokens": u.get("completion_tokens", 0)}}, coins


def _provider_failure(e: Exception) -> bool:
    if isinstance(e, ProviderOutOfCredit):
        return True
    if isinstance(e, OutOfCoins):   # our wallet or a cap: every provider would refuse the same way
        return False
    if isinstance(e, AicoinError):
        return e.status is None or e.status >= 500 or e.status in (429, 529) or "overloaded" in (e.body or "").lower()
    return "timeout" in type(e).__name__.lower()


def claude(body: dict, timeout: float = 300) -> tuple[dict, float]:
    try:
        return _claude(body, timeout)
    except CapReached as e:
        _pause(e) if not getattr(e, "own", False) else None
        _state("waiting", str(e), resets_at=e.reset_at)
        raise


def _claude(body: dict, timeout: float = 300) -> tuple[dict, float]:
    """A structured generation through the aicoin proxy, paid by the server wallet, identified as
    earth-empire: Claude first; when Claude's side fails (out of credit, overloaded, 5xx) Gemini, then
    OpenAI, with the same images and JSON schema. Returns an Anthropic-shaped response with
    "provider"; raises OutOfCoins/CapReached for the lanes to wait on."""
    _guard()
    s = settings()
    body = dict(body)
    body.setdefault("model", s["model"])
    errors = []
    plan = [("anthropic", None)] + FALLBACKS
    for provider, model in plan:
        if _skip_until.get(provider, 0) > time.time():
            errors.append(f"{provider}: skipped (failing recently)")
            continue
        try:
            if provider == "anthropic":
                out, coins = _post("/v1/messages", "anthropic", body, timeout)
                out["provider"] = "anthropic"
            else:
                out, coins = (_via_google if provider == "google" else _via_openai)(body, model, timeout)
            if errors:
                out["fallback_from"] = errors
                event("aicoin.served_by", provider=provider, model=out.get("model"), after=errors)
            _state("ok", None, provider=provider, model=out.get("model"),
                   fallback="; ".join(errors)[:400] if errors else None)
            return out, coins
        except CapReached:
            raise
        except OutOfCoins as e:
            if isinstance(e, ProviderOutOfCredit):
                _skip_until[provider] = time.time() + 900
                errors.append(f"{provider}: {str(e)[:160]}")
                event("aicoin.fallback", logging.WARNING, failed=provider, error=str(e)[:300])
                continue
            _state("waiting", str(e))
            raise
        except Exception as e:
            if not _provider_failure(e):
                raise
            errors.append(f"{provider}: {str(e)[:160]}")
            event("aicoin.fallback", logging.WARNING, failed=provider, error=str(e)[:300])
    _state("waiting", "waiting for budget: provider credit (" + " | ".join(errors)[:240] + ")")
    raise ProviderOutOfCredit("waiting for budget: provider credit")


def transcribe(audio_path: str, timeout: float = 300) -> tuple[dict, float]:
    """OpenAI speech-to-text through the proxy: verbose JSON with timed segments."""
    import httpx
    s = settings()
    with open(audio_path, "rb") as f:
        r = httpx.post(f"{s['proxy_url']}/v1/audio/transcriptions", timeout=timeout,
                       headers=_headers("openai"),
                       data={"model": s["transcribe_model"], "response_format": "verbose_json",
                             "timestamp_granularities[]": "segment"},
                       files={"file": (os.path.basename(audio_path), f, "audio/mpeg")})
    _check(r, "transcribe")
    return r.json(), float(r.headers.get("X-Aicoin-Charged") or 0)
