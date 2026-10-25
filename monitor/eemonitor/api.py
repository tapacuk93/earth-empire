"""The monitor's HTTP API (CONTRACT.md "Monitor"), a service of its own on 127.0.0.1:8010; nginx on the
box routes /v1/monitor/ and /v1/published here, behind the same CloudFront as the backend's API.

    uvicorn eemonitor.api:app --port 8010
"""
from __future__ import annotations

import base64
import hmac
import json
import logging

from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware

from . import db, detect, media, registry, worker

log = logging.getLogger("ee.monitor.api")
app = FastAPI(title="Earth Empire monitor", docs_url="/v1/monitor/docs", openapi_url="/v1/monitor/openapi.json",
              redoc_url=None)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["GET", "POST", "PUT", "OPTIONS"],
                   allow_headers=["*"], max_age=86400)


def conn():
    return db.conn()


def admin(request: Request):
    """The owner: earth-empire/admin-token, the same check as the backend's require_admin."""
    if request.method == "OPTIONS":
        return
    auth = request.headers.get("authorization", "")
    try:
        from ee import config
        token = config.secret("admin_token")
        placeholder = config.is_placeholder(token)
    except Exception:  # noqa: BLE001
        token, placeholder = None, True
    if isinstance(token, dict):
        token = token.get("token") or token.get("value")
    if not token or placeholder or not auth.startswith("Bearer ") or \
            not hmac.compare_digest(auth[7:].strip().encode(), str(token).encode()):
        raise HTTPException(401, "bad or missing admin token")


# Every /v1/monitor/* route is the owner's; only /v1/published is public.
from fastapi import APIRouter  # noqa: E402

owner = APIRouter(dependencies=[Depends(admin)])


def _at_url(platform: str, url: str, t: float) -> str:
    s = int(max(0, t - 2))
    if platform == "youtube":
        return url + ("&" if "?" in url else "?") + f"t={s}s"
    if platform in ("telegram", "facebook"):
        return url + ("&" if "?" in url else "?") + f"t={s}"
    return url


def render(c, row) -> dict:
    h = json.loads(row["data"])
    v = c.execute("SELECT * FROM videos WHERE id=?", (row["video_id"],)).fetchone()
    src = c.execute("SELECT * FROM sources WHERE id=?", (v["source_id"],)).fetchone() if v and v["source_id"] else None
    acc = c.execute("SELECT handle FROM accounts WHERE id=?", (v["account_id"],)).fetchone() if v and v["account_id"] else None
    extra = json.loads(v["extra"] or "{}") if v else {}
    return {
        "id": row["id"], "kind": h["kind"], "phrase": h.get("phrase"), "matched": h["matched"],
        "confidence": h["confidence"], "confidence_label": detect.label(h["confidence"]),
        "scores": h.get("scores"), "notes": h.get("notes", []), "judge": h.get("judge"),
        "language": h.get("language"), "expected_languages": h.get("expected_languages") or
        (json.loads(src["expected_languages"]) if src else []),
        "platform": v["platform"] if v else None,
        "source_kind": v["source_kind"] if v else None, "via": v["via"] if v else None, "hop": v["hop"] if v else 0,
        "source": {"id": src["id"], "name": src["name"], "kind": src["kind"], "country": src["country"],
                   "source_kind": src["source_kind"]} if src else
        ({"id": None, "name": extra.get("owner_name") or extra.get("author"), "kind": None, "country": None,
          "source_kind": v["source_kind"]} if v else None),
        "account": acc["handle"] if acc else extra.get("author") or extra.get("owner_name"),
        "video": {"id": v["id"], "url": v["url"], "title": v["title"], "posted_at": v["posted_at"],
                  "duration": v["duration"], "thumbnail": v["thumbnail"]} if v else None,
        "start": h["start"], "end": h["end"],
        "at_url": _at_url(v["platform"], v["url"], h["start"]) if v else None,
        "excerpt": {"text": h.get("excerpt"), "start": h.get("excerpt_start"), "end": h.get("excerpt_end"),
                    "language": h.get("language"), "en": h.get("excerpt_en")},
        "clip": media.url(row, h, "clip"), "frame": media.url(row, h, "frame"),
        "model": h.get("model"), "found_at": row["found_at"], "published_at": row["published_at"],
        "level": (row["level"] or row["ai_level"]) if "level" in row.keys() else h.get("level"),
        "ai_level": row["ai_level"] if "ai_level" in row.keys() else h.get("level"),
        "level_by": "owner" if "level" in row.keys() and row["level"] and row["level"] != row["ai_level"] else "ai",
        "level_reason": h.get("level_reason"),
    }


