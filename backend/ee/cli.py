"""`ee` - the backend's command line. On the box: sudo -u earth /opt/earth-empire/backend-venv/bin/ee ...

  ee status [--json]                  pipeline counts per state, latest failures, spend
  ee estimate                         what analyzing the pending backlog would cost
  ee analyze <id>... | --next N       analyze now (ignores the daily cap) [--dry-run]
  ee x dry-run [--n 3] [--id ID]      print the next threads that would be posted
  ee x post <id>                      post one item now
  ee facebook check                   is the session logged in? (screenshot)
  ee facebook dry-run [--id ID]       fill the composer for the next item, do not post
  ee facebook post <id>               post one item now
  ee settings [key [value]]           show or change a setting (analysis.daily_cap, x.enabled, ...)
  ee steps set <id> <step> <state>    force a step's state (e.g. after checking Facebook by hand)
  ee steps retry [step]               put failed steps back in the queue
  ee wallet init | show               the server's aicoin wallet
  ee home [refresh|layout|graph]      embeddings and Home layout now / print them
  ee importance [--n N]               score importance for items analyzed before it existed
  ee backup                           back up every part's databases to S3 now
  ee restore [--date D] [--dry-run]   restore them (use deploy/restore-state.sh, which stops services)
  ee admin-token                      check that earth-empire/admin-token exists (never prints it)
  ee delete <id>... | --tests         remove items for good (--tests: every ig_test_* fixture)
"""
from __future__ import annotations

import argparse
import json
import sys

from . import db, store
from .logs import setup


