"""A local stand-in for the backend's ingest API (CONTRACT.md), for tests and dry runs.

    python tests/mock_backend.py --port 8787 --dir /tmp/ee-mock --token test

Presigned uploads go to this server too (PUT /upload/<key>) and land in --dir.
"""

from __future__ import annotations

import argparse
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


class Store:
    def __init__(self, root: Path, token: str):
        self.root, self.token = root, token
        self.items: dict[str, dict] = {}
        self.highlights: dict[str, dict] = {}
        self.highlight_order: list[str] = []
        self.profile: dict | None = None
        self.runs: list[dict] = []
        self.uploads: dict[str, tuple[str, int]] = {}
        self.calls: list[str] = []
        self.heartbeats: list[dict] = []


def make_handler(store: Store, base: str):
    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def _json(self, code: int, obj) -> None:
            body = json.dumps(obj).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _body(self) -> bytes:
            return self.rfile.read(int(self.headers.get("Content-Length") or 0))

        def _auth(self) -> bool:
            if self.headers.get("Authorization") != f"Bearer {store.token}":
                self._json(401, {"error": "unauthorized"})
                return False
            return True

        def do_GET(self):
            if self.path == "/v1/profile":
                return self._json(200, store.profile or {})
            if self.path.startswith("/v1/items"):
                return self._json(200, {"items": sorted(store.items.values(), key=lambda i: i["taken_at"] or "", reverse=True), "next": None})
            if self.path == "/v1/highlights":
                return self._json(200, {"highlights": [store.highlights[h] for h in store.highlight_order]})
            self._json(404, {"error": "not found"})

        def do_POST(self):
            store.calls.append("POST " + self.path)
            if not self._auth():
                return
            data = json.loads(self._body() or b"{}")
            if self.path == "/v1/ingest/media-url":
                key = data["key"]
                assert key.startswith(("items/", "highlights/", "profile/")), key
                return self._json(200, {"upload_url": f"{base}/upload/{key}",
                                        "public_url": f"https://media.empire.earth/{key}"})
            if self.path == "/v1/ingest/heartbeat":
                assert data.get("component") == "collector"
                store.heartbeats.append(data)
                return self._json(200, {"ok": True})
            if self.path == "/v1/ingest/runs":
                for k in ("started_at", "finished_at", "ok", "counts"):
                    assert k in data, k
                store.runs.append(data)
                return self._json(200, {"ok": True})
            self._json(404, {"error": "not found"})

        def do_PUT(self):
            store.calls.append("PUT " + self.path.split("?")[0])
            if self.path.startswith("/upload/"):
                key = self.path[len("/upload/"):]
                data = self._body()
                p = store.root / key
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_bytes(data)
                store.uploads[key] = (self.headers.get("Content-Type"), len(data))
                return self._json(200, {})
            if not self._auth():
                return
            data = json.loads(self._body() or b"{}")
            if self.path == "/v1/ingest/items":
                for it in data["items"]:
                    assert "categories" not in it and "summary" not in it
                    store.items[it["id"]] = it
                return self._json(200, {"upserted": len(data["items"])})
            if self.path == "/v1/ingest/highlights":
                for h in data["highlights"]:
                    store.highlights[h["id"]] = h
                store.highlight_order = [h["id"] for h in data["highlights"]]
                return self._json(200, {"upserted": len(data["highlights"])})
            if self.path == "/v1/ingest/profile":
                store.profile = data
                return self._json(200, {"ok": True})
            self._json(404, {"error": "not found"})
    return H


def serve(root: Path, token: str, port: int = 0) -> tuple[ThreadingHTTPServer, Store, str]:
    store = Store(root, token)
    srv = ThreadingHTTPServer(("127.0.0.1", port), None)  # type: ignore[arg-type]
    base = f"http://127.0.0.1:{srv.server_address[1]}"
    srv.RequestHandlerClass = make_handler(store, base)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, store, base


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8787)
    ap.add_argument("--dir", default="/tmp/ee-mock")
    ap.add_argument("--token", default="test")
    a = ap.parse_args()
    srv, store, base = serve(Path(a.dir), a.token, a.port)
    print(f"mock backend at {base}; uploads in {a.dir}")
    try:
        threading.Event().wait()
    except KeyboardInterrupt:
        srv.shutdown()
