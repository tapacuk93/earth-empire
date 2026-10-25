"""Step 2 of the pipeline: Claude analyzes an item (CONTRACT.md "Analysis").

For each item: every image, frames sampled across every video with their timestamps, a transcript
of the speech, all metadata, the evolving category taxonomy and what earlier items established
(people the owner named, places, series). Claude answers through a forced tool call, so the
result is structured JSON. People are named only from the post's own signals or from a name
the owner gave earlier, never by how a face looks.
"""
from __future__ import annotations

import base64
import json
import logging
import math
import os
import re
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

from . import aicoin, config, store
from .db import j, now, setting, tx
from .logs import event, metric

MAX_FRAMES = 16
MIN_FRAMES = 4
FRAME_EVERY_S = 3.0
IMAGE_EDGE = 1568
FRAME_EDGE = 768
CONTEXT_ITEMS = 30
MAX_NEW_CATEGORIES = 2

RATES = {  # USD per million tokens (input, output): what the proxy meters at
    "claude-opus": (5.0, 25.0), "claude-sonnet": (3.0, 15.0), "claude-haiku": (1.0, 5.0)}


def usd_for(model: str, usage: dict) -> float:
    rin, rout = next((v for k, v in RATES.items() if model.startswith(k)), (3.0, 15.0))
    tin = usage.get("input_tokens", 0) + 1.25 * usage.get("cache_creation_input_tokens", 0) \
        + 0.1 * usage.get("cache_read_input_tokens", 0)
    return (tin * rin + usage.get("output_tokens", 0) * rout) / 1e6


# ------------------------------------------------------------------ media
class Media:
    def __init__(self, work: Path):
        self.work = work
        self._s3 = None

    def fetch(self, url_or_key: str, name: str) -> Path:
        dest = self.work / name
        key = store.media_key(url_or_key)
        local = os.environ.get("EE_MEDIA_LOCAL")    # tests: a directory mirroring the bucket
        if key and local and (Path(local) / key).exists():
            shutil.copy(Path(local) / key, dest)
        elif key:
            if self._s3 is None:
                import boto3
                self._s3 = boto3.client("s3", region_name=config.REGION)
            self._s3.download_file(config.MEDIA_BUCKET, key, str(dest))
        else:
            import httpx
            with httpx.stream("GET", url_or_key, timeout=120, follow_redirects=True) as r:
                r.raise_for_status()
                with open(dest, "wb") as f:
                    for chunk in r.iter_bytes():
                        f.write(chunk)
        return dest


def run(cmd: list[str], timeout=300) -> str:
    p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    if p.returncode != 0:
        raise RuntimeError(f"{cmd[0]} failed: {p.stderr[-800:]}")
    return p.stdout


def probe(path: Path) -> dict:
    out = json.loads(run(["ffprobe", "-v", "error", "-print_format", "json", "-show_format", "-show_streams", str(path)]))
    streams = out.get("streams", [])
    return {"duration": float(out.get("format", {}).get("duration") or 0),
            "has_audio": any(s.get("codec_type") == "audio" for s in streams),
            "has_video": any(s.get("codec_type") == "video" and s.get("codec_name") not in ("mjpeg", "png")
                             for s in streams)}


def jpeg(src: Path, dest: Path, edge: int, at: float | None = None) -> bytes:
    cmd = ["ffmpeg", "-v", "error", "-y"]
    if at is not None:
        cmd += ["-ss", f"{at:.2f}"]
    cmd += ["-i", str(src), "-frames:v", "1",
            "-vf", f"scale={edge}:{edge}:force_original_aspect_ratio=decrease", "-q:v", "4", str(dest)]
    run(cmd)
    if not dest.exists() or dest.stat().st_size == 0:   # e.g. a seek past the last decodable frame
        raise RuntimeError(f"ffmpeg wrote no frame at {at}")
    return dest.read_bytes()


def frame_times(duration: float) -> list[float]:
    n = max(MIN_FRAMES, min(MAX_FRAMES, math.ceil(duration / FRAME_EVERY_S))) if duration > 0 else 1
    return [round((i + 0.5) * duration / n, 2) for i in range(n)] if duration > 0 else [0.0]


