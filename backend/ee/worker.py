"""The pipeline worker: one thread per lane, each taking the oldest due item.

- analyze: items in order, oldest first, within analysis.daily_cap (the cost guard).
- x:        analyzed items, oldest first, one every x.interval_minutes, at most x.daily_cap a day.
- facebook: analyzed items, oldest first, a few a day with random gaps (fbposter.due).
- heard:    the phrase spoken in each video, from cached transcripts, behind analysis (ee.heard).
- house:    heartbeat metric, collector staleness, daily DB backup to S3.

A failure is recorded on that item's step and retried with backoff; the lane moves on to the next
item. Run: python -m ee.worker
"""
from __future__ import annotations

import json
import logging
import random
import signal
import subprocess
import threading
import time
import traceback
from datetime import datetime, timedelta, timezone

from . import aicoin, analysis, config, db, fbposter, store, xposter
from .db import setting
from .logs import event, metric, setup

stop = threading.Event()


def utcnow() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def lane(name, fn, idle=30):
    def loop():
        c = db.conn()
        while not stop.is_set():
            try:
                worked = fn(c)
            except Exception as e:
                event("worker.lane_error", logging.ERROR, lane=name, error=repr(e), tb=traceback.format_exc()[-2000:])
                metric("WorkerErrors")
                worked = False
            stop.wait(1 if worked else idle)
    t = threading.Thread(target=loop, name=name, daemon=True)
    t.start()
    return t


# ------------------------------------------------------------------ analyze
_budget_waits: dict[str, int] = {}


def ai_wait(e, lane: str = "ai") -> float:
    """Waiting for budget: until the cap resets when the answer says when, else a growing backoff
    (1, 2, 4 ... minutes, at most 15) with jitter. Never a reason to fail an item. The next retry
    time goes to GET /v1/status."""
    reset = getattr(e, "reset_at", None)
    secs = None
    if reset:
        try:
            secs = (datetime.strptime(reset[:19], "%Y-%m-%dT%H:%M:%S").replace(tzinfo=timezone.utc)
                    - datetime.now(timezone.utc)).total_seconds() + random.uniform(5, 60)
            secs = max(30.0, min(secs, 900.0))   # look again at least every 15 minutes
        except ValueError:
            secs = None
    if secs is None:
        n = _budget_waits[lane] = _budget_waits.get(lane, 0) + 1
        secs = min(60.0 * 2 ** (n - 1), 900.0) * random.uniform(0.8, 1.2)
    try:
        from .db import conn, set_setting
        set_setting(conn(), "ai.next_retry", (datetime.now(timezone.utc) + timedelta(seconds=secs))
                    .strftime("%Y-%m-%dT%H:%M:%SZ"))
    except Exception:
        pass
    return secs


def ai_ok(lane: str = "ai"):
    _budget_waits.pop(lane, None)



def analyze_once(c) -> bool:
    if setting(c, "analysis.enabled") != "1":
        return False
    cap = int(setting(c, "analysis.daily_cap") or 0)
    if analysis.analyses_today(c) >= cap:
        return False
    item_id = store.claim_next(c, "analyze")
    if not item_id:
        return False
    store.job_start(c, "analyze", "analyzer", "analyzing an item", item_id, "starting")
    try:
        analysis.analyze(c, item_id, job="analyze")
        ai_ok("analyze")
        stop.wait(random.uniform(5, 20))   # gentle on the proxy between items
    except aicoin.OutOfCoins as e:   # a cap, the wallet, or every provider out of credit: wait, keep the item
        store.set_step(c, item_id, "analyze", "pending", note=str(e)[:200])
        event("analysis.waiting", logging.WARNING, item=item_id, reason=str(e)[:300])
        metric("WorkerErrors")
        stop.wait(ai_wait(e, "analyze"))
        return False
    except Exception as e:
        store.fail_step(c, item_id, "analyze", f"{type(e).__name__}: {e}")
        c.execute("INSERT INTO costs(at, item_id, purpose, ok, note) VALUES (?,?,?,0,?)",
                  (utcnow(), item_id, "analyze", str(e)[:500]))
        metric("WorkerErrors")
    finally:
        store.job_end(c, "analyze")
    return True


# ------------------------------------------------------------------ Home layout and importance backfill
_home_last = {"t": 0.0}


