"""The pipeline worker: one thread per lane, each taking the oldest due item.

- analyze: items in order, oldest first, within analysis.daily_cap (the cost guard).
- x:        analyzed items, oldest first, one every x.interval_minutes, at most x.daily_cap a day.
- facebook: analyzed items, oldest first, a few a day with random gaps (fbposter.due).
- house:    heartbeat metric, collector staleness, daily DB backup to S3.

A failure is recorded on that item's step and retried with backoff; the lane moves on to the next
item. Run: python -m ee.worker
"""
from __future__ import annotations

import json
import logging
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
def analyze_once(c) -> bool:
    if setting(c, "analysis.enabled") != "1":
        return False
    cap = int(setting(c, "analysis.daily_cap") or 0)
    if analysis.analyses_today(c) >= cap:
        return False
    item_id = store.claim_next(c, "analyze")
    if not item_id:
        return False
    try:
        analysis.analyze(c, item_id)
    except aicoin.OutOfCoins as e:
        store.set_step(c, item_id, "analyze", "pending", note="out of coins, waiting")
        event("analysis.out_of_coins", logging.ERROR, item=item_id,
              action="fund the server wallet (backend/README.md)")
        metric("WorkerErrors")
        stop.wait(3600)
        return False
    except Exception as e:
        store.fail_step(c, item_id, "analyze", f"{type(e).__name__}: {e}")
        c.execute("INSERT INTO costs(at, item_id, purpose, ok, note) VALUES (?,?,?,0,?)",
                  (utcnow(), item_id, "analyze", str(e)[:500]))
        metric("WorkerErrors")
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
    gap = timedelta(minutes=int(setting(c, "x.interval_minutes") or 30))
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
    try:
        xposter.post_item(c, item_id, dry_run=False)
    except xposter.XNoCredits as e:
        from .db import set_setting
        store.set_step(c, item_id, "x", "pending", note="X has no credits; posting paused")
        set_setting(c, "x.paused_until", "9999-12-31T00:00:00Z")
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
    try:
        fbposter.post_item(c, item_id, dry_run=False)
        fbposter.schedule_next(c)
    except (fbposter.NeedsOwner, fbposter.Warned) as e:
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
    return True


# ------------------------------------------------------------------ housekeeping
_last = {"beat": 0.0, "backup": ""}


def house_once(c) -> bool:
    t = time.time()
    if t - _last["beat"] >= 300:
        _last["beat"] = t
        metric("Heartbeat")
        st = c.execute("SELECT step, state, COUNT(*) n FROM steps GROUP BY step, state").fetchall()
        event("worker.heartbeat", steps={f"{r['step']}.{r['state']}": r["n"] for r in st})
    day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    if config.CLOUDWATCH and _last["backup"] != day and datetime.now(timezone.utc).hour >= 3:
        _last["backup"] = day
        backup(c)
    return False


def backup(c) -> str:
    import boto3
    path = config.DATA_DIR / "backup.sqlite3"
    path.unlink(missing_ok=True)
    c.execute("VACUUM INTO ?", (str(path),))
    subprocess.run(["gzip", "-f", str(path)], check=True)
    key = f"db/daily/{datetime.now(timezone.utc):%Y-%m-%d}.sqlite3.gz"
    s3 = boto3.client("s3", region_name=config.REGION)
    s3.upload_file(str(path) + ".gz", config.BACKUP_BUCKET, key)
    s3.upload_file(str(path) + ".gz", config.BACKUP_BUCKET, "db/latest.sqlite3.gz")
    event("backup.done", key=key)
    return key


def main():
    setup("worker")
    c = db.conn()
    n = store.recover_running(c)
    event("worker.start", requeued=n)
    signal.signal(signal.SIGTERM, lambda *_: stop.set())
    signal.signal(signal.SIGINT, lambda *_: stop.set())
    threads = [lane("analyze", analyze_once), lane("x", x_once, idle=60),
               lane("facebook", facebook_once, idle=120), lane("house", house_once, idle=30)]
    while not stop.is_set():
        stop.wait(5)
    event("worker.stop")
    for t in threads:
        t.join(timeout=30)


if __name__ == "__main__":
    main()