def _cursor(offset: int) -> str:
    return base64.urlsafe_b64encode(str(offset).encode()).decode().rstrip("=")


def _offset(cur: str | None) -> int:
    if not cur:
        return 0
    try:
        return int(base64.urlsafe_b64decode(cur + "=" * (-len(cur) % 4)).decode())
    except Exception:  # noqa: BLE001
        raise HTTPException(400, "bad cursor") from None


@owner.get("/v1/monitor/hits")
def hits(kind: str | None = None, platform: str | None = None, source_kind: str | None = None,
         phrase: str | None = None, min_confidence: float = 0.0, published: bool | None = None,
         sort: str = Query("confidence", pattern="^(confidence|recent|posted)$"),
         before: str | None = None, limit: int = Query(30, ge=1, le=100)):
    c = conn()
    where, args = ["h.confidence >= ?"], [min_confidence]
    if not source_kind:
        where.append("v.source_kind != 'mirror'")   # the owner's own posts: only when asked for
    for col, val in (("h.kind", kind), ("v.platform", platform), ("v.source_kind", source_kind)):
        if val:
            vals = val.split(",")
            where.append(f"{col} IN ({','.join('?' * len(vals))})")
            args += vals
    if phrase:
        where.append("json_extract(h.data, '$.phrase') = ?")
        args.append(phrase.lower())
    if published is not None:
        where.append("h.published_at IS " + ("NOT NULL" if published else "NULL"))
    order = {"confidence": "h.confidence DESC, h.found_at DESC", "recent": "h.found_at DESC, h.confidence DESC",
             "posted": "v.posted_at DESC, h.start"}[sort]
    off = _offset(before)
    rows = c.execute(f"""SELECT h.* FROM hits h JOIN videos v ON v.id=h.video_id WHERE {' AND '.join(where)}
                         ORDER BY {order} LIMIT ? OFFSET ?""", (*args, limit + 1, off)).fetchall()
    more = len(rows) > limit
    return {"hits": [render(c, r) for r in rows[:limit]], "next": _cursor(off + limit) if more else None}


@owner.get("/v1/monitor/hits/{hit_id}")
def hit(hit_id: str):
    c = conn()
    r = c.execute("SELECT * FROM hits WHERE id=?", (hit_id,)).fetchone()
    if not r:
        raise HTTPException(404, "no such hit")
    return render(c, r)


def _level(body) -> int | None:
    lv = body.get("level") if isinstance(body, dict) else None
    if lv is None:
        return None
    if isinstance(lv, str) and lv.upper().startswith("L"):
        lv = lv[1:]
    try:
        lv = int(lv)
    except (TypeError, ValueError):
        lv = 0
    if not 1 <= lv <= 4:
        raise HTTPException(400, "level must be 1 (highest) to 4")
    return lv


async def _body(request: Request):
    try:
        return await request.json()
    except Exception:  # noqa: BLE001
        return {}


@owner.post("/v1/monitor/hits/{hit_id}/publish")
async def publish(hit_id: str, request: Request):
    """"+": approve the hit for the Home mosaic at its AI level, or at `level` when the owner overrides it."""
    override = _level(await _body(request))
    c = conn()
    row = c.execute("SELECT * FROM hits WHERE id=?", (hit_id,)).fetchone()
    if not row:
        raise HTTPException(404, "no such hit")
    media.publish(row, json.loads(row["data"]))
    level = override or row["level"] or row["ai_level"] or 3
    c.execute("UPDATE hits SET published_at=COALESCE(published_at, ?), level=?, section=NULL WHERE id=?",
              (db.now(), level, hit_id))
    return render(c, c.execute("SELECT * FROM hits WHERE id=?", (hit_id,)).fetchone())


@owner.put("/v1/monitor/hits/{hit_id}/level")
async def set_level(hit_id: str, request: Request):
    """The owner's level for a hit (approved or not); {"level": null} goes back to the AI level."""
    body = await _body(request)
    override = _level(body)
    c = conn()
    row = c.execute("SELECT * FROM hits WHERE id=?", (hit_id,)).fetchone()
    if not row:
        raise HTTPException(404, "no such hit")
    c.execute("UPDATE hits SET level=? WHERE id=?", (override, hit_id))
    return render(c, c.execute("SELECT * FROM hits WHERE id=?", (hit_id,)).fetchone())