def home_once(c) -> bool:
    """Embeddings and layout for Home, every minute at most."""
    if time.time() - _home_last["t"] < 60:
        return False
    _home_last["t"] = time.time()
    from . import home
    store.job_start(c, "home", "layout", "updating the Home layout", progress="embeddings, placement, places")
    try:
        changed = home.refresh(c)
        from .db import set_setting
        set_setting(c, "home.recomputed_at", utcnow())
    finally:
        store.job_end(c, "home")
    return changed


def facets_once(c) -> bool:
    from . import facets
    ok, why = facets.due(c)
    if not ok:
        return False
    store.job_start(c, "facets", "facets", "Claude is redefining the site's facets", progress=why)
    from .db import set_setting
    set_setting(c, "facets.started_at", utcnow())
    try:
        doc = facets.run(c)
        store.record(c, "facets", "generated", f"{len(doc['facets'])} facets over {doc['items']} items ({why})")
        ai_ok("facets")
    except aicoin.OutOfCoins as e:
        stop.wait(ai_wait(e, "facets"))
    except Exception as e:
        event("facets.failed", logging.WARNING, error=repr(e)[:500])
        from .db import set_setting
        set_setting(c, "facets.last_run", utcnow())   # try again in 10 minutes at the earliest
        metric("WorkerErrors")
    finally:
        store.job_end(c, "facets")
    return True


def rubric_once(c) -> bool:
    """Once a day: Claude reviews the importance rubric and may refine it (a new version re-scores)."""
    if setting(c, "importance.rubric_review") != "1" or setting(c, "analysis.enabled") != "1":
        return False
    day = utcnow()[:10]
    if (setting(c, "importance.rubric_reviewed") or "") >= day:
        return False
    from .db import set_setting
    store.job_start(c, "rubric", "rubric", "Claude is reviewing the importance rubric")
    try:
        from . import rubric
        rubric.review(c)
        set_setting(c, "importance.rubric_reviewed", day)
    except aicoin.OutOfCoins as e:   # budget: try again later today
        stop.wait(ai_wait(e, "rubric"))
    except Exception as e:
        set_setting(c, "importance.rubric_reviewed", day)   # a real error: once a day is enough
        event("rubric.review_failed", logging.WARNING, error=repr(e)[:300])
    finally:
        store.job_end(c, "rubric")
    return True


_score_failures: dict[str, int] = {}


def importance_once(c) -> bool:
    """When the analyzer has nothing to do: score items analyzed before importance existed."""
    if setting(c, "analysis.enabled") != "1":
        return False
    analysis_can_run = analysis.analyses_today(c) < int(setting(c, "analysis.daily_cap") or 0)
    if analysis_can_run and c.execute(
            "SELECT 1 FROM steps WHERE step='analyze' AND state IN ('pending','running') LIMIT 1").fetchone():
        return False   # the lowest priority: only when no analysis is waiting (and allowed today)
    if c.execute("""SELECT 1 FROM items i JOIN steps s ON s.item_id = i.id WHERE i.priority = 1 AND
                    i.analysis IS NOT NULL AND ((s.step = 'site' AND s.state = 'pending') OR i.thumbs IS NULL)
                    LIMIT 1""").fetchone():
        return False   # and never while an analyzed new item is still on its way to the site
    from . import importance
    day = utcnow()[:10]
    done = c.execute("SELECT COUNT(*) n FROM costs WHERE purpose='importance' AND at >= ?", (day,)).fetchone()["n"]
    if done >= int(setting(c, "importance.rescore_daily_cap") or 300):
        return False   # the cost guard for scoring; the rest continues tomorrow
    ids = importance.pending(c, 1)
    if not ids:
        return False
    store.job_start(c, "importance", "importance", "scoring importance (multimodal, current rubric)", ids[0],
                    f"{len(importance.pending(c, 100000))} to score")
    try:
        importance.backfill_one(c, ids[0], job="importance")
        _score_failures.pop(ids[0], None)
        ai_ok("importance")
        stop.wait(random.uniform(3, 10))
    except aicoin.OutOfCoins as e:   # a cap, the wallet, or the providers: wait, do not burn items
        event("importance.paused", logging.WARNING, error=str(e)[:300])
        stop.wait(ai_wait(e, "importance"))
    except Exception as e:
        n = _score_failures[ids[0]] = _score_failures.get(ids[0], 0) + 1
        event("importance.failed", logging.WARNING, item=ids[0], error=repr(e)[:300], attempt=n)
        if n >= 2:   # give this item up for this rubric version; the next version retries it
            from . import rubric
            c.execute("UPDATE items SET importance=COALESCE(importance, 0.5), importance_method=2, "
                      "importance_version=? WHERE id=?", (rubric.current(c)["version"], ids[0]))
        stop.wait(60 * n)
    finally:
        store.job_end(c, "importance")
    return True