def extract_audio(src: Path, dest: Path) -> Path | None:
    try:
        run(["ffmpeg", "-v", "error", "-y", "-i", str(src), "-vn", "-ac", "1", "-ar", "16000", "-b:a", "32k", str(dest)])
    except RuntimeError:
        return None
    return dest if dest.exists() and dest.stat().st_size > 2000 else None


# ------------------------------------------------------------------ prompt
SYSTEM = """You analyze one item from the owner's own Instagram account for Earth Empire, the \
project that publishes it on its website, apps, X and Facebook. You see every image, frames sampled from every \
video (each labelled with its time in seconds), a transcript of the speech, and all metadata.

Rules:
- People. Name a person ONLY from this item's own signals: photo tags, @mentions, the caption, \
speech in the transcript, on-screen text, stickers - or from a name the owner gave earlier, when \
this item's own text links to it (the same @handle, the same nickname or relation such as "my \
sister" that an earlier item tied to a name). NEVER identify anyone from how their face or body \
looks, not even a celebrity, and never because they resemble someone in an earlier item. If no \
signal names a person, set who to null and describe them neutrally (clothing, role, position). \
"basis" says which signal named them, or "description only".
- Be factual. Say what is visible or stated; mark guesses as guesses ("probably"). Use the \
location, date and caption, and earlier items for recurring places and series.
- Transcripts come from automatic speech recognition and may contain errors, or lyrics, or \
nothing real at all over music; use them with care.
- Times in "events" and "appears" are seconds within that media item's video.
- Categories: reuse existing slugs whenever one fits. Add a new category only when nothing \
existing fits and it would plausibly apply to other items of this account; at most 2 new ones. \
Slugs are lowercase-ascii-with-hyphens, broad topics (travel, food, family, music...), not \
one-off details. 1 to 4 categories per item.
- summary: one plain sentence. description: 2-4 clear, complete sentences written for the \
public page and social posts - who, what, where and context, in the caption's language when the \
caption is not English, otherwise English. The date, the highlight names and the original caption \
are always shown next to it, so do not repeat them or quote the caption. For a repost, describe \
the original and credit its author. Never invent names, never speculate about private matters. \
Proofread it: no fragments, no stray punctuation.
- importance: 0 to 1, scored by the importance rubric at the end of these instructions.
Answer with the JSON object the response format asks for."""

APPEARS = {"type": "array", "items": {"type": "object", "properties": {
    "media": {"type": "integer"}, "from": {"type": "number"}, "to": {"type": "number"}}, "required": ["media"]}}

TOOL = {
    "name": "record_analysis",
    "description": "Record the analysis of the item.",
    "input_schema": {
        "type": "object",
        "properties": {
            "people": {"type": "array", "items": {"type": "object", "properties": {
                "who": {"type": ["string", "null"], "description": "@username or a name, only from the item's signals; else null"},
                "description": {"type": "string"},
                "basis": {"type": "string", "enum": ["tag", "mention", "caption", "speech", "on-screen text",
                                                    "sticker", "earlier item", "description only"]},
                "role": {"type": "string"}, "appears": APPEARS},
                "required": ["who", "description", "basis"]}},
            "what": {"type": "string"},
            "events": {"type": "array", "items": {"type": "object", "properties": {
                "media": {"type": "integer"}, "at": {"type": "number"}, "text": {"type": "string"}},
                "required": ["media", "at", "text"]}},
            "when": {"type": "object", "properties": {k: {"type": "string"} for k in
                                                       ("date", "time_of_day", "season", "occasion", "basis")}},
            "where": {"type": "object", "properties": {k: {"type": "string"} for k in
                                                        ("place", "kind", "country", "basis")}},
            "objects": {"type": "array", "items": {"type": "string"}},
            "animals": {"type": "array", "items": {"type": "string"}},
            "brands": {"type": "array", "items": {"type": "string"}},
            "on_screen_text": {"type": "array", "items": {"type": "string"}},
            "speech": {"type": ["object", "null"], "properties": {
                "language": {"type": "string"}, "transcript": {"type": "string"}}},
            "music": {"type": ["string", "null"]},
            "mood": {"type": "string"},
            "language": {"type": "string", "description": "main language of the item's text and speech"},
            "context": {"type": "string"},
            "keywords": {"type": "array", "items": {"type": "string"}},
            "categories": {"type": "array", "items": {"type": "string"}, "minItems": 1, "maxItems": 4},
            "new_categories": {"type": "array", "maxItems": MAX_NEW_CATEGORIES, "items": {"type": "object", "properties": {
                "slug": {"type": "string"}, "name": {"type": "string"}, "description": {"type": "string"}},
                "required": ["slug", "name", "description"]}},
            "summary": {"type": "string"},
            "description": {"type": "string"},
            "importance": {"type": "number", "description": "0 to 1, how significant the moment or content is"},
            "covers": {"type": "array", "description": "For each video: the time of the sampled frame that "
                       "looks best as its cover - sharp, well lit, representative of the video, not blank, "
                       "blurred or mid-transition.", "items": {"type": "object", "properties": {
                           "media": {"type": "integer"}, "at": {"type": "number"}}, "required": ["media", "at"]}},
        },
        "required": ["people", "what", "when", "where", "mood", "language", "context", "keywords",
                     "categories", "summary", "description", "importance"],
    },
}


