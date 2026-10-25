"""The HTTP API (CONTRACT.md "The API"). Run: uvicorn ee.api:app --port 8000"""
from __future__ import annotations

import hmac
import json
import logging
import re
import time
import uuid

from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from . import config, db, status as status_mod, store
from .logs import event, metric, setup

setup("api")
app = FastAPI(title="Earth Empire API", version="1", docs_url="/v1/docs", openapi_url="/v1/openapi.json",
              redoc_url=None)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["GET", "HEAD", "OPTIONS", "POST", "PUT", "DELETE"],
                   allow_headers=["*"], max_age=86400)

STARTED = time.time()
log = logging.getLogger("ee.api")


@app.middleware("http")
async def access_log(request: Request, call_next):
    t0 = time.time()
    rid = uuid.uuid4().hex[:12]
    try:
        resp = await call_next(request)
    except Exception as e:
        event("api.error", logging.ERROR, rid=rid, method=request.method, path=request.url.path, error=repr(e))
        metric("ApiErrors")
        return JSONResponse({"error": "internal error", "request_id": rid}, status_code=500)
    ms = int((time.time() - t0) * 1000)
    if resp.status_code >= 400 or request.url.path.startswith("/v1/ingest"):
        event("api.request", logging.WARNING if resp.status_code >= 500 else logging.INFO, rid=rid,
              method=request.method, path=request.url.path, status=resp.status_code, ms=ms)
    if request.method == "GET" and resp.status_code == 200 and not request.url.path.startswith("/v1/admin"):
        resp.headers.setdefault("Cache-Control", "public, max-age=30")
    return resp


def conn():
    return db.conn()


def _bearer_matches(request: Request, *keys: str) -> bool:
    auth = request.headers.get("authorization", "")
    if not auth.startswith("Bearer "):
        return False
    given = auth[7:].strip().encode()
    ok = False
    for k in keys:
        token = config.secret(k)
        if token and not config.is_placeholder(token) and hmac.compare_digest(given, str(token).encode()):
            ok = True
    return ok


def require_token(request: Request):
    """The collector's ingest token."""
    if not _bearer_matches(request, "ingest_token"):
        event("api.unauthorized", logging.WARNING, path=request.url.path)
        raise HTTPException(401, "bad or missing bearer token")


def require_admin(request: Request):
    """The owner: earth-empire/admin-token, entered once in the apps."""
    if not _bearer_matches(request, "admin_token"):
        event("api.unauthorized", logging.WARNING, path=request.url.path, admin=True)
        raise HTTPException(401, "bad or missing admin token")


def require_admin_or_ingest(request: Request):
    if not _bearer_matches(request, "admin_token", "ingest_token"):
        event("api.unauthorized", logging.WARNING, path=request.url.path)
        raise HTTPException(401, "bad or missing bearer token")


# ------------------------------------------------------------------ public
@app.get("/v1/health")
def health():
    c = conn()
    last = c.execute("SELECT finished_at, ok, received_at FROM runs ORDER BY id DESC LIMIT 1").fetchone()
    last_ok = c.execute("SELECT received_at FROM runs WHERE ok=1 ORDER BY id DESC LIMIT 1").fetchone()
    steps = {r["step"] + "." + r["state"]: r["n"] for r in
             c.execute("SELECT step, state, COUNT(*) n FROM steps GROUP BY step, state")}
    items = c.execute("SELECT COUNT(*) n, SUM(published_at IS NOT NULL) p FROM items").fetchone()
    stale = None
    if last_ok:
        from datetime import datetime, timezone
        age = (datetime.now(timezone.utc) - datetime.strptime(last_ok["received_at"], "%Y-%m-%dT%H:%M:%SZ")
               .replace(tzinfo=timezone.utc)).total_seconds()
        stale = age > 3 * 3600
    return {
        "ok": True,
        "uptime_s": int(time.time() - STARTED),
        "items": items["n"], "published": items["p"] or 0,
        "collector": {"last_run": dict(last) if last else None,
                      "last_ok_at": last_ok["received_at"] if last_ok else None,
                      "stale": stale},
        "pipeline": steps,
    }


@app.get("/v1/profile")
def profile():
    row = conn().execute("SELECT data, updated_at FROM profile WHERE id=1").fetchone()
    if not row:
        raise HTTPException(404, "no profile yet")
    p = json.loads(row["data"])
    p["avatar"] = store.to_url(p.get("avatar"))
    p["updated_at"] = row["updated_at"]
    return p


KINDS = {"post", "carousel", "reel", "story"}


