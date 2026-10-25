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

import httpx

from . import config
from .logs import event

DEFAULT_PROXY = "https://proxy.aicoin.oeaio.com"
DEFAULT_MODEL = "claude-sonnet-5-5"
TOKEN_LIFETIME = 3600

_lock = threading.Lock()
_token: tuple[float, str] | None = None


class AicoinError(Exception):
    def __init__(self, msg, status=None, body=None):
        super().__init__(msg)
        self.status, self.body = status, body


class OutOfCoins(AicoinError):
    pass


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
    s = settings()
    address = address or s["address"]
    r = httpx.get(f"{s['proxy_url']}/wallet/api/reputation/{address}", timeout=20)
    r.raise_for_status()
    return r.json()


def _check(r: httpx.Response, what: str):
    if r.status_code == 402:
        raise OutOfCoins(f"{what}: the server wallet is out of aicoin", 402, r.text[:500])
    if r.status_code >= 400:
        raise AicoinError(f"{what}: HTTP {r.status_code}: {r.text[:500]}", r.status_code, r.text[:2000])


def claude(body: dict, timeout: float = 300) -> tuple[dict, float]:
    """POST /v1/messages through the proxy. Returns (response JSON, coins charged)."""
    s = settings()
    body = dict(body)
    body.setdefault("model", s["model"])
    for attempt in range(4):
        r = httpx.post(f"{s['proxy_url']}/v1/messages", json=body, timeout=timeout,
                       headers={"X-AI": "anthropic", "X-Api-Key": token(), "anthropic-version": "2023-06-01",
                                "content-type": "application/json"})
        if r.status_code in (429, 500, 502, 503, 529) and attempt < 3:
            wait = 15 * (attempt + 1)
            event("aicoin.retry", logging.WARNING, status=r.status_code, wait=wait, body=r.text[:300])
            time.sleep(wait)
            continue
        _check(r, "claude")
        return r.json(), float(r.headers.get("X-Aicoin-Charged") or 0)
    raise AicoinError("unreachable")


def transcribe(audio_path: str, timeout: float = 300) -> tuple[dict, float]:
    """OpenAI speech-to-text through the proxy: verbose JSON with timed segments."""
    s = settings()
    with open(audio_path, "rb") as f:
        r = httpx.post(f"{s['proxy_url']}/v1/audio/transcriptions", timeout=timeout,
                       headers={"X-AI": "openai", "X-Api-Key": token()},
                       data={"model": s["transcribe_model"], "response_format": "verbose_json",
                             "timestamp_granularities[]": "segment"},
                       files={"file": (os.path.basename(audio_path), f, "audio/mpeg")})
    _check(r, "transcribe")
    return r.json(), float(r.headers.get("X-Aicoin-Charged") or 0)