def _meta(d: dict) -> dict:
    keep = ("kind", "taken_at", "caption", "hashtags", "mentions", "tagged_users", "location", "music",
            "alt_text", "stickers", "counts", "highlights", "source_url", "extra")
    out = {k: d.get(k) for k in keep if d.get(k) not in (None, [], {}, "")}
    rep = d.get("repost_of")
    if rep:
        out["repost_of"] = {k: v for k, v in rep.items() if k != "media" and v not in (None, [], {}, "")}
    return out


def earlier_context(c, item_id: str, taken_at: str) -> dict:
    cats = [dict(r) for r in c.execute("""SELECT c.slug, c.name, c.description, COUNT(ic.item_id) n
        FROM categories c LEFT JOIN item_categories ic ON ic.slug=c.slug GROUP BY c.slug ORDER BY n DESC""")]
    recent = []
    for r in c.execute("""SELECT id, kind, taken_at, summary, categories FROM items WHERE analysis IS NOT NULL
            AND id != ? ORDER BY ABS(julianday(taken_at) - julianday(?)) LIMIT ?""", (item_id, taken_at, CONTEXT_ITEMS)):
        recent.append({"id": r["id"], "kind": r["kind"], "date": r["taken_at"][:10], "summary": r["summary"],
                       "categories": json.loads(r["categories"])})
    recent.sort(key=lambda x: x["date"])
    named: dict[str, dict] = {}
    places: dict[str, int] = {}
    for r in c.execute("SELECT id, taken_at, analysis FROM items WHERE analysis IS NOT NULL AND id != ?", (item_id,)):
        a = json.loads(r["analysis"])
        for p in a.get("people") or []:
            if p.get("who") and p.get("basis") != "description only":
                e = named.setdefault(p["who"], {"who": p["who"], "items": 0, "how_named": set(), "roles": set()})
                e["items"] += 1
                e["how_named"].add(p.get("basis") or "")
                if p.get("role"):
                    e["roles"].add(p["role"][:60])
        w = (a.get("where") or {}).get("place")
        if w:
            places[w] = places.get(w, 0) + 1
    people = sorted(named.values(), key=lambda e: -e["items"])[:60]
    for e in people:
        e["how_named"], e["roles"] = sorted(e["how_named"]), sorted(e["roles"])[:4]
    return {"categories": cats, "nearby_items": recent, "people_named_earlier": people,
            "recurring_places": sorted(places, key=lambda k: -places[k])[:40]}


# ------------------------------------------------------------------ analyze one item
def _progress(c, job, text):
    if job:
        store.job_progress(c, job, text)


