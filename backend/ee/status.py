"""GET /v1/status: what the backend is doing now and how every component is (CONTRACT.md "Status").

Public, so nothing secret or private leaves here: no tokens, keys, addresses, URLs with queries,
file paths or account names; error texts are reduced to a short, scrubbed sentence; items that
are not public yet are never named.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import time
from datetime import datetime, timezone

from .db import setting

STARTED = time.time()

SCRUB = [
    (re.compile(r"(?i)(bearer|token|key|secret|password|signature|authorization)[\"'=: ]+\S+"), r"\1 [hidden]"),
    (re.compile(r"https?://[^\s\"')]+"), lambda m: re.sub(r"[?#].*", "", m.group(0))),
    (re.compile(r"[A-Za-z0-9_\-]{32,}(\.[A-Za-z0-9_\-]{16,})?"), "[hidden]"),
    (re.compile(r"/(var|opt|tmp|home|etc|usr)/[^\s\"')]*"), "[path]"),
    (re.compile(r"(?i)screenshot\s+\S+"), "screenshot saved"),
    (re.compile(r"'[^']{24,}'|\"[^\"]{24,}\""), "'…'"),
]


def scrub(text: str | None, limit: int = 200) -> str | None:
    if not text:
        return None
    t = str(text)
    for rx, rep in SCRUB:
        t = rx.sub(rep, t)
    t = " ".join(t.split())
    return t[:limit] + ("…" if len(t) > limit else "")


def _now():
    return datetime.now(timezone.utc)


def _ts():
    return _now().strftime("%Y-%m-%dT%H:%M:%SZ")


def _ago(seconds: float) -> str:
    return datetime.fromtimestamp(time.time() - seconds, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _age(ts: str | None) -> float | None:
    if not ts:
        return None
    try:
        return (_now() - datetime.strptime(ts[:19], "%Y-%m-%dT%H:%M:%S").replace(tzinfo=timezone.utc)).total_seconds()
    except ValueError:
        return None


def comp(cid, name, state, *, last_success=None, last_error=None, details=None):
    return {"id": cid, "name": name, "state": state, "last_success": last_success,
            "last_error": last_error, "details": details or {}}


def err(at, message):
    return {"at": at, "message": scrub(message)} if at or message else None


def _public_ids(c) -> set:
    return {r["id"] for r in c.execute("SELECT id FROM items WHERE published_at IS NOT NULL")}


def _last_transition(c, step, to_state):
    return c.execute("SELECT at, note, item_id FROM transitions WHERE step=? AND to_state=? ORDER BY id DESC LIMIT 1",
                     (step, to_state)).fetchone()


def _box():
    out = []
    du = shutil.disk_usage("/")
    pct = du.used / du.total * 100
    out.append(comp("disk", "Disk", "down" if pct > 95 else "degraded" if pct > 85 else "ok",
                    details={"used_percent": round(pct, 1), "free_gb": round(du.free / 1e9, 1),
                             "total_gb": round(du.total / 1e9, 1)}))
    try:
        mem = {}
        with open("/proc/meminfo") as f:
            for line in f:
                k, v = line.split(":")
                mem[k] = int(v.split()[0]) * 1024
        used = 1 - mem["MemAvailable"] / mem["MemTotal"]
        swap_used = (mem["SwapTotal"] - mem["SwapFree"]) / mem["SwapTotal"] if mem.get("SwapTotal") else 0
        out.append(comp("memory", "Memory", "down" if used > 0.97 else "degraded" if used > 0.9 else "ok",
                        details={"used_percent": round(used * 100, 1), "total_gb": round(mem["MemTotal"] / 1e9, 1),
                                 "swap_used_percent": round(swap_used * 100, 1)}))
    except (OSError, KeyError, ValueError):
        pass
    try:
        l1, l5, l15 = os.getloadavg()
        n = os.cpu_count() or 1
        out.append(comp("cpu", "CPU", "degraded" if l5 / n > 1.5 else "ok",
                        details={"load_1m": round(l1, 2), "load_5m": round(l5, 2), "load_15m": round(l15, 2),
                                 "cpus": n, "busy_percent_5m": round(min(l5 / n, 1) * 100)}))
    except OSError:
        pass
    return out


def build(c) -> dict:
    public = _public_ids(c)
    comps = []

    comps.append(comp("api", "API", "ok", last_success=_ts(),
                      details={"uptime_s": int(time.time() - STARTED), "version": os.environ.get("EE_VERSION", "1")}))

    t0 = time.time()
    items = c.execute("SELECT COUNT(*) n, SUM(published_at IS NOT NULL) p FROM items").fetchone()
    q_ms = round((time.time() - t0) * 1000, 1)
    from . import config
    try:
        size = os.path.getsize(config.DB_PATH) / 1e6
    except OSError:
        size = None
    b_at, b_err = setting(c, "backup.last_at"), setting(c, "backup.last_error")
    b_age = _age(b_at)
    comps.append(comp("db", "Database", "degraded" if b_age is None or b_age > 3 * 3600 else "ok",
                      last_success=b_at or None,
                      last_error=err(b_err[:20] if b_err else None, b_err[21:] if b_err else None),
                      details={"items": items["n"], "published": items["p"] or 0, "query_ms": q_ms,
                               "size_mb": round(size, 1) if size else None, "last_backup_at": b_at or None,
                               "backup": "hourly to S3, all parts"}))

    hb = setting(c, "worker.heartbeat_at")
    hb_age = _age(hb)
    comps.append(comp("workers", "Workers", "down" if hb_age is None or hb_age > 300 else "ok", last_success=hb or None,
                      details={"heartbeat_age_s": int(hb_age) if hb_age is not None else None,
                               "lanes": ["analyze", "x", "facebook", "housekeeping"]}))

    # analyzer
    q = {r["state"]: r["n"] for r in c.execute("SELECT state, COUNT(*) n FROM steps WHERE step='analyze' GROUP BY state")}
    done = _last_transition(c, "analyze", "done")
    fail = _last_transition(c, "analyze", "failed")
    day = _now().strftime("%Y-%m-%d")
    today = c.execute("SELECT COUNT(*) n FROM costs WHERE purpose='analyze' AND at >= ?", (day,)).fetchone()["n"]
    cap = int(setting(c, "analysis.daily_cap") or 0)
    ai = json.loads(setting(c, "ai.state") or "null") or {}
    a_state = "ok"
    reason = None
    if setting(c, "analysis.enabled") != "1":
        a_state, reason = "off", "turned off"
    elif ai.get("state") in ("waiting", "error"):
        a_state, reason = "degraded", ai.get("reason")
    elif q.get("pending", 0) and today >= cap:
        a_state, reason = "degraded", "daily cap reached; the rest waits for tomorrow"
    elif fail and done and fail["at"] > done["at"]:
        a_state, reason = "degraded", "the latest analysis failed"
    comps.append(comp("analyzer", "AI analyzer", a_state, last_success=done["at"] if done else None,
                      last_error=err(fail["at"], fail["note"]) if fail else None,
                      details={"reason": reason, "model": "Claude Sonnet 5.5 (Anthropic API)", "pending": q.get("pending", 0),
                               "running": q.get("running", 0), "done": q.get("done", 0), "failed": q.get("failed", 0),
                               "analyzed_today": today, "daily_cap": cap}))
    spent = c.execute("SELECT COALESCE(SUM(usd), 0) s FROM costs WHERE at >= ? AND ok=1", (day,)).fetchone()["s"]
    budget_usd = float(setting(c, "ai.daily_budget_usd") or 10)
    comps.append(comp("claude", "Claude (Anthropic API)",
                      {"ok": "ok", "waiting": "degraded", "error": "down"}.get(ai.get("state"), "ok"),
                      last_success=ai.get("at") if ai.get("state") == "ok" else None,
                      last_error=err(ai.get("at"), ai.get("reason")) if ai.get("state") in ("waiting", "error") else None,
                      details={"reason": ai.get("reason"), "spent_today_usd": round(spent, 3),
                               "daily_budget_usd": budget_usd}))

    # collector and other parts that report heartbeats
    last = c.execute("SELECT finished_at, ok, counts, received_at FROM runs ORDER BY id DESC LIMIT 1").fetchone()
    last_ok = c.execute("SELECT received_at FROM runs WHERE ok=1 ORDER BY id DESC LIMIT 1").fetchone()
    last_bad = c.execute("SELECT received_at, counts FROM runs WHERE ok=0 ORDER BY id DESC LIMIT 1").fetchone()
    ok_age = _age(last_ok["received_at"]) if last_ok else None
    hbs = {r["component"]: r for r in c.execute("SELECT * FROM heartbeats")}
    col_hb = hbs.pop("collector", None)
    c_state = "down" if ok_age is None or ok_age > 3 * 3600 else ("degraded" if last and not last["ok"] else "ok")
    counts = json.loads(last["counts"]) if last else {}
    comps.append(comp("collector", "Instagram collector", c_state,
                      last_success=last_ok["received_at"] if last_ok else None,
                      last_error=err(last_bad["received_at"], "run failed: " + ", ".join(
                          f"{k}={v}" for k, v in json.loads(last_bad["counts"] or "{}").items()
                          if isinstance(v, (int, float, str)) and k not in ("log_url",))[:160]) if last_bad else None,
                      details={"last_run_at": last["received_at"] if last else None,
                               "last_run_ok": bool(last["ok"]) if last else None,
                               "last_run_counts": {k: v for k, v in counts.items() if isinstance(v, (int, float))},
                               "runs_24h": c.execute("SELECT COUNT(*) n FROM runs WHERE received_at >= ?",
                                                     (_ago(86400),)).fetchone()["n"],
                               **({"heartbeat": _hb_detail(col_hb)} if col_hb else {})}))
    for name in ["monitor", *sorted(k for k in hbs if k != "monitor")]:
        h = hbs.get(name)
        if not h:
            comps.append(comp(name, name.capitalize(), "down", details={"reason": "no heartbeat received yet"}))
            continue
        age = _age(h["at"])
        st = "down" if age is None or age > 1800 else ("ok" if h["ok"] else "degraded")
        comps.append(comp(name, name.capitalize(), st, last_success=h["last_ok_at"],
                          last_error=err(h["last_error_at"], h["last_error"]), details=_hb_detail(h)))

    # posters
    for cid, name, step in (("x_poster", "X poster", "x"), ("facebook_poster", "Facebook poster", "facebook")):
        pre = step
        q = {r["state"]: r["n"] for r in c.execute("SELECT state, COUNT(*) n FROM steps WHERE step=? GROUP BY state", (step,))}
        posted = _last_transition(c, step, "posted")
        fail = _last_transition(c, step, "failed")
        enabled = setting(c, f"{pre}.enabled") == "1" and setting(c, f"{pre}.dry_run") != "1"
        paused = setting(c, f"{pre}.paused_until")
        st, reason = "ok", None
        if not enabled:
            st, reason = "off", "not switched on yet"
        elif paused and (paused.startswith("session:") or paused > _ts()):
            st = "degraded"
            reason = setting(c, f"{pre}.pause_reason") or ("X API has no credits" if paused.startswith("9999")
                                                          else "paused")
        elif fail and (not posted or fail["at"] > posted["at"]):
            st, reason = "degraded", "the latest post failed"
        det = {"reason": reason, "posted": q.get("posted", 0), "pending": q.get("pending", 0),
               "failed": q.get("failed", 0), "skipped": q.get("skipped", 0),
               "daily_cap": int(setting(c, f"{pre}.daily_cap") or 0)}
        if paused and not paused.startswith(("session:", "9999")):
            det["paused_until"] = paused
        if step == "facebook":
            det["next_post_at"] = setting(c, "facebook.next_at") or None
        else:
            det["interval_minutes"] = int(setting(c, "x.interval_minutes") or 0)
        comps.append(comp(cid, name, st, last_success=posted["at"] if posted else None,
                          last_error=err(fail["at"], fail["note"]) if fail else None, details=det))

    # background AI jobs: importance scoring, rubric, facets, layout, and today's spend
    from . import importance as imp_mod, rubric as rub_mod
    day = _now().strftime("%Y-%m-%d")
    queue = len(imp_mod.pending(c, 100000))
    scored_today = c.execute("SELECT COUNT(*) n FROM costs WHERE purpose='importance' AND at >= ?", (day,)).fetchone()["n"]
    last_scored = c.execute("SELECT MAX(at) t FROM costs WHERE purpose='importance'").fetchone()["t"]
    rub = rub_mod.current(c)
    cap = int(setting(c, "importance.rescore_daily_cap") or 0)
    scored = c.execute("SELECT COUNT(*) n FROM items WHERE analysis IS NOT NULL AND importance_version = ? "
                       "AND importance_method >= 2", (rub["version"],)).fetchone()["n"]
    analyzed = c.execute("SELECT COUNT(*) n FROM items WHERE analysis IS NOT NULL").fetchone()["n"]
    comps.append(comp("importance", "Importance scoring", "degraded" if queue and scored_today >= cap else "ok",
                      last_success=last_scored, details={
                          "rubric_version": rub["version"], "method": "frames, images, transcripts, text",
                          "queue": queue, "scored_with_current_rubric": scored, "analyzed": analyzed,
                          "progress_percent": round(100 * scored / analyzed) if analyzed else 100,
                          "scored_today": scored_today, "daily_cap": cap,
                          "reason": "daily cap reached" if queue and scored_today >= cap else None}))
    comps.append(comp("rubric", "Importance rubric", "ok" if setting(c, "importance.rubric_review") == "1" else "off",
                      last_success=rub.get("created_at"), details={
                          "version": rub["version"], "by": rub.get("by"), "reason": scrub(rub.get("reason"), 200),
                          "versions": c.execute("SELECT COUNT(*) n FROM rubrics").fetchone()["n"],
                          "last_review_day": setting(c, "importance.rubric_reviewed") or None}))
    fdoc = json.loads(setting(c, "facets.current") or "{}")
    comps.append(comp("facets", "Facets", "ok", last_success=fdoc.get("generated_at"), details={
        "facets": len(fdoc.get("facets") or []),
        "categories": sum(len(f.get("categories") or []) for f in fdoc.get("facets") or []),
        "items": fdoc.get("items"),
        "runs_today": c.execute("SELECT COUNT(*) n FROM costs WHERE purpose='facets' AND at >= ?", (day,)).fetchone()["n"],
        "daily_cap": int(setting(c, "facets.daily_cap") or 0)}))
    lay = {r["half"]: r["n"] for r in c.execute("SELECT half, COUNT(*) n FROM layout GROUP BY half")}
    comps.append(comp("layout", "Home layout", "ok", last_success=setting(c, "home.recomputed_at") or None, details={
        "top_tiles": lay.get("top", 0), "bottom_tiles": lay.get("bottom", 0),
        "embedded": c.execute("SELECT COUNT(*) n FROM embeddings").fetchone()["n"],
        "half_life_days": float(setting(c, "size.half_life_days") or 0),
        "importance_w": float(setting(c, "size.importance_w") or 0),
        "display_exponent": float(setting(c, "size.display_exponent") or 0)}))
    spend = {r["purpose"]: {"calls": r["n"], "coins": round(r["coins"] or 0, 1), "usd": round(r["usd"] or 0, 3)}
             for r in c.execute("SELECT purpose, COUNT(*) n, SUM(coins) coins, SUM(usd) usd FROM costs "
                                "WHERE at >= ? GROUP BY purpose", (day,))}
    comps.append(comp("spend", "AI spend today", "ok", details={
        "by_purpose": spend, "coins": round(sum(v["coins"] for v in spend.values()), 1),
        "usd": round(sum(v["usd"] for v in spend.values()), 2)}))

    site_at = setting(c, "site.built_at")
    comps.append(comp("site", "Site build", "ok" if setting(c, "site.auto_build") == "1" else "off",
                      details={"newest_item_published": site_at or None}))
    comps += _box()

    queues = {}
    for r in c.execute("SELECT step, state, COUNT(*) n FROM steps GROUP BY step, state"):
        queues.setdefault(r["step"], {})[r["state"]] = r["n"]
    comps.append(comp("queues", "Queues", "ok", details=queues))

    # activity
    jobs = []
    for r in c.execute("SELECT * FROM jobs ORDER BY started_at"):
        el = _age(r["started_at"])
        jobs.append({"component": r["component"], "what": r["what"],
                     "item": r["item_id"] if r["item_id"] in public else None,
                     "progress": scrub(r["progress"], 120), "started_at": r["started_at"],
                     "elapsed_s": int(el) if el is not None else None})
    for name, h in list(hbs.items()) + ([("collector", col_hb)] if col_hb else []):
        for jb in (json.loads(h["detail"] or "{}").get("jobs") or [])[:5]:
            if isinstance(jb, dict):
                jobs.append({"component": name, "what": scrub(jb.get("what"), 120), "item": None,
                             "progress": scrub(jb.get("progress"), 120), "started_at": jb.get("started_at"),
                             "elapsed_s": int(_age(jb.get("started_at")) or 0) if jb.get("started_at") else None})

    events = []
    for r in c.execute("SELECT at, item_id, step, from_state, to_state, note FROM transitions "
                       "WHERE to_state != 'running' ORDER BY id DESC LIMIT 60"):
        comp_id = {"analyze": "analyzer", "x": "x_poster", "facebook": "facebook_poster", "site": "site"}.get(r["step"], r["step"])
        text = {"done": "analyzed an item", "posted": "published an item" if r["step"] == "site" else "posted an item",
                "failed": "failed: " + (scrub(r["note"], 140) or ""), "pending": "queued an item",
                "skipped": "skipped an item"}.get(r["to_state"], r["to_state"])
        events.append({"at": r["at"], "component": comp_id, "kind": r["to_state"], "text": text,
                       "item": r["item_id"] if r["item_id"] in public else None, "ok": r["to_state"] != "failed"})
    for r in c.execute("SELECT * FROM events ORDER BY id DESC LIMIT 50"):
        events.append({"at": r["at"], "component": r["component"], "kind": r["kind"], "text": scrub(r["text"], 160),
                       "item": r["item_id"] if r["item_id"] in public else None, "ok": bool(r["ok"])})
    for r in c.execute("SELECT received_at, ok, counts FROM runs ORDER BY id DESC LIMIT 20"):
        cnt = {k: v for k, v in json.loads(r["counts"] or "{}").items() if isinstance(v, (int, float))}
        events.append({"at": r["received_at"], "component": "collector", "kind": "run",
                       "text": ("collector run ok" if r["ok"] else "collector run failed") +
                               (": " + ", ".join(f"{k} {v}" for k, v in list(cnt.items())[:6]) if cnt else ""),
                       "item": None, "ok": bool(r["ok"])})
    events.sort(key=lambda e: e["at"] or "", reverse=True)

    order = {"down": 3, "degraded": 2, "ok": 1, "off": 0}
    core = [x for x in comps if x["id"] in ("api", "db", "workers", "analyzer", "collector")]
    worst = max((order[x["state"]] for x in core), default=1)
    overall = {3: "down", 2: "degraded"}.get(worst, "ok")
    return {"generated_at": _ts(), "overall": overall, "components": comps,
            "activity": {"jobs": jobs, "events": events[:50]}}


def _hb_detail(h) -> dict:
    d = json.loads(h["detail"] or "{}")
    out = {"heartbeat_at": h["at"]}
    for k, v in d.items():
        if k == "jobs":
            continue
        if isinstance(v, (int, float, bool)) or v is None:
            out[k] = v
        elif isinstance(v, str):
            out[k] = scrub(v, 120)
    return out