@owner.post("/v1/monitor/hits/{hit_id}/unpublish")
def unpublish(hit_id: str):
    c = conn()
    if not c.execute("SELECT 1 FROM hits WHERE id=?", (hit_id,)).fetchone():
        raise HTTPException(404, "no such hit")
    row = c.execute("SELECT * FROM hits WHERE id=?", (hit_id,)).fetchone()
    c.execute("UPDATE hits SET published_at=NULL WHERE id=?", (hit_id,))
    media.unpublish(row, json.loads(row["data"]))
    return render(c, c.execute("SELECT * FROM hits WHERE id=?", (hit_id,)).fetchone())


@app.get("/v1/published")
def published(before: str | None = None, limit: int = Query(30, ge=1, le=100)):
    """The hits the owner approved for Home, newest first, each with its level."""
    c = conn()
    off = _offset(before)
    rows = c.execute("SELECT * FROM hits WHERE published_at IS NOT NULL ORDER BY published_at DESC LIMIT ? OFFSET ?",
                     (limit + 1, off)).fetchall()
    return {"hits": [render(c, r) for r in rows[:limit]], "next": _cursor(off + limit) if len(rows) > limit else None}


@owner.post("/v1/monitor/fetch")
async def fetch(request: Request):
    try:
        body = await request.json()
    except Exception:  # noqa: BLE001
        body = {}
    n = body.get("n", 10) if isinstance(body, dict) else 10
    if not isinstance(n, int) or n < 1:
        raise HTTPException(400, "n must be a positive integer")
    c = conn()
    pending = c.execute("SELECT COALESCE(SUM(remaining),0) r FROM requests WHERE done_at IS NULL").fetchone()["r"]
    queued = c.execute("SELECT COUNT(*) n FROM videos WHERE state='queued'").fetchone()["n"]
    if pending + queued > 500:
        raise HTTPException(429, "the queue is full; try again later")
    return worker.fetch_request(c, n, {"platform": body.get("platform"), "source_kind": body.get("source_kind")})


@owner.get("/v1/monitor/sources")
def sources(platform: str | None = None, source_kind: str | None = None):
    c = conn()
    out = []
    for s in c.execute("SELECT * FROM sources ORDER BY source_kind, name").fetchall():
        if source_kind and s["source_kind"] != source_kind:
            continue
        accs = [dict(a) for a in c.execute(
            """SELECT a.id, platform, handle, platform_id, enabled, last_polled_at, last_error,
                      (SELECT COUNT(*) FROM videos v WHERE v.account_id=a.id) videos,
                      (SELECT COUNT(*) FROM videos v WHERE v.account_id=a.id AND state='done') scanned
               FROM accounts a WHERE source_id=?""", (s["id"],))]
        if platform:
            accs = [a for a in accs if a["platform"] == platform]
            if not accs:
                continue
        out.append({"id": s["id"], "name": s["name"], "kind": s["kind"], "country": s["country"],
                    "source_kind": s["source_kind"], "origin": s["origin"], "source_url": s["source_url"],
                    "expected_languages": json.loads(s["expected_languages"]),
                    "languages_inferred": bool(s["languages_inferred"]), "accounts": accs})
    return {"sources": out}


@owner.post("/v1/monitor/sources")
async def add_source(request: Request):
    try:
        return registry.add_owner_source(conn(), await request.json())
    except ValueError as e:
        raise HTTPException(400, str(e)) from None


@owner.get("/v1/monitor/phrases")
def get_phrases():
    from . import highlights
    c = conn()
    return {"phrases": worker.list_phrases(c), "suggested": highlights.list_suggestions(c)}


@owner.post("/v1/monitor/phrases/suggested/{text}/accept")
def accept_suggestion(text: str):
    from . import highlights
    c = conn()
    if not highlights.decide(c, text, True):
        raise HTTPException(404, "no such suggestion")
    return get_phrases()


@owner.post("/v1/monitor/phrases/suggested/{text}/reject")
def reject_suggestion(text: str):
    from . import highlights
    c = conn()
    if not highlights.decide(c, text, False):
        raise HTTPException(404, "no such suggestion")
    return get_phrases()


@owner.post("/v1/monitor/phrases/suggest")
def make_suggestions():
    """Ask Claude now (it also runs by itself when the highlights change)."""
    from . import highlights
    c = conn()
    n = highlights.suggest_phrases(c, force=True)
    return {"added": n, **get_phrases()}


@owner.put("/v1/monitor/phrases")
async def put_phrases(request: Request):
    body = await request.json()
    ps = body.get("phrases") if isinstance(body, dict) else None
    if not isinstance(ps, list) or not all(isinstance(p, str) for p in ps) or not ps:
        raise HTTPException(400, 'body must be {"phrases": ["...", ...]}')
    c = conn()
    worker.set_phrases(c, ps, use_claude=body.get("claude", True) is not False)
    if body.get("rescan", True):
        db.set_setting(c, "rescan.requested", db.now())
    return get_phrases()