def build_request(c, item_id: str, work: Path, job: str | None = None) -> tuple[dict, dict]:
    row = c.execute("SELECT * FROM items WHERE id=?", (item_id,)).fetchone()
    if not row:
        raise LookupError(item_id)
    d = json.loads(row["data"])
    media = Media(work)
    content: list[dict] = []
    info = {"images": 0, "frames": 0, "audio_s": 0.0, "transcripts": [], "coins": 0.0, "videos": []}
    meta = _meta(d)
    content.append({"type": "text", "text": "Item metadata (JSON):\n" + j(meta)})
    groups = [("", "", d.get("media") or [])]
    if d.get("repost_of"):
        groups.append(("original (repost of @%s) " % d["repost_of"].get("author", "?"), "r",
                       d["repost_of"].get("media") or []))
    n = 0
    for label, prefix, items in groups:
        for local_n, m in enumerate(items):
            src_url = m.get("url")
            if not src_url:
                continue
            ext = Path(store.media_key(src_url) or src_url).suffix or (".mp4" if m.get("type") == "video" else ".jpg")
            _progress(c, job, f"downloading media {n + 1}")
            src = media.fetch(src_url, f"m{n}{ext}")
            if m.get("type") == "video":
                pr = probe(src)
                dur = pr["duration"] or (m.get("duration") or 0)
                content.append({"type": "text", "text": f"Media {n} - {label}video, {dur:.1f} s. Frames follow:"})
                times = frame_times(dur)
                _progress(c, job, f"sampling {len(times)} frames from media {n + 1} ({dur:.0f} s)")
                info["videos"].append({"n": n, "key": f"{prefix}{local_n}", "src": src, "times": times})
                for k, t in enumerate(times):
                    try:
                        data = jpeg(src, work / f"f{n}_{k}.jpg", FRAME_EDGE, at=t)
                    except RuntimeError:
                        continue
                    content.append({"type": "text", "text": f"media {n} at {t:.1f} s"})
                    content.append({"type": "image", "source": {"type": "base64", "media_type": "image/jpeg",
                                                                "data": base64.b64encode(data).decode()}})
                    info["frames"] += 1
                if pr["has_audio"]:
                    audio = extract_audio(src, work / f"a{n}.mp3")
                    mkey = store.media_key(src_url) or src_url
                    cached = c.execute("SELECT * FROM transcripts WHERE media=?", (mkey,)).fetchone()
                    if cached:
                        tr = {"language": cached["language"], "text": cached["text"],
                              "segments": json.loads(cached["segments"])}
                        coins = 0.0
                    elif audio:
                        _progress(c, job, f"transcribing the speech in media {n + 1}")
                        tr, coins = aicoin.transcribe(str(audio))
                        c.execute("INSERT OR REPLACE INTO transcripts(media, language, text, segments, created_at) "
                                  "VALUES (?,?,?,?,?)", (mkey, tr.get("language"), tr.get("text"),
                                                         j(tr.get("segments") or []), now()))
                    if cached or audio:
                        info["coins"] += coins
                        info["audio_s"] += dur
                        segs = [f"[{s.get('start', 0):.1f}-{s.get('end', 0):.1f}] {s.get('text', '').strip()}"
                                for s in tr.get("segments") or []]
                        text = "\n".join(segs) or (tr.get("text") or "").strip()
                        info["transcripts"].append({"media": n, "language": tr.get("language"), "text": tr.get("text")})
                        content.append({"type": "text", "text": f"Transcript of media {n} (automatic, language guess "
                                                                f"{tr.get('language')}):\n{text or '(no speech)'}"})
                        if not cached:
                            c.execute("INSERT INTO costs(at, item_id, purpose, model, coins, usd, ok, note) "
                                      "VALUES (?,?,?,?,?,?,1,?)", (now(), item_id, "transcribe", "whisper-1", coins,
                                                                  round(dur / 60 * 0.006, 5), f"{dur:.1f}s"))
            else:
                data = jpeg(src, work / f"i{n}.jpg", IMAGE_EDGE)
                content.append({"type": "text", "text": f"Media {n} - {label}image:"})
                content.append({"type": "image", "source": {"type": "base64", "media_type": "image/jpeg",
                                                            "data": base64.b64encode(data).decode()}})
                info["images"] += 1
            n += 1
    ctx = earlier_context(c, item_id, row["taken_at"])
    content.append({"type": "text", "text": "What earlier items established (JSON). Category slugs to reuse, nearby "
                                            "items, people the owner named before and how:\n" + j(ctx)})
    content.append({"type": "text", "text": "Analyze this item now."})
    # Structured outputs: the answer is JSON matching the schema (forced tool use is gone on
    # Sonnet 5.5). Effort medium: this is perception and description, not deep reasoning.
    from . import rubric
    rub = rubric.current(c)
    info["rubric_version"] = rub["version"]
    body = {"max_tokens": 16000, "system": SYSTEM + "\n\nImportance rubric (version %d):\n%s" % (rub["version"], rub["text"]),
            "output_config": {"effort": "medium",
                              "format": {"type": "json_schema", "schema": strict_schema(TOOL["input_schema"])}},
            "messages": [{"role": "user", "content": content}]}
    return body, info