@app.get("/v1/items")
def items(kind: str | None = None, category: str | None = None, highlight: str | None = None,
          tag: str | None = None, q: str | None = None, before: str | None = None, limit: int = Query(30, ge=1, le=100)):
    c = conn()
    where, args = ["i.published_at IS NOT NULL"], []
    if kind:
        kinds = [k for k in kind.split(",") if k in KINDS]
        if not kinds:
            raise HTTPException(400, "unknown kind")
        where.append(f"i.kind IN ({','.join('?' * len(kinds))})")
        args += kinds
    if category:
        where.append("i.id IN (SELECT item_id FROM item_categories WHERE slug=?)")
        args.append(category)
    if highlight:
        where.append("i.id IN (SELECT item_id FROM item_highlights WHERE highlight_id=?)")
        args.append(highlight)
    if tag and tag.strip():
        where.append("i.id IN (SELECT item_id FROM item_tags WHERE tag=?)")
        args.append(" ".join(tag.strip().lower().lstrip("#").split()))
    if q and q.strip():
        fq = store.fts_query(q)
        if fq:
            where.append("i.id IN (SELECT id FROM items_fts WHERE items_fts MATCH ?)")
            args.append(fq)
    if before:
        t, i = store.decode_cursor(before)
        if i:
            where.append("(i.taken_at < ? OR (i.taken_at = ? AND i.id < ?))")
            args += [t, t, i]
        else:
            where.append("i.taken_at < ?")
            args.append(t)
    rows = c.execute(f"SELECT * FROM items i WHERE {' AND '.join(where)} ORDER BY i.taken_at DESC, i.id DESC LIMIT ?",
                     (*args, limit + 1)).fetchall()
    more = len(rows) > limit
    rows = rows[:limit]
    return {"items": [store.render_item(c, r) for r in rows],
            "next": store.encode_cursor(rows[-1]["taken_at"], rows[-1]["id"]) if more and rows else None}


@app.get("/v1/items/{item_id}")
def item(item_id: str):
    c = conn()
    row = c.execute("SELECT * FROM items WHERE id=? AND published_at IS NOT NULL", (item_id,)).fetchone()
    if not row:
        raise HTTPException(404, "no such item")
    return store.render_item(c, row)


@app.get("/v1/highlights")
def highlights():
    rows = conn().execute("SELECT * FROM highlights ORDER BY position, id").fetchall()
    return {"highlights": [store.render_highlight(r) for r in rows]}


@app.get("/v1/categories")
def categories():
    rows = conn().execute("""SELECT c.slug, c.name, c.description, COUNT(i.id) count FROM categories c
        LEFT JOIN item_categories ic ON ic.slug = c.slug
        LEFT JOIN items i ON i.id = ic.item_id AND i.published_at IS NOT NULL
        GROUP BY c.slug HAVING count > 0 ORDER BY count DESC, c.slug""").fetchall()
    return {"categories": [dict(r) for r in rows]}


TAG_KINDS = {"category", "keyword", "place", "country", "object", "animal", "brand", "hashtag", "person",
             "mood", "occasion"}


@app.get("/v1/tags")
def tags(kind: str | None = None, limit: int = Query(200, ge=1, le=2000)):
    where, args = ["i.published_at IS NOT NULL"], []
    if kind:
        kinds = [k for k in kind.split(",") if k in TAG_KINDS]
        if not kinds:
            raise HTTPException(400, f"kind must be one of {sorted(TAG_KINDS)}")
        where.append(f"t.kind IN ({','.join('?' * len(kinds))})")
        args += kinds
    rows = conn().execute(f"""SELECT t.tag, t.kind, COUNT(*) count FROM item_tags t JOIN items i ON i.id=t.item_id
        WHERE {' AND '.join(where)} GROUP BY t.tag, t.kind ORDER BY count DESC, t.tag LIMIT ?""",
                          (*args, limit)).fetchall()
    return {"tags": [dict(r) for r in rows]}


# ------------------------------------------------------------------ ingest
KEY_RE = re.compile(r"^(items/[A-Za-z0-9_\-]+/[A-Za-z0-9_.\-]+|highlights/[A-Za-z0-9_\-]+/[A-Za-z0-9_.\-]+|profile/[A-Za-z0-9_.\-]+)$")
CONTENT_TYPES = {"image/jpeg", "image/png", "image/webp", "image/heic", "video/mp4", "video/quicktime",
                 "audio/mpeg", "audio/mp4", "application/json"}


@app.post("/v1/ingest/media-url", dependencies=[Depends(require_token)])
async def media_url(request: Request):
    body = await request.json()
    key, ctype = body.get("key", ""), body.get("content_type", "")
    if not KEY_RE.match(key) or ".." in key:
        raise HTTPException(400, "key must look like items/<id>/<n>.<ext>, highlights/<id>/cover.jpg or profile/<file>")
    if ctype not in CONTENT_TYPES:
        raise HTTPException(400, f"content_type must be one of {sorted(CONTENT_TYPES)}")
    import boto3
    s3 = boto3.client("s3", region_name=config.REGION,
                      config=__import__("botocore.config").config.Config(signature_version="s3v4"))
    url = s3.generate_presigned_url("put_object", ExpiresIn=3600, HttpMethod="PUT",
                                    Params={"Bucket": config.MEDIA_BUCKET, "Key": key, "ContentType": ctype,
                                            "CacheControl": "public, max-age=31536000"})
    exists = False
    try:
        head = s3.head_object(Bucket=config.MEDIA_BUCKET, Key=key)
        exists = True
        size = head["ContentLength"]
    except Exception:
        size = None
    return {"upload_url": url, "public_url": f"{config.MEDIA_BASE_URL}/{key}",
            "headers": {"Content-Type": ctype, "Cache-Control": "public, max-age=31536000"},
            "exists": exists, "size": size}


