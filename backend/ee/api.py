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
    """Public and minimal: is the API up. Everything else is in GET /v1/status (owner only)."""
    conn().execute("SELECT 1").fetchone()
    return {"ok": True}


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
          tag: str | None = None, facet: str | None = None, q: str | None = None, before: str | None = None, limit: int = Query(30, ge=1, le=100),
          lang: str | None = None):
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
    if facet and ":" in facet:
        from . import facets as fc
        ids = sorted(fc.item_ids_for(c, facet)) or ["-"]
        where.append(f"i.id IN ({','.join('?' * len(ids))})")
        args += ids
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
    from . import i18n
    lang = i18n.wanted(c, lang)
    return {"items": i18n.items(c, [store.render_item(c, r) for r in rows], lang),
            "next": store.encode_cursor(rows[-1]["taken_at"], rows[-1]["id"]) if more and rows else None}


@app.get("/v1/items/{item_id}")
def item(item_id: str, lang: str | None = None):
    from . import i18n
    c = conn()
    row = c.execute("SELECT * FROM items WHERE id=? AND published_at IS NOT NULL", (item_id,)).fetchone()
    if not row:
        raise HTTPException(404, "no such item")
    return i18n.items(c, [store.render_item(c, row)], i18n.wanted(c, lang))[0]


@app.get("/v1/items/{item_id}/explain")
def item_explain(item_id: str, lang: str = Query("en", max_length=35)):
    """What is happening, in the viewer's language (`lang`: a BCP 47 tag, e.g. `uk-UA`): a post by its own
    description, translated; anything else from its analysis. 503 past the day's cap: show the English text."""
    from . import aicoin, explain
    code = explain.normalize(lang)
    if not code:
        raise HTTPException(400, "lang must be a language tag such as en or uk-UA")
    c = conn()
    row = c.execute("SELECT * FROM items WHERE id=? AND published_at IS NOT NULL", (item_id,)).fetchone()
    if not row:
        raise HTTPException(404, "no such item")
    try:
        out = explain.explain(c, row, code)
    except explain.CapReached:
        raise HTTPException(503, "explanations are paused for today")
    except (aicoin.AicoinError, RuntimeError) as e:
        event("explain.failed", logging.WARNING, item=item_id, lang=code, error=repr(e))
        raise HTTPException(503, "could not explain right now")
    resp = JSONResponse(out)
    resp.headers["Cache-Control"] = "public, max-age=86400"
    return resp


@app.get("/v1/items/{item_id}/related")
def item_related(item_id: str, limit: int = Query(20, ge=1, le=100), lang: str | None = None):
    """Related published items and hits: the same half of Home first, then the other half."""
    from . import home
    c = conn()
    rel = home.related(c, item_id, limit)
    if not rel and not c.execute("SELECT 1 FROM items WHERE id=? AND published_at IS NOT NULL", (item_id,)).fetchone() \
            and item_id not in {h["id"] for h in home.published_hits()}:
        raise HTTPException(404, "no such item")
    ids = [r["id"] for r in rel if r["kind"] == "item"]
    rows = {r["id"]: r for r in c.execute(
        f"SELECT * FROM items WHERE published_at IS NOT NULL AND id IN ({','.join('?' * len(ids))})", ids)} if ids else {}
    out = []
    for r in rel:
        if r["kind"] == "item" and r["id"] in rows:
            from . import i18n
            out.append({**r, "item": i18n.items(c, [store.render_item(c, rows[r["id"]])], i18n.norm(lang))[0]})
        elif r["kind"] == "hit":
            out.append(r)   # the hit itself: GET /v1/published
    return {"related": out}


@app.get("/v1/layout")
def home_layout():
    from . import home
    return home.layout(conn())


@app.get("/v1/facets")
def facets_view(lang: str | None = None):
    from . import facets as fc, i18n
    c = conn()
    return i18n.facets(c, fc.public_view(c), i18n.wanted(c, lang))


@app.get("/v1/tags/graph")
def tags_graph(max_nodes: int = Query(300, ge=10, le=1000)):
    from . import home
    return home.tag_graph(conn(), max_nodes=max_nodes)


@app.get("/v1/highlights")
def highlights(lang: str | None = None):
    from . import i18n
    c = conn()
    rows = c.execute("SELECT * FROM highlights ORDER BY position, id").fetchall()
    return {"highlights": i18n.highlights(c, [store.render_highlight(r) for r in rows], i18n.norm(lang))}