_heard_failures: dict[str, int] = {}


def heard_once(c) -> bool:
    """The phrase spoken in each video (ee.heard), from cached transcripts only: always behind new-item
    analysis, a few items per call, within heard.daily_cap calls a day and the AI budget."""
    if setting(c, "analysis.enabled") != "1" or setting(c, "heard.enabled") != "1":
        return False
    analysis_can_run = analysis.analyses_today(c) < int(setting(c, "analysis.daily_cap") or 0)
    if analysis_can_run and c.execute(
            "SELECT 1 FROM steps WHERE step='analyze' AND state IN ('pending','running') LIMIT 1").fetchone():
        return False   # behind analysis: never while an item waits for it (and analysis may run today)
    from . import heard
    day = utcnow()[:10]
    calls = c.execute("SELECT COUNT(*) n FROM costs WHERE purpose='heard' AND at >= ?", (day,)).fetchone()["n"]
    if calls >= int(setting(c, "heard.daily_cap") or 150):
        return False   # the cost guard; the rest continues tomorrow
    queue = heard.pending(c, 200)
    if not queue:
        return False
    ids = heard.batch(c, queue, int(setting(c, "heard.batch_size") or 8))
    store.job_start(c, "heard", "heard", "Claude is reading what is said in the videos", ids[0],
                    f"{len(ids)} items in this call, {len(heard.pending(c, 100000))} waiting")
    try:
        heard.run_batch(c, ids)
        for i in ids:
            _heard_failures.pop(i, None)
        ai_ok("heard")
        from .db import set_setting
        set_setting(c, "heard.last_run", utcnow())
        stop.wait(random.uniform(3, 10))
    except aicoin.OutOfCoins as e:   # a cap, the wallet, or the providers: wait, keep the items
        event("heard.paused", logging.WARNING, error=str(e)[:300])
        stop.wait(ai_wait(e, "heard"))
    except Exception as e:
        failed = getattr(e, "missing", ids)
        given_up = []
        for i in failed:
            n = _heard_failures[i] = _heard_failures.get(i, 0) + 1
            if n >= 2:
                given_up.append(i)
                _heard_failures.pop(i, None)
        heard.give_up(c, given_up)   # done for now, without a phrase; a new transcript or highlight retries
        from .db import set_setting
        set_setting(c, "heard.last_error", f"{utcnow()} {type(e).__name__}: {e}"[:300])
        event("heard.failed", logging.WARNING, items=failed, error=repr(e)[:300], given_up=given_up)
        metric("WorkerErrors")
        stop.wait(60)
    finally:
        store.job_end(c, "heard")
    return True


# ------------------------------------------------------------------ thumbnails
_thumb_failures: dict[str, int] = {}


def thumbs_once(c) -> bool:
    from . import thumbs
    item_id = thumbs.next_without(c)
    if not item_id:
        return False
    try:
        thumbs.thumbs_for(c, item_id)
    except Exception as e:
        n = _thumb_failures[item_id] = _thumb_failures.get(item_id, 0) + 1
        event("thumbs.failed", logging.WARNING, item=item_id, error=repr(e)[:300], attempt=n)
        if n >= 3:   # give up on this one (the original thumbnail stays null)
            c.execute("UPDATE items SET thumbs='{}' WHERE id=?", (item_id,))
        stop.wait(30 * n)
    return True


# ------------------------------------------------------------------ X
def is_test(c, item_id) -> bool:
    """Fixture items (extra.test) are never posted anywhere."""
    row = c.execute("SELECT data FROM items WHERE id=?", (item_id,)).fetchone()
    return bool(row and (json.loads(row["data"]).get("extra") or {}).get("test"))