@app.put("/v1/ingest/items", dependencies=[Depends(require_token)])
async def ingest_items(request: Request):
    body = await request.json()
    try:
        counts = store.upsert_items(conn(), body.get("items") or [])
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {"ok": True, **counts}


@app.put("/v1/ingest/highlights", dependencies=[Depends(require_token)])
async def ingest_highlights(request: Request):
    body = await request.json()
    try:
        n = store.upsert_highlights(conn(), body.get("highlights") or [])
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {"ok": True, "highlights": n}


@app.put("/v1/ingest/profile", dependencies=[Depends(require_token)])
async def ingest_profile(request: Request):
    body = await request.json()
    if not isinstance(body, dict) or not body.get("username"):
        raise HTTPException(400, "profile needs a username")
    store.put_profile(conn(), body)
    return {"ok": True}


@app.post("/v1/ingest/runs", dependencies=[Depends(require_token)])
async def ingest_run(request: Request):
    body = await request.json()
    rid = store.add_run(conn(), body)
    ok = bool(body.get("ok"))
    event("collector.run", logging.INFO if ok else logging.WARNING, run=rid, ok=ok,
          counts=body.get("counts"), started_at=body.get("started_at"), finished_at=body.get("finished_at"),
          log_url=body.get("log_url"))
    metric("CollectorRunsOk" if ok else "CollectorRunsFailed")
    return {"ok": True, "id": rid}


# ------------------------------------------------------------------ admin
@app.get("/v1/status")
def status():
    resp = JSONResponse(status_mod.build(conn()))
    resp.headers["Cache-Control"] = "public, max-age=5"
    return resp


@app.post("/v1/ingest/heartbeat", dependencies=[Depends(require_token)])
async def heartbeat(request: Request):
    """A part on the box (collector, monitor, ...) says how it is and what it is doing."""
    body = await request.json()
    comp = str(body.get("component") or "")
    if not re.fullmatch(r"[a-z][a-z0-9_-]{1,30}", comp) or comp in (
            "api", "db", "workers", "analyzer", "x_poster", "facebook_poster", "site", "disk", "cpu", "memory", "queues"):
        raise HTTPException(400, "component must be a short lowercase name of a part, e.g. collector or monitor")
    ok = bool(body.get("ok", True))
    detail = body.get("detail") if isinstance(body.get("detail"), dict) else {}
    if isinstance(body.get("jobs"), list):
        detail["jobs"] = body["jobs"][:10]
    ts = db.now()
    c = conn()
    c.execute("""INSERT INTO heartbeats(component, at, ok, detail, last_ok_at, last_error_at, last_error)
                 VALUES (?,?,?,?,?,?,?) ON CONFLICT(component) DO UPDATE SET at=excluded.at, ok=excluded.ok,
                 detail=excluded.detail, last_ok_at=COALESCE(excluded.last_ok_at, heartbeats.last_ok_at),
                 last_error_at=COALESCE(excluded.last_error_at, heartbeats.last_error_at),
                 last_error=COALESCE(excluded.last_error, heartbeats.last_error)""",
              (comp, ts, 1 if ok else 0, db.j(detail)[:20000], ts if ok else None,
               None if ok else ts, None if ok else str(body.get("error") or "not ok")[:1000]))
    if body.get("event"):
        store.record(c, comp, str(body.get("kind") or "event")[:30], str(body["event"]), ok=ok)
    return {"ok": True}


@app.get("/v1/admin/me", dependencies=[Depends(require_admin)])
def admin_me():
    """For the apps: does the token the owner typed work?"""
    return {"ok": True, "role": "owner"}


@app.get("/v1/admin/pipeline", dependencies=[Depends(require_admin_or_ingest)])
def admin_pipeline(failures: int = Query(20, ge=1, le=200)):
    return store.pipeline_status(conn(), failures)


@app.get("/v1/admin/items/{item_id}", dependencies=[Depends(require_admin)])
def admin_item(item_id: str):
    c = conn()
    row = c.execute("SELECT * FROM items WHERE id=?", (item_id,)).fetchone()
    if not row:
        raise HTTPException(404, "no such item")
    steps = [dict(r) for r in c.execute("SELECT * FROM steps WHERE item_id=?", (item_id,))]
    trans = [dict(r) for r in c.execute("SELECT * FROM transitions WHERE item_id=? ORDER BY id", (item_id,))]
    return {"item": store.render_item(c, row), "steps": steps, "transitions": trans}


@app.post("/v1/admin/items/{item_id}/reanalyze", dependencies=[Depends(require_admin)])
def admin_reanalyze(item_id: str):
    c = conn()
    if not c.execute("SELECT 1 FROM items WHERE id=?", (item_id,)).fetchone():
        raise HTTPException(404, "no such item")
    store.set_step(c, item_id, "analyze", "pending", note="owner asked")
    return {"ok": True}
