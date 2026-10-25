"""Thumbnails (about 640 px on the short side) for every media item that arrived without one,
saved as items/<id>/<n>.thumb.jpg (r<n> for a repost original's media), so grids never load
the originals. Made right after ingest by the worker; existing items are backfilled the same way.
"""
from __future__ import annotations

import json
import logging
import shutil
import tempfile
from pathlib import Path

from . import store
from .analysis import Media, put_media, run
from .db import j
from .logs import event

EDGE = 640


def make_thumb(src: Path, dest: Path, video: bool) -> None:
    scale = f"scale='if(gt(iw,ih),-2,min({EDGE},iw))':'if(gt(iw,ih),min({EDGE},ih),-2)'"
    cmd = ["ffmpeg", "-v", "error", "-y"]
    if video:
        cmd += ["-ss", "1"]
    cmd += ["-i", str(src), "-frames:v", "1", "-vf", scale, "-q:v", "5", str(dest)]
    try:
        run(cmd)
    except RuntimeError:
        if not video:
            raise
        run(["ffmpeg", "-v", "error", "-y", "-i", str(src), "-frames:v", "1", "-vf", scale, "-q:v", "5", str(dest)])


def thumbs_for(c, item_id: str) -> dict:
    row = c.execute("SELECT data FROM items WHERE id=?", (item_id,)).fetchone()
    d = json.loads(row["data"])
    made = {}
    work = Path(tempfile.mkdtemp(prefix="ee-thumb-"))
    try:
        fetch = Media(work)
        for prefix, media in (("", d.get("media") or []), ("r", (d.get("repost_of") or {}).get("media") or [])):
            for n, m in enumerate(media):
                if m.get("thumbnail") or not m.get("url") or not store.media_key(m["url"]):
                    continue
                key = f"items/{item_id}/{prefix}{n}.thumb.jpg"
                src = fetch.fetch(m["url"], f"{prefix}{n}{Path(store.media_key(m['url'])).suffix}")
                out = work / f"{prefix}{n}.thumb.jpg"
                make_thumb(src, out, m.get("type") == "video")
                put_media(key, out, "image/jpeg")
                made[f"{prefix}{n}"] = key
                src.unlink(missing_ok=True)
    finally:
        shutil.rmtree(work, ignore_errors=True)
    c.execute("UPDATE items SET thumbs=? WHERE id=?", (j(made), item_id))
    event("thumbs.done", item=item_id, made=len(made))
    return made


def next_without(c) -> str | None:
    r = c.execute("SELECT id FROM items WHERE thumbs IS NULL ORDER BY taken_at DESC LIMIT 1").fetchone()
    return r["id"] if r else None