def x_once(c) -> bool:
    # Dry runs are the CLI's (ee x dry-run); the lane only posts for real.
    if setting(c, "x.enabled") != "1" or setting(c, "x.dry_run") == "1" or not xposter.credentials():
        return False
    paused = setting(c, "x.paused_until")
    if paused and paused > utcnow():
        return False
    last = c.execute("SELECT MAX(updated_at) t FROM steps WHERE step='x' AND state='posted'").fetchone()["t"]
    gap = timedelta(minutes=int(setting(c, "x.interval_minutes") or 30) * random.uniform(0.8, 1.3))
    if last and datetime.strptime(last, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc) + gap > datetime.now(timezone.utc):
        return False
    day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    n = c.execute("SELECT COUNT(*) n FROM steps WHERE step='x' AND state='posted' AND updated_at >= ?", (day,)).fetchone()["n"]
    if n >= int(setting(c, "x.daily_cap") or 40):
        return False
    item_id = store.claim_next(c, "x", requires_analysis=True)
    if not item_id:
        return False
    if is_test(c, item_id):
        store.set_step(c, item_id, "x", "skipped", note="test fixture")
        return True
    store.job_start(c, "x", "x_poster", "posting a thread to X", item_id, "uploading media")
    try:
        xposter.post_item(c, item_id, dry_run=False, job="x")
    except xposter.XNoCredits as e:
        from .db import set_setting
        store.set_step(c, item_id, "x", "pending", note="X has no credits; posting paused")
        set_setting(c, "x.paused_until", "9999-12-31T00:00:00Z")
        store.record(c, "x_poster", "paused", "X API has no credits; posting paused", ok=False)
        event("x.no_credits", logging.ERROR, item=item_id, error=str(e),
              action="buy X API credits (console.x.com), then: ee settings x.paused_until ''")
        metric("WorkerErrors")
    except xposter.XError as e:
        store.fail_step(c, item_id, "x", str(e), permanent=e.status in (400, 403))
        if e.retry_after:
            from .db import set_setting
            set_setting(c, "x.paused_until", (datetime.now(timezone.utc) + timedelta(seconds=e.retry_after))
                        .strftime("%Y-%m-%dT%H:%M:%SZ"))
        metric("WorkerErrors")
    except Exception as e:
        store.fail_step(c, item_id, "x", f"{type(e).__name__}: {e}")
        metric("WorkerErrors")
    finally:
        store.job_end(c, "x")
    return True


# ------------------------------------------------------------------ Facebook
def facebook_once(c) -> bool:
    if setting(c, "facebook.enabled") != "1" or setting(c, "facebook.dry_run") == "1":
        return False
    ok, why = fbposter.due(c)
    if not ok:
        return False
    item_id = store.claim_next(c, "facebook", requires_analysis=True)
    if not item_id:
        return False
    if is_test(c, item_id):
        store.set_step(c, item_id, "facebook", "skipped", note="test fixture")
        return True
    store.job_start(c, "facebook", "facebook_poster", "posting to Facebook", item_id, "opening the composer")
    try:
        fbposter.post_item(c, item_id, dry_run=False, job="facebook")
        fbposter.schedule_next(c)
    except (fbposter.NeedsOwner, fbposter.Warned, fbposter.OwnerDecision) as e:
        fbposter.handle_block(c, e)
        store.set_step(c, item_id, "facebook", "pending", note=str(e)[:500])
    except Exception as e:
        row = c.execute("SELECT detail FROM steps WHERE item_id=? AND step='facebook'", (item_id,)).fetchone()
        submitted = row and row["detail"] and "submitted_at" in json.loads(row["detail"])
        store.fail_step(c, item_id, "facebook",
                        f"{type(e).__name__}: {e}" + (" - Post was clicked: check the profile, then "
                                                       "`ee steps set <id> facebook posted|pending`" if submitted else ""),
                        permanent=bool(submitted))
        fbposter.schedule_next(c)
        metric("WorkerErrors")
    finally:
        store.job_end(c, "facebook")
    return True


# ------------------------------------------------------------------ housekeeping
_last = {"beat": 0.0, "backup": 0.0, "backup_day": "", "site": 0.0, "wallet": 0.0}
SITE_BUILD = "/opt/earth-empire/repo/backend/deploy/build-site.sh"


SITE_MIN_GAP = 90   # seconds between builds: new items show within ~2 minutes, bursts coalesce


def site_live(item_id: str, tries: int = 6) -> bool:
    """Is the item's prerendered page served by empire.earth (through CloudFront)?"""
    import httpx
    url = f"{config.env('EE_SITE_URL', 'https://empire.earth')}/item/{item_id}"
    for i in range(tries):
        try:
            r = httpx.get(url, params={"_": int(time.time())}, timeout=20, follow_redirects=True)
            if r.status_code == 200 and item_id in r.text:
                return True
        except httpx.HTTPError:
            pass
        stop.wait(10)
    return False