def strict_schema(node):
    """Our schema in the subset structured outputs accept: additionalProperties false on every
    object, no array/number/string constraints, ["x", "null"] spelled as anyOf."""
    if isinstance(node, list):
        return [strict_schema(n) for n in node]
    if not isinstance(node, dict):
        return node
    out = {k: strict_schema(v) for k, v in node.items()
           if k not in ("minItems", "maxItems", "minimum", "maximum", "minLength", "maxLength", "multipleOf")}
    t = out.get("type")
    if isinstance(t, list):
        rest = {k: v for k, v in out.items() if k not in ("type", "description")}
        branches = [dict(rest, type=x) if x != "null" else {"type": "null"} for x in t]
        for b in branches:
            if b["type"] != "object":
                b.pop("properties", None)
                b.pop("required", None)
            if b["type"] == "object":
                b["additionalProperties"] = False
        out = {"anyOf": branches}
        if node.get("description"):
            out["description"] = node["description"]
        return out
    if t == "object":
        out["additionalProperties"] = False
    return out


SLUG_RE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")


def slugify(s: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")
    return s[:40]


def apply_result(c, item_id: str, out: dict, model: str) -> list[str]:
    ts = now()
    with tx(c):
        existing = {r["slug"] for r in c.execute("SELECT slug FROM categories")}
        added = []
        for nc in (out.get("new_categories") or [])[:MAX_NEW_CATEGORIES]:
            slug = slugify(nc.get("slug") or nc.get("name") or "")
            if slug and slug not in existing:
                c.execute("INSERT INTO categories(slug, name, description, created_at, created_by_item) VALUES (?,?,?,?,?)",
                          (slug, (nc.get("name") or slug)[:60], (nc.get("description") or "")[:300], ts, item_id))
                existing.add(slug)
                added.append(slug)
        cats = []
        for s in out.get("categories") or []:
            s = slugify(s)
            if s and s not in existing and len(added) < MAX_NEW_CATEGORIES:
                # used without being declared as new: create it rather than drop it
                c.execute("INSERT INTO categories(slug, name, description, created_at, created_by_item) VALUES (?,?,?,?,?)",
                          (s, s.replace("-", " ").title(), "", ts, item_id))
                existing.add(s)
                added.append(s)
            if s in existing and s not in cats:
                cats.append(s)
        analysis = {k: out.get(k) for k in ("people", "what", "events", "when", "where", "objects", "animals", "brands",
                                            "on_screen_text", "speech", "music", "mood", "language", "context",
                                            "keywords")}
        analysis.update({"model": model, "analyzed_at": ts})
        imp = out.get("importance")
        imp = min(1.0, max(0.0, float(imp))) if isinstance(imp, (int, float)) else None
        data = json.loads(c.execute("SELECT data FROM items WHERE id=?", (item_id,)).fetchone()["data"])
        c.execute("""UPDATE items SET analysis=?, categories=?, summary=?, description=?, importance=? WHERE id=?""",
                  (j(analysis), j(cats), out.get("summary"), out.get("description"), imp, item_id))
        c.execute("DELETE FROM item_categories WHERE item_id=?", (item_id,))
        for s in cats:
            c.execute("INSERT INTO item_categories VALUES (?,?)", (item_id, s))
        c.execute("DELETE FROM item_tags WHERE item_id=?", (item_id,))
        for tag, kind in tags_for(data, out, cats):
            c.execute("INSERT OR IGNORE INTO item_tags VALUES (?,?,?)", (item_id, tag, kind))
        store.index_item(c, item_id)
        store._set_step(c, item_id, "analyze", "done", note=f"categories {cats}, new {added}")
        # public only when not an image-only repost and the monitor's scan matched (store.gate)
        store.gate(c, item_id)
    return cats


TAG_BASES = {"tag", "mention", "caption"}


def tags_for(d: dict, out: dict, cats: list[str]) -> set[tuple[str, str]]:
    """(tag, kind) pairs for the tag cloud, all lowercase."""
    tags: set[tuple[str, str]] = set()

    def add(value, kind):
        if isinstance(value, str):
            v = " ".join(value.strip().lower().lstrip("#").split())
            # a tag is a word or a short name, not a descriptive phrase
            if 1 < len(v) <= 40 and len(v.split()) <= 4 and not any(ch in v for ch in "()[]:;,"):
                tags.add((v, kind))

    for c_ in cats:
        add(c_, "category")
    for k in out.get("keywords") or []:
        add(k, "keyword")
    for kind, key in (("object", "objects"), ("animal", "animals"), ("brand", "brands")):
        for v in out.get(key) or []:
            add(v, kind)
    where = out.get("where") or {}
    add(where.get("place"), "place")
    add(where.get("country"), "country")
    loc = d.get("location") or {}
    if isinstance(loc, dict):
        add(loc.get("name"), "place")
    for h in d.get("hashtags") or []:
        add(h, "hashtag")
    for p in out.get("people") or []:   # only people the post itself named
        if p.get("who") and p.get("basis") in TAG_BASES:
            add(p["who"], "person")
    add(out.get("mood"), "mood")
    add((out.get("when") or {}).get("occasion"), "occasion")
    return tags


def save_covers(c, item_id: str, picks: list[dict], videos: list[dict]) -> dict:
    """The best-looking frame of each video, at full size, to items/<id>/<n>.cover.jpg."""
    chosen = {p.get("media"): p.get("at") for p in picks or [] if isinstance(p, dict)}
    covers = {}
    for v in videos:
        times = v["times"]
        at = chosen.get(v["n"])
        if not isinstance(at, (int, float)):
            at = times[len(times) // 2]        # nothing chosen: the middle frame
        at = min(times, key=lambda t: abs(t - at))   # snap to a frame Claude actually saw
        key = f"items/{item_id}/{v['key']}.cover.jpg"
        out = v["src"].parent / f"cover-{v['key']}.jpg"
        try:
            jpeg(v["src"], out, 1920, at=at)
            put_media(key, out, "image/jpeg")
            covers[v["key"]] = {"cover": key, "cover_at": at}
        except Exception as e:
            event("analysis.cover_failed", logging.WARNING, item=item_id, media=v["key"], error=str(e))
    c.execute("UPDATE items SET covers=? WHERE id=?", (j(covers), item_id))
    return covers


def put_media(key: str, path: Path, ctype: str) -> None:
    local = os.environ.get("EE_MEDIA_LOCAL")
    if local:
        dest = Path(local) / key
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(path, dest)
        return
    import boto3
    boto3.client("s3", region_name=config.REGION).upload_file(
        str(path), config.MEDIA_BUCKET, key,
        ExtraArgs={"ContentType": ctype, "CacheControl": "public, max-age=86400"})


def analyze(c, item_id: str, *, dry_run: bool = False, job: str | None = None) -> dict:
    """Analyze one item end to end. Raises on failure; the worker records it."""
    t0 = time.time()
    work = Path(tempfile.mkdtemp(prefix="ee-analyze-"))
    try:
        body, info = build_request(c, item_id, work, job)
        model = aicoin.settings()["model"]
        if dry_run:
            imgs = sum(1 for b in body["messages"][0]["content"] if b["type"] == "image")
            return {"item": item_id, "dry_run": True, "images": imgs, **info}
        _progress(c, job, f"asking Claude ({info['images']} images, {info['frames']} frames)")
        resp, coins = aicoin.claude(body)
        usage = resp.get("usage") or {}
        usd = usd_for(resp.get("model") or model, usage)
        c.execute("INSERT INTO costs(at, item_id, purpose, model, input_tokens, output_tokens, coins, usd, ok) "
                  "VALUES (?,?,?,?,?,?,?,?,1)", (now(), item_id, "analyze", resp.get("model") or model,
                                                usage.get("input_tokens"), usage.get("output_tokens"), coins, usd))
        if resp.get("stop_reason") == "refusal":
            raise RuntimeError(f"Claude declined: {resp.get('stop_details')}")
        if resp.get("stop_reason") == "max_tokens":
            raise RuntimeError("the answer hit max_tokens")
        text = "".join(b.get("text", "") for b in resp.get("content") or [] if b.get("type") == "text")
        try:
            out = json.loads(text)
        except ValueError:
            raise RuntimeError(f"the answer is not JSON (stop_reason {resp.get('stop_reason')}): {text[:300]}")
        _progress(c, job, "saving the analysis and covers")
        covers = save_covers(c, item_id, out.get("covers"), info["videos"])
        cats = apply_result(c, item_id, out, resp.get("model") or model)
        c.execute("UPDATE items SET importance_version=?, importance_method=2 WHERE id=?",
                  (info.get("rubric_version"), item_id))
        result = {"item": item_id, "categories": cats, "summary": out.get("summary"),
                  "input_tokens": usage.get("input_tokens"), "output_tokens": usage.get("output_tokens"),
                  "coins": coins + info["coins"], "usd": round(usd, 4), "seconds": round(time.time() - t0, 1),
                  "images": info["images"], "frames": info["frames"], "audio_s": round(info["audio_s"], 1),
                  "covers": covers}
        event("analysis.done", **result)
        metric("AnalysisCoins", coins + info["coins"], unit="None")
        return result
    finally:
        shutil.rmtree(work, ignore_errors=True)


def analyses_today(c) -> int:
    from datetime import datetime, timezone
    day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    return c.execute("SELECT COUNT(*) n FROM costs WHERE purpose='analyze' AND at >= ?", (day,)).fetchone()["n"]


def estimate(c) -> dict:
    """What analyzing everything still pending would cost, from measured averages where they exist."""
    pending = c.execute("""SELECT i.kind, i.data FROM steps s JOIN items i ON i.id=s.item_id
                           WHERE s.step='analyze' AND s.state IN ('pending','failed','running')""").fetchall()
    measured = c.execute("""SELECT COUNT(*) n, AVG(usd) usd, AVG(coins) coins, AVG(input_tokens) tin,
                            AVG(output_tokens) tout FROM costs WHERE purpose='analyze' AND ok=1""").fetchone()
    tr = c.execute("SELECT AVG(coins) coins FROM costs WHERE purpose='transcribe'").fetchone()
    # A priori, per media: an image ~1,600 tokens, a video's frames ~5,500 tokens plus a transcript;
    # prompt and context ~4,000; answer ~1,500 tokens. Sonnet-class rates: $3 in / $15 out per M.
    est_items, videos = 0.0, 0
    for r in pending:
        d = json.loads(r["data"])
        media = (d.get("media") or []) + ((d.get("repost_of") or {}).get("media") or [])
        tin = 4000 + sum(5500 if m.get("type") == "video" else 1600 for m in media)
        videos += sum(1 for m in media if m.get("type") == "video")
        est_items += (tin * 3 + 1500 * 15) / 1e6
    coin = 0.009
    out = {"pending_items": len(pending), "pending_videos": videos,
           "a_priori_usd": round(est_items + videos * 0.003, 2),
           "a_priori_coins": math.ceil((est_items + videos * 0.003) / coin)}
    if measured["n"]:
        per = (measured["usd"] or 0)
        out.update({"measured_items": measured["n"], "measured_usd_per_item": round(per, 4),
                    "measured_coins_per_item": round(measured["coins"] or 0, 1),
                    "measured_tokens_per_item": [round(measured["tin"] or 0), round(measured["tout"] or 0)],
                    "measured_total_usd": round(per * len(pending), 2),
                    "measured_total_coins": math.ceil(((measured["coins"] or 0) + (tr["coins"] or 0)) * len(pending))})
    return out