@app.get("/v1/i18n")
def ui_strings(lang: str | None = None):
    """The site's own words in the visitor's language: {"lang", "strings": {english: translated}}."""
    from . import i18n
    c = conn()
    return i18n.ui(c, i18n.wanted(c, lang))


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
    # Only Content-Type is signed, so a client that sends just that header (as CONTRACT.md says)
    # matches the signature. (Signing Cache-Control too made such PUTs fail with 403
    # SignatureDoesNotMatch.) CloudFront caches media by its own policy.
    url = s3.generate_presigned_url("put_object", ExpiresIn=3600, HttpMethod="PUT",
                                    Params={"Bucket": config.MEDIA_BUCKET, "Key": key, "ContentType": ctype})
    exists = False
    try:
        head = s3.head_object(Bucket=config.MEDIA_BUCKET, Key=key)
        exists = True
        size = head["ContentLength"]
    except Exception:
        size = None
    return {"upload_url": url, "public_url": f"{config.MEDIA_BASE_URL}/{key}",
            "headers": {"Content-Type": ctype},
            "exists": exists, "size": size}


@app.put("/v1/ingest/items", dependencies=[Depends(require_token)])
async def ingest_items(request: Request):
    body = await request.json()
    try:
        counts = store.upsert_items(conn(), body.get("items") or [])
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {"ok": True, **counts}


@app.post("/v1/ingest/deleted", dependencies=[Depends(require_token)])
async def ingest_deleted(request: Request):
    """{"deleted": [item ids gone from Instagram], "restored": [ids seen again]}: off the site at once."""
    body = await request.json()
    return {"ok": True, **store.mark_deleted(conn(), body.get("deleted") or [], body.get("restored") or [])}


@app.put("/v1/ingest/detections", dependencies=[Depends(require_token)])
async def ingest_detections(request: Request):
    """The monitor's scan of the owner's items (CONTRACT.md "Detection"): stored as context on each item."""
    body = await request.json()
    rows = body.get("detections") if isinstance(body, dict) else None
    if not isinstance(rows, list):
        raise HTTPException(400, 'body must be {"detections": [{"id": "ig_…", "detection": {"matched": bool, "hits": [...]}}]}')
    c = conn()
    out = {"published": [], "unpublished": [], "unchanged": 0, "unknown": []}
    changed = False
    for r in rows:
        iid, det = (r or {}).get("id"), (r or {}).get("detection")
        if not iid or not isinstance(det, dict) or not isinstance(det.get("matched"), bool):
            raise HTTPException(400, "every entry needs id and detection.matched (bool)")
        det.setdefault("scanned_at", db.now())
        with db.tx(c):
            before = c.execute("SELECT published_at FROM items WHERE id=?", (iid,)).fetchone()
            if not before:
                out["unknown"].append(iid)
                continue
            c.execute("UPDATE items SET detection=? WHERE id=?", (db.j(det), iid))
            public, why = store.gate(c, iid)
            store.index_item(c, iid)
        if public and not before["published_at"]:
            out["published"].append(iid)
        elif not public and before["published_at"]:
            out["unpublished"].append(iid)
            changed = True
        else:
            out["unchanged"] += 1
    if changed:
        db.set_setting(c, "site.force", db.now())   # rebuild the site without them
    event("ingest.detections", n=len(rows), published=len(out["published"]), unpublished=len(out["unpublished"]))
    return {"ok": True, **out}


@app.put("/v1/ingest/highlights", dependencies=[Depends(require_token)])
async def ingest_highlights(request: Request):
    body = await request.json()
    try:
        c = conn()
        n = store.upsert_highlights(c, body.get("highlights") or [])
        gone = 0   # the tray can list fewer than exist (it stops at 100): removal waits for a per-highlight check
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {"ok": True, "highlights": n, "removed": gone}


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
@app.get("/v1/status", dependencies=[Depends(require_admin)])
def status():
    resp = JSONResponse(status_mod.build(conn()))
    resp.headers["Cache-Control"] = "private, no-store"
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


SIZE_KEYS = {"half_life_days": "size.half_life_days", "age_floor": "size.age_floor",
             "importance_w": "size.importance_w", "display_exponent": "size.display_exponent"}
PLACEMENT_KEYS = ("post", "dedicated", "shared", "repost", "story", "hit_top", "hit_bottom")


