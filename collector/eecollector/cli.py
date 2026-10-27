"""ee-collector: backfill | incremental | login | import-session | status

Exit codes: 0 ok, 1 error, 2 config (placeholders), 3 checkpoint/challenge, 4 not logged in,
5 rate-limited, 6 another run holds the lock.
"""

from __future__ import annotations

import argparse
import fcntl
import json
import logging
import sys
import time
from pathlib import Path

from . import parse
from .backend import Backend
from .config import Secrets, Settings, active_runner, is_placeholder
from .igweb import IGBrowser, IGStop
from .media import Downloader
from .pipeline import Collector, summarize
from .state import State

log = logging.getLogger("ee")

COOLDOWN_FIRST = 2 * 3600   # after a 429: 2 h, then 4, 8, at most 12 h; reset by a good run
COOLDOWN_MAX = 12 * 3600
EXIT = {"config": 2, "checkpoint": 3, "login": 4, "rate_limit": 5}


def setup_logging(s: Settings, mode: str) -> Path | None:
    fmt = logging.Formatter("%(asctime)sZ %(levelname)s %(name)s: %(message)s", "%Y-%m-%dT%H:%M:%S")
    fmt.converter = time.gmtime  # log times in UTC, like the API
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    h = logging.StreamHandler(sys.stderr)
    h.setFormatter(fmt)
    root.addHandler(h)
    for noisy in ("httpx", "httpcore", "botocore", "boto3", "urllib3"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    try:
        s.log_dir.mkdir(parents=True, exist_ok=True)
        path = s.log_dir / f"{time.strftime('%Y%m%dT%H%M%S', time.gmtime())}-{mode}.log"
        fh = logging.FileHandler(path)
        fh.setFormatter(fmt)
        root.addHandler(fh)
        return path
    except OSError as e:
        log.warning("no log file (%s); logging to stderr only", e)
        return None


def lock(s: Settings):
    s.state_dir.mkdir(parents=True, exist_ok=True)
    s.profile_lock.parent.mkdir(parents=True, exist_ok=True)
    f = open(s.profile_lock, "a")
    try:
        fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        return None
    return f


def cmd_run(args, s: Settings, secrets: Secrets) -> int:
    mode = {"backfill": "full", "sample": "sample", "quick": "quick"}.get(args.cmd, "incremental")
    budget = float(args.budget) * 60 if args.budget else None
    if mode == "incremental" and not State(s.state_db).get("backfill.done_at"):
        # until the whole account is in, every timer run continues the backfill for a while
        mode = "full"
        budget = budget or 40 * 60
    setup_logging(s, mode)
    who = active_runner(s)
    if who and who != s.runner:
        log.info("the collector runs on %r (SSM %s); this runner (%r) stays off Instagram", who, s.runner_param, s.runner)
        return 0
    lk = lock(s)
    if not lk:
        log.info("another collector run (or a login) holds the lock; skipping this %s run", mode)
        return 6
    started = parse.now_iso()
    until = State(s.state_db).get("ratelimit.until", 0)
    if time.time() < until and not args.force:
        when = time.strftime("%H:%M UTC", time.gmtime(until))
        log.info("cooling down after Instagram's 429 until %s; not touching Instagram (--force overrides)", when)
        try:
            Backend(s.api, secrets.ingest_token()).heartbeat(
                ok=False, jobs=[], detail=_detail(State(s.state_db), State(s.state_db).get("last_run")),
                error=f"rate-limited by Instagram; cooling down until {when}")
        except Exception as e:  # noqa: BLE001
            log.warning("heartbeat: %s", e)
        lk.close()
        return 0
    state = State(s.state_db)
    counts: dict = {}
    ok, code = False, 1
    backend = None
    stop_text = stop_error = None
    try:
        target = args.target or secrets.target()
        if is_placeholder(target):
            raise IGStop("config", "earth-empire/target holds a placeholder; set the archived account's username")
        backend = Backend(s.api, secrets.ingest_token())
        backend.heartbeat(ok=True, jobs=[{"what": "login", "progress": None, "started_at": started}],
                          detail={"mode": {"full": "backfill"}.get(mode, mode)})
        with IGBrowser(s, creds=secrets.instagram if s.auto_login else None, session_state=secrets.session_state, state=state) as ig:
            try:
                ig.ensure_session()
            except IGStop:
                ig.screenshot(s.state_dir / "screenshots")
                raise
            c = Collector(ig, backend, state, Downloader(ig.user_agent), target, limit=args.limit,
                          budget_s=budget)
            c.started = started
            try:
                counts = c.run(mode)
            except IGStop:
                ig.screenshot(s.state_dir / "screenshots")
                raise
            finally:
                counts = c.counts
                try:
                    c.flush()
                except Exception as e:  # noqa: BLE001
                    log.error("final flush failed: %s", e)
        ok, code = True, 0
        state.set("ratelimit.strikes", 0)
        log.info("run %s finished: %s", mode, summarize(counts))
    except IGStop as e:
        code = EXIT.get(e.kind, 1)
        if e.kind == "rate_limit":
            strikes = int(state.get("ratelimit.strikes", 0)) + 1
            pause = min(COOLDOWN_MAX, COOLDOWN_FIRST * 2 ** (strikes - 1)) * (1 + 0.2 * (time.time() % 1))
            state.set("ratelimit.strikes", strikes)
            state.set("ratelimit.until", time.time() + pause)
            log.warning("rate limit #%d in a row: no Instagram requests for %.1f h", strikes, pause / 3600)
        counts[f"stopped_{e.kind}"] = 1
        log.error("STOPPED (%s): %s", e.kind.upper(), e)
        stop_text = f"STOPPED ({_stop_label(e)})"
        stop_error = str(e)
    except Exception as e:  # noqa: BLE001 - every failure ends in a run record
        log.exception("run %s failed: %s", mode, e)
        counts["failed"] = 1
        stop_text, stop_error = f"run failed: {type(e).__name__}", str(e)[:300]
    finally:
        last = {"finished_at": parse.now_iso(), "ok": ok, "mode": mode,
                "event": None if ok else stop_text, "error": None if ok else stop_error,
                "counts": {k: v for k, v in counts.items() if isinstance(v, (int, float))}}
        state.set("last_run", last)
        if backend:
            try:
                backend.post_run({"started_at": started, "finished_at": last["finished_at"], "ok": ok,
                                  "counts": {"mode": mode, **counts}})
            except Exception as e:  # noqa: BLE001
                log.error("could not record the run: %s", e)
            done = f"run finished ({ {'full': 'backfill'}.get(mode, mode) }): " + \
                ", ".join(f"{k} {v}" for k, v in sorted(last["counts"].items()) if k in ("items", "media_uploaded", "errors"))
            backend.heartbeat(ok=ok, jobs=[], detail=_detail(state, last),
                              event=done if ok else stop_text, kind="run" if ok else "stop",
                              error=None if ok else stop_error)
        lk.close()
    return code


def _stop_label(e: IGStop) -> str:
    text = str(e).lower()
    if e.kind == "login" and "refused" in text:
        return "login refused"
    if e.kind == "login" and "automatic login is off" in text:
        return "logged out, waiting for a login by hand"
    if e.kind == "page":
        return "profile page gave nothing"
    if e.kind == "config" and "not available" in text:
        return "target profile not available"
    return {"checkpoint": "checkpoint", "login": "logged out", "rate_limit": "rate limited",
            "config": "config"}.get(e.kind, e.kind)


def _detail(state: State, last: dict | None) -> dict:
    d = {"items_known": state.count_items(), "posts_known": state.count_posts(),
         "backfill_done": bool(state.get("backfill.done_at"))}
    if last:
        d["last_run_at"] = last.get("finished_at")
        d["last_run_ok"] = bool(last.get("ok"))
        if last.get("event"):
            d["last_stop"] = last["event"]
    return d


def cmd_heartbeat(args, s: Settings, secrets: Secrets) -> int:
    """Between runs: report the last run's outcome so /v1/status never shows the collector as down
    while it is only waiting for its timer. Touches nothing on Instagram."""
    logging.basicConfig(level=logging.WARNING)
    who = active_runner(s)
    if who and who != s.runner:
        return 0  # the active runner reports
    lk = lock(s)
    if not lk:
        return 0  # a run is going; it sends its own heartbeats
    lk.close()
    state = State(s.state_db)
    last = state.get("last_run")
    ok = bool(last.get("ok")) if last else True
    Backend(s.api, secrets.ingest_token()).heartbeat(
        ok=ok, jobs=[], detail=_detail(state, last),
        error=None if ok else (last.get("error") or last.get("event")))
    return 0


def cmd_login(args, s: Settings, secrets: Secrets) -> int:
    """Interactive: a headed browser on the remote display; the person logs in, the profile keeps it."""
    setup_logging(s, "login")
    lk = lock(s)
    if not lk:
        log.error("a collector run holds the lock; stop it first (systemctl stop ee-collector-*)")
        return 6
    s.headless = False
    state = State(s.state_db)
    with IGBrowser(s, state=state) as ig:
        ig.page.goto("https://www.instagram.com/accounts/login/")
        log.info("log in to Instagram in the remote browser window; waiting up to %d min", args.wait)
        deadline = time.time() + args.wait * 60
        while time.time() < deadline:
            if ig.logged_in() and "/accounts/login" not in ig.page.url and "/challenge" not in ig.page.url:
                ig.page.wait_for_timeout(5000)  # let "save login info" settle
                ig.mark_logged_in()
                log.info("logged in; the session is saved in %s", s.profile_dir)
                return 0
            ig.page.wait_for_timeout(2000)
    log.error("no login within %d minutes", args.wait)
    return 4


def cmd_auto_login(args, s: Settings, secrets: Secrets) -> int:
    """Headless automatic login with the stored credentials (one attempt), then a session check."""
    setup_logging(s, "login")
    lk = lock(s)
    if not lk:
        return 6
    state = State(s.state_db)
    try:
        with IGBrowser(s, creds=secrets.instagram, session_state=secrets.session_state, state=state) as ig:
            ig.ensure_session()  # auto-login is the explicit request for one attempt
            log.info("session ok")
        return 0
    except IGStop as e:
        log.error("STOPPED (%s): %s", e.kind.upper(), e)
        return EXIT.get(e.kind, 1)


def cmd_import(args, s: Settings, secrets: Secrets) -> int:
    """Import a Playwright storageState (file, or the earth-empire/instagram-session secret)."""
    setup_logging(s, "import")
    lk = lock(s)
    if not lk:
        return 6
    st = json.loads(Path(args.file).read_text()) if args.file else secrets.session_state()
    if not st:
        log.error("no storageState found")
        return 2
    with IGBrowser(s, state=State(s.state_db)) as ig:
        n = ig.import_state(st)
        ig.goto("https://www.instagram.com/")
        log.info("imported %d cookies; logged in: %s", n, ig.logged_in())
        if ig.logged_in():
            ig.mark_logged_in()
            return 0
        return 4


def cmd_status(args, s: Settings, secrets: Secrets) -> int:
    st = State(s.state_db)
    rows = st.db.execute("select k, v from kv where k not like 'backfill.hl.%' order by k").fetchall()
    print(json.dumps({"items": st.count_items(),
                      "highlights_read": st.db.execute("select count(*) from kv where k like 'backfill.hl.%'").fetchone()[0],
                      **{k: json.loads(v) for k, v in rows}}, indent=1))
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="ee-collector")
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("backfill", "incremental", "sample", "quick"):
        p = sub.add_parser(name)
        p.add_argument("--target", help="override earth-empire/target (testing)")
        p.add_argument("--limit", type=int, help="stop paging after about this many items (testing)")
        p.add_argument("--force", action="store_true", help="run even during a rate-limit cool-down")
        p.add_argument("--budget", type=float, help="minutes; a backfill stops at its checkpoint after this")
    p = sub.add_parser("login", help="headed login on the remote display (noVNC)")
    p.add_argument("--wait", type=int, default=30, help="minutes to wait")
    sub.add_parser("auto-login", help="one headless login attempt with the stored credentials")
    p = sub.add_parser("import-session", help="load a Playwright storageState into the profile")
    p.add_argument("file", nargs="?", help="storageState JSON; default: secret earth-empire/instagram-session")
    sub.add_parser("status")
    sub.add_parser("heartbeat", help="report the last run to /v1/status (the heartbeat timer)")
    args = ap.parse_args(argv)
    s = Settings()
    secrets = Secrets(s)
    return {"backfill": cmd_run, "incremental": cmd_run, "sample": cmd_run, "quick": cmd_run, "login": cmd_login, "auto-login": cmd_auto_login,
            "import-session": cmd_import, "status": cmd_status, "heartbeat": cmd_heartbeat}[args.cmd](args, s, secrets)


if __name__ == "__main__":
    sys.exit(main())
