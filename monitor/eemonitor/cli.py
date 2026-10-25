"""ee-monitor: the owner's commands on the box.

    ee-monitor status                      queue, usage, stops (as JSON)
    ee-monitor hits [N]                    the most confident hits
    ee-monitor fetch N [platform]          queue at least N more videos
    ee-monitor scan <video id>             scan one video now (in this process)
    ee-monitor scan-url <url> [lang,...]   scan any public video URL (telegram post, facebook video, media file)
    ee-monitor add <platform> <handle> <name> [langs]   add an account (comma-separated languages)
    ee-monitor poll [platform]             poll due accounts now
    ee-monitor resume <platform>           clear a platform's stop
    ee-monitor set <key> <value>           change a setting (caps, model, thresholds)
    ee-monitor phrases [p1 p2 ...]         show or replace the phrases
    ee-monitor rescan                      detection again over stored transcripts
    ee-monitor load-registry               re-read monitor/sources.json
    ee-monitor bench <audio file> [model]  transcription speed on this machine
"""
from __future__ import annotations

import json
import logging
import sys
import time


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    from . import api, db, registry, worker
    if not argv or argv[0] in ("-h", "--help", "help"):
        print(__doc__)
        return 0
    c = db.conn()
    cmd, args = argv[0], argv[1:]
    out = None
    if cmd == "status":
        out = api.status()
    elif cmd == "hits":
        out = [{k: h[k] for k in ("id", "kind", "phrase", "matched", "confidence", "confidence_label", "at_url")}
               | {"excerpt": (h["excerpt"]["text"] or "")[:160], "en": h["excerpt"]["en"]}
               for h in api.hits(limit=int(args[0]) if args else 20, kind=None, platform=None, source_kind=None,
                                 phrase=None, min_confidence=0.0, published=None, sort="confidence", before=None)["hits"]]
    elif cmd == "fetch":
        out = worker.fetch_request(c, int(args[0]), {"platform": args[1] if len(args) > 1 else None})
    elif cmd == "scan":
        worker.setup(c)
        v = c.execute("SELECT * FROM videos WHERE id=?", (args[0],)).fetchone()
        if not v:
            print("no such video")
            return 1
        worker.scan(c, v)
        out = api.videos(limit=1)
    elif cmd == "scan-url":
        worker.setup(c)
        url = args[0]
        langs = args[1].split(",") if len(args) > 1 else []
        sid = "adhoc"
        registry.upsert_source(c, sid, "Ad hoc scans", "official", "owner", langs)
        vid = "url:" + url
        if "t.me/" in url:
            from .platforms import telegram
            post = url.split("t.me/")[1].split("?")[0].strip("/")
            vid = f"tg:{post}"
            v = {"id": vid, "platform": "telegram", "url": f"https://t.me/{post}", "media_url": None,
                 "extra": {"post": post, "index": 0}}
            v["media_url"] = telegram.refresh_media_url(c, v)
        else:
            v = {"id": vid, "platform": "web", "url": url, "media_url": url, "extra": {}}
        worker.insert_video(c, v, None, "official", source_id=sid, queue=True)
        c.execute("UPDATE videos SET state='queued', source_id=? WHERE id=?", (sid, vid))
        worker.scan(c, c.execute("SELECT * FROM videos WHERE id=?", (vid,)).fetchone())
        out = {"video": dict(c.execute("SELECT id, state, error, languages, audio_s, cpu_s FROM videos WHERE id=?", (vid,)).fetchone()),
               "hits": [api.render(c, r) for r in c.execute("SELECT * FROM hits WHERE video_id=? ORDER BY confidence DESC", (vid,))]}
    elif cmd == "add":
        out = registry.add_owner_source(c, {"platform": args[0], "handle": args[1], "name": args[2],
                                            "expected_languages": args[3].split(",") if len(args) > 3 else []})
    elif cmd == "poll":
        worker.setup(c)
        if args:
            c.execute("UPDATE accounts SET next_poll_at=? WHERE platform=?", (db.now(), args[0]))
        out = {"new": worker.discover(c)}
    elif cmd == "resume":
        c.execute("DELETE FROM stops WHERE platform=?", (args[0],))
        if args[0] == "facebook":
            db.set_setting(c, "facebook.password_tried_at", "")
        out = {"ok": True}
    elif cmd == "set":
        db.set_setting(c, args[0], args[1])
        out = {args[0]: db.setting(c, args[0])}
    elif cmd == "phrases":
        out = worker.set_phrases(c, args) if args else worker.list_phrases(c)
    elif cmd == "rescan":
        out = worker.rescan(c)
    elif cmd == "load-registry":
        out = registry.load_file(c)
    elif cmd == "bench":
        from . import transcribe
        t0 = time.time()
        tr = transcribe.transcribe(args[0], args[1] if len(args) > 1 else "small")
        out = {"model": tr["model"], "audio_s": tr["duration"], "speech_s": tr["speech_s"], "wall_s": round(time.time() - t0, 1),
               "cpu_s": tr["cpu_s"], "realtime_factor": round((time.time() - t0) / max(1, tr["duration"]), 3),
               "languages": transcribe.languages(tr),
               "text": " | ".join(ch["text"] for ch in tr["chunks"])[:1500]}
    else:
        print(__doc__)
        return 2
    print(json.dumps(out, ensure_ascii=False, indent=1, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