def site_once(c) -> None:
    """Rebuild and publish the site when items went public since the last good build, then check
    the newest item's page is live. Only a verified build moves site.built_at, so a build that
    missed an item is simply done again on the next tick."""
    if setting(c, "site.auto_build") != "1" or time.time() - _last["site"] < SITE_MIN_GAP:
        return
    row = c.execute("SELECT id, published_at FROM items WHERE published_at IS NOT NULL "
                    "ORDER BY published_at DESC, id DESC LIMIT 1").fetchone()
    force = setting(c, "site.force")
    if not force and (not row or row["published_at"] <= (setting(c, "site.built_at") or "")):
        return
    newest, newest_id = (row["published_at"], row["id"]) if row else (setting(c, "site.built_at") or "", None)
    _last["site"] = time.time()
    t0 = time.time()
    store.job_start(c, "site", "site", "building and publishing empire.earth", progress="npm build, prerender, sync")
    try:
        p = subprocess.run(["bash", SITE_BUILD], capture_output=True, text=True, timeout=1800)
        if p.returncode == 0:
            store.job_progress(c, "site", "checking the new page is live")
            live = site_live(newest_id) if newest_id else True   # nothing public: the empty site is fine
    finally:
        store.job_end(c, "site")
    from .db import set_setting
    if p.returncode == 0 and live:
        set_setting(c, "site.built_at", newest)
        if force and setting(c, "site.force") == force:
            set_setting(c, "site.force", "")
        event("site.built", seconds=round(time.time() - t0), newest=newest, item=newest_id, out=p.stdout[-300:])
        store.record(c, "site", "build", f"site rebuilt and published in {round(time.time() - t0)} s")
    elif p.returncode == 0:
        event("site.not_live", logging.ERROR, item=newest_id, out=p.stdout[-800:])
        store.record(c, "site", "build", "site built, but the newest page is not live yet; rebuilding", ok=False)
        metric("WorkerErrors")
    else:
        event("site.build_failed", logging.ERROR, code=p.returncode, err=(p.stderr or p.stdout)[-1500:])
        store.record(c, "site", "build", "site build failed", ok=False)
        metric("WorkerErrors")


def house_once(c) -> bool:
    t = time.time()
    if t - _last["beat"] >= 300:
        _last["beat"] = t
        metric("Heartbeat")
        st = c.execute("SELECT step, state, COUNT(*) n FROM steps GROUP BY step, state").fetchall()
        event("worker.heartbeat", steps={f"{r['step']}.{r['state']}": r["n"] for r in st})
    from .db import set_setting
    set_setting(c, "worker.heartbeat_at", utcnow())
    if config.CLOUDWATCH and t - _last["backup"] >= 3600:   # hourly; the first each day also kept dated
        _last["backup"] = t
        day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        try:
            from . import backup
            keys = backup.backup_all(daily=_last["backup_day"] != day)
            _last["backup_day"] = day
            set_setting(c, "backup.last_at", utcnow())
            store.record(c, "db", "backup", f"backed up {len(keys)} database(s)")
        except Exception as e:
            set_setting(c, "backup.last_error", f"{utcnow()} {e}"[:300])
            store.record(c, "db", "backup", f"backup failed: {type(e).__name__}", ok=False)
            event("backup.failed", logging.ERROR, error=repr(e))
            metric("WorkerErrors")
    if config.CLOUDWATCH and t - _last["wallet"] >= 3600:
        _last["wallet"] = t
        try:
            bal = aicoin.balance()
            set_setting(c, "analysis.wallet_balance", str(bal.get("balance", 0)))
            set_setting(c, "analysis.wallet_checked_at", utcnow())
        except Exception as e:
            event("wallet.balance_unavailable", logging.WARNING, error=str(e))
    if config.CLOUDWATCH:
        site_once(c)
    return False


def main():
    setup("worker")
    c = db.conn()
    n = store.recover_running(c)
    c.execute("DELETE FROM jobs WHERE component IN ('analyzer','x_poster','facebook_poster','site')")
    event("worker.start", requeued=n)
    signal.signal(signal.SIGTERM, lambda *_: stop.set())
    signal.signal(signal.SIGINT, lambda *_: stop.set())
    threads = [lane("analyze", analyze_once), lane("thumbs", thumbs_once, idle=20),
               lane("home", home_once, idle=20), lane("importance", importance_once, idle=60),
               lane("heard", heard_once, idle=60),
               lane("facets", facets_once, idle=60), lane("rubric", rubric_once, idle=600), lane("x", x_once, idle=60),
               lane("facebook", facebook_once, idle=120), lane("house", house_once, idle=15)]
    while not stop.is_set():
        stop.wait(5)
    event("worker.stop")
    for t in threads:
        t.join(timeout=30)


if __name__ == "__main__":
    main()