@owner.post("/v1/monitor/rescan")
def rescan():
    c = conn()
    db.set_setting(c, "rescan.requested", db.now())
    n = c.execute("SELECT COUNT(*) n FROM videos WHERE state='done' AND transcript IS NOT NULL").fetchone()["n"]
    return {"ok": True, "videos": n}


@owner.get("/v1/monitor/learning")
def learning():
    """Misses and improvements: the mirror of tapacuk93's Instagram as ground truth."""
    from . import learn
    return learn.report(conn())


@owner.get("/v1/monitor/videos")
def videos(state: str | None = None, platform: str | None = None, limit: int = Query(50, ge=1, le=200)):
    c = conn()
    where, args = ["1=1"], []
    if state:
        where.append("state=?")
        args.append(state)
    if platform:
        where.append("platform=?")
        args.append(platform)
    rows = c.execute(f"""SELECT id, platform, source_id, source_kind, via, hop, url, title, posted_at, duration, state,
                         requested, error, scanned_at, languages, audio_s, cpu_s, model,
                         (SELECT COUNT(*) FROM hits h WHERE h.video_id=videos.id) hits
                         FROM videos WHERE {' AND '.join(where)}
                         ORDER BY COALESCE(scanned_at, discovered_at) DESC LIMIT ?""", (*args, limit)).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        d["languages"] = json.loads(d["languages"]) if d["languages"] else None
        out.append(d)
    return {"videos": out}


def _learning_summary(c) -> dict:
    from . import learn
    r = learn.report(c)
    return {k: r[k] for k in ("checked", "matched", "found_first", "recall", "misses_by_cause")}


@owner.get("/v1/monitor/status")
def status():
    c = conn()
    states = {}
    for r in c.execute("SELECT platform, state, COUNT(*) n FROM videos GROUP BY platform, state"):
        states.setdefault(r["platform"], {})[r["state"]] = r["n"]
    perf = c.execute("""SELECT COUNT(*) n, SUM(audio_s) a, SUM(cpu_s) cpu FROM
                        (SELECT audio_s, cpu_s FROM videos WHERE state='done' AND audio_s>0 ORDER BY scanned_at DESC LIMIT 50)""").fetchone()
    hits_by = {f"{r['kind']}.{detect.label(r['confidence'])}": r["n"] for r in
               c.execute("SELECT kind, confidence, COUNT(*) n FROM hits GROUP BY kind, confidence")}
    agg: dict[str, int] = {}
    for k, n in hits_by.items():
        agg[k] = agg.get(k, 0) + n
    stops = [dict(r) for r in c.execute("SELECT * FROM stops")]
    usage = {r["counter"]: round(r["value"], 3) for r in c.execute("SELECT counter, value FROM usage WHERE day=?", (db.today(),))}
    return {
        "ok": True,
        "videos": states,
        "scanned_total": c.execute("SELECT COUNT(*) n FROM videos WHERE state='done'").fetchone()["n"],
        "audio_hours_total": round((c.execute("SELECT SUM(audio_s) s FROM videos WHERE state='done'").fetchone()["s"] or 0) / 3600, 2),
        "hits": agg,
        "throughput": {"recent_videos": perf["n"], "audio_s": round(perf["a"] or 0, 1), "cpu_s": round(perf["cpu"] or 0, 1),
                       "cpu_per_audio": round((perf["cpu"] or 0) / perf["a"], 3) if perf["a"] else None},
        "today": usage,
        "caps": {k: db.setting(c, k) for k in ("scan.daily_audio_minutes", "scan.recommended_daily_audio_minutes",
                                               "claude.daily_usd", "rec.daily_expansions", "whisper.model")},
        "requests": [dict(r) for r in c.execute("SELECT * FROM requests WHERE done_at IS NULL")],
        "stops": stops,
        "gate": __import__("eemonitor.gate", fromlist=["summary"]).summary(c),
        "gate_published": __import__("eemonitor.gate", fromlist=["summary"]).summary(c, True),
        "learning": _learning_summary(c),
        "last_scans": [dict(r) for r in c.execute(
            "SELECT id, platform, scanned_at, audio_s, (SELECT COUNT(*) FROM hits h WHERE h.video_id=videos.id) hits "
            "FROM videos WHERE state='done' ORDER BY scanned_at DESC LIMIT 5")],
    }


app.include_router(owner)