def _settings_view(c) -> dict:
    from . import rubric
    cur = rubric.current(c)
    return {
        "size": {k: float(db.setting(c, v)) for k, v in SIZE_KEYS.items()},
        "placement": {k: float(db.setting(c, f"placement.{k}")) for k in PLACEMENT_KEYS},
        "rubric": {"version": cur["version"], "text": cur["text"], "reason": cur["reason"], "by": cur["by"],
                   "history": rubric.history(c)},
        "rubric_review": db.setting(c, "importance.rubric_review") == "1",
        "formula": "size = the level's weight: L1 post or dedicated highlight, L2 shared highlight, L3 repost, "
                   "L4 story in no highlight (the placement weights); AI-found items get their level from Claude. "
                   "Tile area ∝ size ** display_exponent.",
        "unused_for_size": ["half_life_days", "age_floor", "importance_w"],
        "note": "Age and importance no longer change tile size; importance still sets the AI-found levels "
                "and breaks ties in ordering.",
    }


@app.get("/v1/admin/settings", dependencies=[Depends(require_admin)])
def admin_settings():
    """The owner's Settings screen: the size formula's parameters and the importance rubric."""
    return _settings_view(conn())


@app.put("/v1/admin/settings", dependencies=[Depends(require_admin)])
async def admin_settings_put(request: Request):
    """Partial update: {"size": {...}, "placement": {...}, "rubric": {"text", "reason"?}, "rubric_review": bool}."""
    body = await request.json()
    c = conn()

    def num(v, lo, hi, name):
        if not isinstance(v, (int, float)) or not lo <= float(v) <= hi:
            raise HTTPException(400, f"{name} must be a number from {lo} to {hi}")
        return str(float(v))
    for k, v in (body.get("size") or {}).items():
        if k not in SIZE_KEYS:
            raise HTTPException(400, f"unknown size setting {k}")
        lim = {"half_life_days": (0.5, 3650), "age_floor": (0, 1), "importance_w": (0, 1),
               "display_exponent": (0.25, 4)}[k]
        db.set_setting(c, SIZE_KEYS[k], num(v, *lim, k))
    for k, v in (body.get("placement") or {}).items():
        if k not in PLACEMENT_KEYS:
            raise HTTPException(400, f"unknown placement {k}")
        db.set_setting(c, f"placement.{k}", num(v, 0, 1, k))
    if "rubric_review" in body:
        db.set_setting(c, "importance.rubric_review", "1" if body["rubric_review"] else "0")
    r = body.get("rubric")
    if isinstance(r, dict) and (r.get("text") or "").strip():
        from . import rubric
        if r["text"].strip() != rubric.current(c)["text"].strip():
            v = rubric.add(c, r["text"], r.get("reason") or "edited by the owner", "owner", True)
            store.record(c, "analyzer", "rubric", f"importance rubric v{v} set by the owner; items are re-scored")
    event("settings.updated", keys=sorted(body.keys()))
    return _settings_view(c)


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


@app.delete("/v1/admin/items/{item_id}", dependencies=[Depends(require_admin)])
def admin_delete(item_id: str):
    """Remove an item for good (rows, media, CDN cache); the site is rebuilt without it."""
    c = conn()
    if not c.execute("SELECT 1 FROM items WHERE id=?", (item_id,)).fetchone():
        raise HTTPException(404, "no such item")
    out = store.delete_item(c, item_id)
    db.set_setting(c, "site.force", db.now())
    return {"ok": True, **out}


@app.put("/v1/admin/items/{item_id}/heard", dependencies=[Depends(require_admin)])
async def admin_item_heard(item_id: str, request: Request):
    """The owner's label for an item: {"text": "у тебе 3"}; kept over Claude's; "" or null hands it back."""
    from . import heard
    body = await request.json()
    text = body.get("text") if isinstance(body, dict) else None
    if text is not None and not isinstance(text, str):
        raise HTTPException(400, "text must be a string or null")
    c = conn()
    try:
        h = heard.set_by_owner(c, item_id, text)
    except KeyError:
        raise HTTPException(404, "no such item")
    return {"id": item_id, "heard": h}


@app.post("/v1/admin/items/{item_id}/reanalyze", dependencies=[Depends(require_admin)])
def admin_reanalyze(item_id: str):
    c = conn()
    if not c.execute("SELECT 1 FROM items WHERE id=?", (item_id,)).fetchone():
        raise HTTPException(404, "no such item")
    store.set_step(c, item_id, "analyze", "pending", note="owner asked")
    return {"ok": True}
