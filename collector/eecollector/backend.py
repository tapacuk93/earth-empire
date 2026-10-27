"""The backend's ingest API (CONTRACT.md: /v1/ingest/*), with retries and logging."""

from __future__ import annotations

import logging
import time

import httpx

log = logging.getLogger("ee.backend")


class BackendError(RuntimeError):
    pass


class Backend:
    def __init__(self, api: str, token: str, timeout: float = 120):
        self.api = api.rstrip("/")
        self.http = httpx.Client(timeout=timeout, headers={"Authorization": f"Bearer {token}",
                                                           "User-Agent": "earth-empire-collector"})

    def __repr__(self) -> str:
        return f"<Backend {self.api}>"

    def _call(self, method: str, path: str, **kw) -> dict:
        url = self.api + path
        for attempt in range(4):
            try:
                r = self.http.request(method, url, **kw)
            except httpx.HTTPError as e:
                log.warning("backend %s %s failed: %s (attempt %d)", method, path, e, attempt + 1)
                time.sleep(5 * (attempt + 1))
                continue
            if r.status_code >= 500 or r.status_code == 429:
                log.warning("backend %s %s -> %d %s (attempt %d)", method, path, r.status_code, r.text[:300], attempt + 1)
                time.sleep(5 * (attempt + 1))
                continue
            if r.status_code >= 400:
                raise BackendError(f"{method} {path} -> {r.status_code}: {r.text[:500]}")
            return r.json() if r.content else {}
        raise BackendError(f"{method} {path} failed after retries")

    def upload(self, key: str, data: bytes, content_type: str) -> str:
        """Presigned upload; returns the public media.empire.earth URL."""
        p = self._call("POST", "/v1/ingest/media-url", json={"key": key, "content_type": content_type})
        for attempt in range(4):
            try:
                r = httpx.put(p["upload_url"], content=data, headers={"Content-Type": content_type}, timeout=600)
                if r.status_code < 300:
                    return p["public_url"]
                log.warning("upload %s -> %d %s", key, r.status_code, r.text[:300])
            except httpx.HTTPError as e:
                log.warning("upload %s failed: %s", key, e)
            time.sleep(5 * (attempt + 1))
        raise BackendError(f"upload of {key} failed")

    def put_items(self, items: list[dict]) -> dict:
        return self._call("PUT", "/v1/ingest/items", json={"items": items})

    def post_deleted(self, deleted: list[str], restored: list[str]) -> dict:
        return self._call("POST", "/v1/ingest/deleted", json={"deleted": deleted, "restored": restored})

    def put_highlights(self, highlights: list[dict]) -> dict:
        return self._call("PUT", "/v1/ingest/highlights", json={"highlights": highlights})

    def put_profile(self, profile: dict) -> dict:
        return self._call("PUT", "/v1/ingest/profile", json=profile)

    def heartbeat(self, ok: bool = True, detail: dict | None = None, jobs: list | None = None,
                  event: str | None = None, kind: str | None = None, error: str | None = None) -> None:
        """CONTRACT.md heartbeat for /v1/status. Best effort: a failed heartbeat never stops a run."""
        body: dict = {"component": "collector", "ok": ok, "detail": detail or {}}
        if jobs is not None:
            body["jobs"] = jobs
        if event:
            body["event"], body["kind"] = event, kind or "event"
        if error:
            body["error"] = error
        try:
            r = self.http.post(self.api + "/v1/ingest/heartbeat", json=body, timeout=15)
            if r.status_code >= 400:
                log.warning("heartbeat -> %d %s", r.status_code, r.text[:200])
        except httpx.HTTPError as e:
            log.warning("heartbeat failed: %s", e)

    def post_run(self, run: dict) -> dict:
        return self._call("POST", "/v1/ingest/runs", json=run)