def main(argv=None):
    setup("cli")
    ap = argparse.ArgumentParser(prog="ee", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("status"); p.add_argument("--json", action="store_true")
    sub.add_parser("estimate")
    p = sub.add_parser("analyze"); p.add_argument("ids", nargs="*"); p.add_argument("--next", type=int, default=0)
    p.add_argument("--dry-run", action="store_true")
    for name in ("x", "facebook"):
        p = sub.add_parser(name); p.add_argument("action", choices=["dry-run", "post", "check"])
        p.add_argument("id", nargs="?"); p.add_argument("--id", dest="opt_id"); p.add_argument("--n", type=int, default=1)
    p = sub.add_parser("settings"); p.add_argument("key", nargs="?"); p.add_argument("value", nargs="?")
    p = sub.add_parser("steps"); p.add_argument("action", choices=["set", "retry"]); p.add_argument("rest", nargs="*")
    p = sub.add_parser("wallet"); p.add_argument("action", choices=["init", "show"])
    p = sub.add_parser("home"); p.add_argument("action", nargs="?", default="refresh", choices=["refresh", "layout", "graph", "full"])
    p = sub.add_parser("importance"); p.add_argument("--n", type=int, default=1000)
    sub.add_parser("backup")
    p = sub.add_parser("restore"); p.add_argument("--date"); p.add_argument("--only"); p.add_argument("--dry-run", action="store_true")
    sub.add_parser("unpublish-rule")
    p = sub.add_parser("delete"); p.add_argument("ids", nargs="*"); p.add_argument("--tests", action="store_true")
    a = ap.parse_args(argv)
    if a.cmd in ("backup", "restore"):   # never hold the database open around these
        from . import backup
        if a.cmd == "backup":
            print("\n".join(backup.backup_all()))
        else:
            for f in backup.restore_all(date=a.date, only=a.only, dry_run=a.dry_run):
                print(json.dumps(f))
        return 0
    c = db.conn()

    if a.cmd == "status":
        st = store.pipeline_status(c)
        if a.json:
            print(json.dumps(st, indent=2, ensure_ascii=False))
            return
        print(f"items: {st['items']}")
        for step, states in st["steps"].items():
            print(f"  {step:9} " + "  ".join(f"{k}={v}" for k, v in sorted(states.items())))
        r = st["last_collector_run"]
        print("last collector run:", f"{r['finished_at']} ok={bool(r['ok'])} {r['counts']}" if r else "none")
        s = st["spend_24h"]
        print(f"spend 24h: {s['n']} calls, {s['coins']:.0f} coins, ${s['usd']:.2f}")
        if st["failures"]:
            print("latest failures:")
            for f in st["failures"]:
                print(f"  {f['updated_at']} {f['item_id']} {f['step']} x{f['attempts']} "
                      f"next {f['next_at'] or 'never'}: {(f['last_error'] or '')[:160]}")
    elif a.cmd == "estimate":
        from . import analysis
        print(json.dumps(analysis.estimate(c), indent=2))
    elif a.cmd == "analyze":
        from . import analysis
        ids = list(a.ids)
        if a.next:
            ids += [r["item_id"] for r in c.execute(
                """SELECT s.item_id FROM steps s JOIN items i ON i.id=s.item_id WHERE s.step='analyze'
                   AND s.state IN ('pending','failed') ORDER BY i.taken_at LIMIT ?""", (a.next,))]
        for i in ids:
            try:
                if not a.dry_run:
                    store.set_step(c, i, "analyze", "running", note="cli")
                res = analysis.analyze(c, i, dry_run=a.dry_run)
                print(json.dumps(res, ensure_ascii=False))
            except Exception as e:
                if not a.dry_run:
                    store.fail_step(c, i, "analyze", f"{type(e).__name__}: {e}")
                print(f"{i}: FAILED {type(e).__name__}: {e}", file=sys.stderr)
    elif a.cmd == "x":
        from . import xposter
        ids = [a.id or a.opt_id] if (a.id or a.opt_id) else [r["item_id"] for r in c.execute(
            """SELECT s.item_id FROM steps s JOIN items i ON i.id=s.item_id WHERE s.step='x' AND s.state IN
               ('pending','failed') AND i.published_at IS NOT NULL ORDER BY i.taken_at LIMIT ?""", (a.n,))]
        for i in ids:
            if a.action == "dry-run":
                xposter.post_item(c, i, dry_run=True)
            elif a.action == "post":
                store.set_step(c, i, "x", "running", note="cli")
                try:
                    print(xposter.post_item(c, i, dry_run=False))
                except Exception as e:
                    store.fail_step(c, i, "x", str(e))
                    raise
    elif a.cmd == "facebook":
        from . import fbposter
        if a.action == "check":
            state = fbposter.session_state()
            if not state:
                print("earth-empire/facebook-session holds no session")
                return 1
            with fbposter.profile_lock():
                b = fbposter.Browser(state)
                try:
                    b.open_home()
                    print("logged in; screenshot", b.shot("check"))
                except fbposter.FacebookError as e:
                    print("NOT usable:", e)
                    return 1
                finally:
                    b.close()
            return 0
        ids = [a.id or a.opt_id] if (a.id or a.opt_id) else [r["item_id"] for r in c.execute(
            """SELECT s.item_id FROM steps s JOIN items i ON i.id=s.item_id WHERE s.step='facebook' AND s.state IN
               ('pending','failed') AND i.published_at IS NOT NULL ORDER BY i.taken_at LIMIT ?""", (a.n,))]
        for i in ids:
            if a.action == "dry-run":
                print(fbposter.post_item(c, i, dry_run=True))
            else:
                store.set_step(c, i, "facebook", "running", note="cli")
                print(fbposter.post_item(c, i, dry_run=False))
    elif a.cmd == "settings":
        if a.key and a.value is not None:
            if a.key not in db.DEFAULT_SETTINGS and a.key != "facebook.next_at":
                print(f"unknown setting {a.key}", file=sys.stderr)
                return 2
            db.set_setting(c, a.key, a.value)
            from .logs import event
            event("settings.changed", key=a.key, value=a.value)
        for r in c.execute("SELECT key, value FROM settings WHERE key LIKE ? ORDER BY key", ((a.key or "") + "%",)):
            print(f"{r['key']} = {r['value']}")
    elif a.cmd == "steps":
        if a.action == "set":
            item_id, step, state = a.rest
            store.set_step(c, item_id, step, state, note="set by hand")
        else:
            step = a.rest[0] if a.rest else None
            rows = c.execute("SELECT item_id, step FROM steps WHERE state='failed'" + (" AND step=?" if step else ""),
                             (step,) if step else ()).fetchall()
            for r in rows:
                store.set_step(c, r["item_id"], r["step"], "pending", note="retry by hand")
            print(f"requeued {len(rows)}")
    elif a.cmd == "wallet":
        from . import aicoin, config
        s = config.secret("claude", fresh=True)
        s = s if isinstance(s, dict) else {}
        if a.action == "init":
            if s.get("wallet_private_key"):
                print("a wallet exists already:", s.get("wallet_address"))
            else:
                addr, priv = aicoin.new_wallet()
                s = {k: v for k, v in s.items() if k != "placeholder"}
                s.update({"wallet_address": addr, "wallet_private_key": priv,
                          "proxy_url": s.get("proxy_url") or aicoin.DEFAULT_PROXY,
                          "model": s.get("model") or aicoin.DEFAULT_MODEL})
                config.put_secret("claude", s)
                print("created wallet", addr, "(key stored only in earth-empire/claude)")
        addr = s.get("wallet_address")
        if addr:
            print(json.dumps(aicoin.balance(addr), indent=2))
    elif a.cmd == "home":
        from . import home
        if a.action == "full":
            for half in ("top", "bottom"):
                db.set_setting(c, f"home.full_layout_n.{half}", "0")
                c.execute("DELETE FROM layout WHERE half=?", (half,))
        if a.action in ("refresh", "full"):
            while home.update_embeddings(c):
                pass
            print(json.dumps(home.update_layout(c)))
            db.set_setting(c, "home.layout_at", db.now())
        elif a.action == "layout":
            print(json.dumps(home.layout(c), indent=1)[:4000])
        else:
            print(json.dumps(home.tag_graph(c), indent=1)[:4000])
    elif a.cmd == "importance":
        from . import importance
        for r in importance.run(c, a.n):
            print(json.dumps(r, ensure_ascii=False))
    elif a.cmd == "unpublish-rule":
        n = 0
        for r in c.execute("SELECT id, published_at FROM items WHERE analysis IS NOT NULL").fetchall():
            with db.tx(c):
                public, why = store.gate(c, r["id"])
            if r["published_at"] and not public:
                print("unpublished", r["id"], "-", why)
                n += 1
        if n:
            db.set_setting(c, "site.force", db.now())   # the worker rebuilds the site without them
        print(f"{n} unpublished; public now:",
              c.execute("SELECT COUNT(*) FROM items WHERE published_at IS NOT NULL").fetchone()[0])
    elif a.cmd == "delete":
        ids = list(a.ids)
        if a.tests:
            ids += [r["id"] for r in c.execute("SELECT id FROM items WHERE id LIKE 'ig\\_test\\_%' ESCAPE '\\'")]
        for i in ids:
            print(store.delete_item(c, i))
        if a.tests:
            c.execute("DELETE FROM highlights WHERE id LIKE 'hl\\_test\\_%' ESCAPE '\\'")
        db.set_setting(c, "site.force", db.now())
        from .logs import event
        event("items.deleted", ids=ids)
        print(f"deleted {len(ids)}: {ids}")
    return 0


if __name__ == "__main__":
    sys.exit(main() or 0)
