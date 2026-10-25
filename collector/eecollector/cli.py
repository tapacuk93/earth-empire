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
from .config import Secrets, Settings, is_placeholder
from .igweb import IGBrowser, IGStop
from .media import Downloader
from .pipeline import Collector, summarize
from .state import State

log = logging.getLogger("ee")

EXIT = {"config": 2, "checkpoint": 3, "login": 4, "rate_limit": 5}


def setup_logging(s: Settings, mode: str) -> Path | None:
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s", "%Y-%m-%dT%H:%M:%S")
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
    mode = "full" if args.cmd == "backfill" else "incremental"
    budget = float(args.budget) * 60 if args.budget else None
    if mode == "incremental" and not State(s.state_db).get("backfill.done_at"):
        # until the whole account is in, every timer run continues the backfill for a while
        mode = "full"
        budget = budget or 40 * 60
    setup_logging(s, mode)
    lk = lock(s)
    if not lk:
        log.info("another collector run (or a login) holds the lock; skipping this %s run", mode)
        return 6
    started = parse.now_iso()
    state = State(s.state_db)
    counts: dict = {}
    ok, code = False, 1
    backend = None
    try:
        target = args.target or secrets.target()
        if is_placeholder(target):
            raise IGStop("config", "earth-empire/target holds a placeholder; set the archived account's username")
        backend = Backend(s.api, secrets.ingest_token())
        with IGBrowser(s, creds=secrets.instagram, session_state=secrets.session_state, state=state) as ig:
            try:
                ig.ensure_session()
            except IGStop:
                ig.screenshot(s.state_dir / "screenshots")
                raise
            c = Collector(ig, backend, state, Downloader(ig.user_agent), target, limit=args.limit,
                          budget_s=budget)
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
        log.info("run %s finished: %s", mode, summarize(counts))
    except IGStop as e:
        code = EXIT.get(e.kind, 1)
        counts[f"stopped_{e.kind}"] = 1
        log.error("STOPPED (%s): %s", e.kind.upper(), e)
    except Exception as e:  # noqa: BLE001 - every failure ends in a run record
        log.exception("run %s failed: %s", mode, e)
        counts["failed"] = 1
    finally:
        if backend:
            try:
                backend.post_run({"started_at": started, "finished_at": parse.now_iso(), "ok": ok,
                                  "counts": {"mode": mode, **counts}})
            except Exception as e:  # noqa: BLE001
                log.error("could not record the run: %s", e)
        lk.close()
    return code


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
            ig.ensure_session()
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
    for name in ("backfill", "incremental"):
        p = sub.add_parser(name)
        p.add_argument("--target", help="override earth-empire/target (testing)")
        p.add_argument("--limit", type=int, help="stop paging after about this many items (testing)")
        p.add_argument("--budget", type=float, help="minutes; a backfill stops at its checkpoint after this")
    p = sub.add_parser("login", help="headed login on the remote display (noVNC)")
    p.add_argument("--wait", type=int, default=30, help="minutes to wait")
    sub.add_parser("auto-login", help="one headless login attempt with the stored credentials")
    p = sub.add_parser("import-session", help="load a Playwright storageState into the profile")
    p.add_argument("file", nargs="?", help="storageState JSON; default: secret earth-empire/instagram-session")
    sub.add_parser("status")
    args = ap.parse_args(argv)
    s = Settings()
    secrets = Secrets(s)
    return {"backfill": cmd_run, "incremental": cmd_run, "login": cmd_login, "auto-login": cmd_auto_login,
            "import-session": cmd_import, "status": cmd_status}[args.cmd](args, s, secrets)


if __name__ == "__main__":
    sys.exit(main())
