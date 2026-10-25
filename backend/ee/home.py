"""The Home screen's data (CONTRACT.md "Home layout"): two zoomable mosaics and a tag graph.

- Halves: `top` holds items from the owner's dedicated highlights (small, distinct ones) and the
  published monitor hits filed under `dedicated`; `bottom` holds everything else (the big catch-all
  highlights, items in no highlight) and hits filed under `common`. Which highlights are dedicated
  is the owner's choice, kept by the monitor (`home.dedicated_highlights`); until it is made,
  highlights that hold at most 30 items and under a quarter of all highlighted items count as
  dedicated.
- Similarity: every published item and hit gets an embedding of its description and analysis from
  an open-source multilingual sentence model (paraphrase-multilingual-MiniLM-L12-v2 through
  fastembed/ONNX, on the box, no paid API).
- Places: a seeded t-SNE per half the first time (and whenever a half has doubled since its last
  full layout, aligned to the old places by Procrustes so the picture does not jump). In between,
  a new tile is placed at the similarity-weighted centre of its nearest neighbours and nothing
  else moves.
- Size: recency leads, importance scales it; the kind of item never matters.
"""
from __future__ import annotations

import hashlib
import json
import logging
import math
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path

from . import config
from .db import now, set_setting, setting, tx
from .logs import event

MODEL = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
MONITOR_DB = Path("/var/lib/earth-empire/monitor/monitor.sqlite3")
MODEL_DIR = config.DATA_DIR / "models"
NEIGHBOURS = 5
RECENCY_HALF_LIFE_DAYS = 365.0

_model = None
_model_lock = threading.Lock()


# ------------------------------------------------------------------ inputs
def monitor_conn():
    if not MONITOR_DB.exists():
        return None
    try:
        return sqlite3.connect(f"file:{MONITOR_DB}?mode=ro", uri=True, timeout=10)
    except sqlite3.Error:
        return None


def dedicated_highlights(c) -> set[str]:
    m = monitor_conn()
    if m:
        try:
            r = m.execute("SELECT value FROM settings WHERE key='home.dedicated_highlights'").fetchone()
            if r and r[0]:
                ids = json.loads(r[0])
                if ids:
                    return set(ids)
        except (sqlite3.Error, ValueError):
            pass
        finally:
            m.close()
    sizes = {r["id"]: len(json.loads(r["item_ids"] or "[]")) for r in c.execute("SELECT id, item_ids FROM highlights")}
    counted: dict[str, int] = {}   # the collector may name highlights only on the items themselves
    for (d,) in c.execute("SELECT data FROM items"):
        for h in json.loads(d).get("highlights") or []:
            if isinstance(h, dict) and h.get("id"):
                counted[h["id"]] = counted.get(h["id"], 0) + 1
    for h, n in counted.items():
        sizes[h] = max(sizes.get(h, 0), n)
    total = sum(sizes.values()) or 1
    return {h for h, n in sizes.items() if n <= 30 and n < 0.25 * total}


def published_hits() -> list[dict]:
    m = monitor_conn()
    if not m:
        return []
    try:
        cols = {r[1] for r in m.execute("PRAGMA table_info(hits)")}
        extra = ", ".join(c for c in ("level", "level_by") if c in cols) or "NULL"
        rows = m.execute(f"SELECT id, data, published_at, section, {extra} FROM hits "
                         "WHERE published_at IS NOT NULL").fetchall()
    except sqlite3.Error:
        return []
    finally:
        m.close()
    out = []
    for row in rows:
        hid, data, pub, section = row[:4]
        try:
            d = json.loads(data or "{}")
        except ValueError:
            d = {}
        level = row[4] if len(row) > 4 else None
        level_by = row[5] if len(row) > 5 else None
        out.append({"id": hid, "data": d, "published_at": pub, "section": section,
                    "level": level if level in (1, 2, 3, 4) else None, "level_by": level_by})
    return out


def item_text(row) -> str:
    d = json.loads(row["data"])
    a = json.loads(row["analysis"] or "{}")
    parts = [row["summary"] or "", row["description"] or "", a.get("what") or "", a.get("context") or "",
             " ".join(a.get("keywords") or []), " ".join(json.loads(row["categories"] or "[]")),
             (a.get("where") or {}).get("place") or "", (d.get("caption") or "")[:600]]
    rep = d.get("repost_of") or {}
    if isinstance(rep, dict):
        parts.append((rep.get("caption") or "")[:300])
    return "\n".join(p for p in parts if p)[:2000]


def hit_text(h: dict) -> str:
    d = h["data"]
    ex = d.get("excerpt") or {}
    src = d.get("source") or {}
    return "\n".join(x for x in [(d.get("video") or {}).get("title") or "", ex.get("en") or ex.get("text") or "",
                                 src.get("name") or "", d.get("account") or ""] if x)[:2000]


# ------------------------------------------------------------------ embeddings
def model():
    global _model
    with _model_lock:
        if _model is None:
            from fastembed import TextEmbedding
            MODEL_DIR.mkdir(parents=True, exist_ok=True)
            _model = TextEmbedding(model_name=MODEL, cache_dir=str(MODEL_DIR), threads=1)
        return _model


def embed_texts(texts: list[str]):
    import numpy as np
    vecs = np.array(list(model().embed(texts, batch_size=16)), dtype=np.float32)
    vecs /= np.linalg.norm(vecs, axis=1, keepdims=True) + 1e-9
    return vecs


def update_embeddings(c, batch: int = 32) -> int:
    """Embed published items and hits whose text changed. Returns how many were embedded."""
    have = {r["id"]: r["text_hash"] for r in c.execute("SELECT id, text_hash FROM embeddings")}
    todo = []
    for r in c.execute("SELECT * FROM items WHERE published_at IS NOT NULL"):
        t = item_text(r)
        h = hashlib.sha256(t.encode()).hexdigest()[:16]
        if have.get(r["id"]) != h:
            todo.append((r["id"], "item", t, h))
    for hit in published_hits():
        t = hit_text(hit)
        h = hashlib.sha256(t.encode()).hexdigest()[:16]
        if have.get("hit:" + hit["id"]) != h:
            todo.append(("hit:" + hit["id"], "hit", t, h))
    todo = todo[:batch]
    if not todo:
        return 0
    vecs = embed_texts([t for _, _, t, _ in todo])
    with tx(c):
        for (i, kind, _, h), v in zip(todo, vecs):
            c.execute("""INSERT INTO embeddings(id, kind, text_hash, vec, updated_at) VALUES (?,?,?,?,?)
                         ON CONFLICT(id) DO UPDATE SET text_hash=excluded.text_hash, vec=excluded.vec,
                         updated_at=excluded.updated_at""", (i, kind, h, v.tobytes(), now()))
    set_setting(c, "home.dirty", now())
    event("home.embedded", n=len(todo))
    return len(todo)


def vectors(c, ids=None):
    import numpy as np
    rows = c.execute("SELECT id, vec FROM embeddings").fetchall()
    out = {r["id"]: np.frombuffer(r["vec"], dtype=np.float32) for r in rows if ids is None or r["id"] in ids}
    return out


# ------------------------------------------------------------------ placement (CONTRACT.md "Home layout")
OWN_DEFAULT = 1.0   # a post of the owner's own


def weights(c) -> dict:
    keys = ("post", "dedicated", "shared", "repost", "story", "hit_top", "hit_bottom")
    return {k: float(setting(c, f"placement.{k}") or 0) for k in keys}


def placement(d: dict, kind: str, hls: list[str], dedicated: set[str], w: dict | None = None) -> tuple[float, str]:
    """Where the item lives: the highest that applies."""
    w = w or {"post": 1, "dedicated": 1, "shared": 0.5, "repost": 0.25, "story": 0.125}
    repost = bool(d.get("repost_of"))
    tab = (d.get("extra") or {}).get("repost_source") == "reposts tab" or str(d.get("id", "")).startswith("ig_repost_")
    rules = []
    if [h for h in hls if h in dedicated]:
        rules.append((w["dedicated"], "in a dedicated highlight"))
    if [h for h in hls if h not in dedicated]:
        rules.append((w["shared"], "in a shared highlight"))
    if tab:
        rules.append((w["repost"], "reposted with Instagram's Repost feature"))
    elif kind != "story" and not repost:
        rules.append((w["post"], "a post"))
    elif kind != "story":
        rules.append((w["repost"], "a repost"))
    if kind == "story" and not hls:
        rules.append((w["story"], "a story in no highlight"))
    if not rules:
        rules.append((w["story"], "a story"))
    return max(rules, key=lambda r: r[0])


curation = placement   # the earlier name


# ------------------------------------------------------------------ members of each half
def members(c) -> dict[str, dict]:
    """id -> {"half", "kind", "taken_at", "importance", "label"} for every published item and hit."""
    ded = dedicated_highlights(c)
    hl_titles = {r["id"]: r["title"] for r in c.execute("SELECT id, title FROM highlights")}
    item_hls: dict[str, list[str]] = {}
    for r in c.execute("SELECT item_id, highlight_id FROM item_highlights"):
        item_hls.setdefault(r["item_id"], []).append(r["highlight_id"])
    out = {}
    from .store import has_video
    W = weights(c)
    for r in c.execute("SELECT id, kind, taken_at, importance, data FROM items WHERE published_at IS NOT NULL"):
        hls = item_hls.get(r["id"], [])
        d = json.loads(r["data"])
        video = has_video(d)
        for h in d.get("highlights") or []:
            if isinstance(h, dict) and h.get("id") and h["id"] not in hls:
                hls.append(h["id"])
                hl_titles.setdefault(h["id"], h.get("title"))
        top = [h for h in hls if h in ded]
        half = "all"   # one panel: a single similarity layout over everything
        cur, why = placement(d, r["kind"], hls, ded, W)
        orig = (d.get("repost_of") or {}).get("taken_at") if isinstance(d.get("repost_of"), dict) else None
        label_hl = (top or hls or [None])[0]
        label = hl_titles.get(label_hl) if label_hl else None
        out[r["id"]] = {"half": half, "kind": "item", "taken_at": r["taken_at"], "video": video,
                        "source": "profile", "level": level_of(cur, W),
                        "original_at": orig or r["taken_at"],
                        "curation": cur, "curation_reason": why,
                        "importance": r["importance"], "label": label or {"reel": "Reels", "story": "Stories"}.get(
                            r["kind"], "Posts")}
    for h in published_hits():
        d = h["data"]
        # the monitor's effective level (AI-chosen or the owner's override); L3 only if it has none yet
        lvl = h.get("level") or (d.get("level") if d.get("level") in (1, 2, 3, 4) else 3)
        lw = {1: W["dedicated"], 2: W["shared"], 3: W["repost"], 4: W["story"]}[lvl]
        out["hit:" + h["id"]] = {"half": "all", "kind": "hit", "video": True, "source": "ai_found", "level": lvl,
                                 "curation": lw,
                                 "curation_reason": ("level L%d set by the owner" % lvl) if h.get("level_by") == "owner"
                                 else "AI-chosen level L%d: %s" % (lvl, (d.get("level_reason") or "rated by the monitor")[:120]),
                                 "original_at": (d.get("video") or {}).get("posted_at") or h["published_at"],
                                 "curation_reason": "detected, published in the top section" if top_hit
                                 else "detected, published in the bottom section",
                                 "taken_at": (d.get("video") or {}).get("posted_at") or h["published_at"],
                                 "importance": d.get("importance") if isinstance(d.get("importance"), (int, float))
                                 else None, "label": (d.get("source") or {}).get("name") or "Detected"}
    return out


# ------------------------------------------------------------------ layout
def _tsne(vecs, seed=42):
    import numpy as np
    n = len(vecs)
    if n == 1:
        return np.array([[0.5, 0.5]])
    if n < 5:   # too few for t-SNE: the first two principal components
        x = vecs - vecs.mean(0)
        u, s, _ = np.linalg.svd(x, full_matrices=False)
        pts = u[:, :2] * s[:2] if u.shape[1] >= 2 else np.c_[u[:, 0] * s[0], np.zeros(n)]
    else:
        from sklearn.manifold import TSNE
        pts = TSNE(n_components=2, perplexity=max(2.0, min(30.0, (n - 1) / 3)), init="pca", metric="cosine",
                   random_state=seed, max_iter=1000).fit_transform(vecs)
    return _normalize(pts)


def _normalize(pts):
    import numpy as np
    lo, hi = pts.min(0), pts.max(0)
    span = np.where(hi - lo > 1e-9, hi - lo, 1.0)
    return 0.05 + 0.9 * (pts - lo) / span


def _align(pts, idx, old):
    """Rotate/reflect/scale all of `pts` so that its rows `idx` land on `old` (orthogonal Procrustes):
    a re-layout keeps the look of the tiles that were already placed."""
    import numpy as np
    sub = pts[idx]
    mu_a, mu_b = sub.mean(0), old.mean(0)
    a, b = sub - mu_a, old - mu_b
    u, s, vt = np.linalg.svd(a.T @ b)
    r = u @ vt
    scale = s.sum() / max((a ** 2).sum(), 1e-9)
    return (pts - mu_a) @ r * scale + mu_b


def update_layout(c) -> dict:
    import numpy as np
    mem = members(c)
    vec = vectors(c)
    placed = {r["id"]: dict(r) for r in c.execute("SELECT * FROM layout")}
    stats = {}
    with tx(c):
        for i in [i for i in placed if i not in mem or i not in vec or not mem[i]["video"]]:
            c.execute("DELETE FROM layout WHERE id=?", (i,))   # unpublished, gone, or an image (attached)
        for i, p in placed.items():   # moved to the other half: place again
            if i in mem and mem[i]["half"] != p["half"]:
                c.execute("DELETE FROM layout WHERE id=?", (i,))
    placed = {r["id"]: dict(r) for r in c.execute("SELECT * FROM layout")}
    for half in ("all",):
        ids = [i for i, m in mem.items() if m["half"] == half and i in vec and m["video"]]
        if not ids:
            continue
        have = [i for i in ids if i in placed]
        new = [i for i in ids if i not in placed]
        last_full = int(setting(c, f"home.full_layout_n.{half}") or 0)
        full = len(have) < 5 or len(ids) >= 2 * max(last_full, 1)
        ts = now()
        if full:
            pts = _tsne(np.stack([vec[i] for i in ids]))
            if len(have) >= 3:
                idx = [ids.index(i) for i in have]
                old = np.array([[placed[i]["x"], placed[i]["y"]] for i in have])
                pts = _align(pts, idx, old)
                pts = np.clip(pts, 0.0, 1.0)
            with tx(c):
                for i, (x, y) in zip(ids, pts):
                    c.execute("""INSERT INTO layout(id, half, x, y, placed, updated_at) VALUES (?,?,?,?,?,?)
                                 ON CONFLICT(id) DO UPDATE SET half=excluded.half, x=excluded.x, y=excluded.y,
                                 placed=excluded.placed, updated_at=excluded.updated_at""",
                              (i, half, float(x), float(y), "full", ts))
            set_setting(c, f"home.full_layout_n.{half}", str(len(ids)))
            stats[half] = {"full": len(ids)}
        elif new:
            base = np.stack([vec[i] for i in have])
            coords = np.array([[placed[i]["x"], placed[i]["y"]] for i in have])
            with tx(c):
                for i in new:
                    sims = base @ vec[i]
                    k = np.argsort(-sims)[:NEIGHBOURS]
                    w = np.clip(sims[k], 0.01, None) ** 2
                    x, y = (coords[k] * w[:, None]).sum(0) / w.sum()
                    jit = int(hashlib.sha256(i.encode()).hexdigest()[:8], 16)
                    x += ((jit & 0xFFFF) / 0xFFFF - 0.5) * 0.04
                    y += ((jit >> 16) / 0xFFFF - 0.5) * 0.04
                    c.execute("INSERT OR REPLACE INTO layout(id, half, x, y, placed, updated_at) VALUES (?,?,?,?,?,?)",
                              (i, half, float(min(max(x, 0), 1)), float(min(max(y, 0), 1)), "near", ts))
            stats[half] = {"placed_near": len(new)}
    if stats:
        event("home.layout", **stats)
    return stats


def attachments(c, mem=None, vec=None) -> dict[str, str]:
    """Each of the account's own images (an item without video) -> its most similar video:
    from the same half when there is one, else from any. Images are never tiles of their own."""
    import numpy as np
    mem = mem or members(c)
    vec = vec if vec is not None else vectors(c, set(mem))
    vids = [i for i, m in mem.items() if m["video"] and i in vec]
    out = {}
    if not vids:
        return out
    V = np.stack([vec[i] for i in vids])
    for i, m in mem.items():
        if m["video"] or i not in vec:
            continue
        sims = V @ vec[i]
        same = [k for k, v in enumerate(vids) if mem[v]["half"] == m["half"]]
        pool = same or list(range(len(vids)))
        best = max(pool, key=lambda k: (sims[k], mem[vids[k]]["taken_at"] or ""))
        out[i] = vids[best]
    return out


def level_of(weight: float, w: dict) -> int:
    """Placement weight -> level: L1 post or dedicated highlight, L2 shared highlight, L3 repost,
    L4 story in no highlight."""
    for lvl, key in ((1, "dedicated"), (2, "shared"), (3, "repost")):
        if weight >= w[key] - 1e-9:
            return lvl
    return 4


def size_params(c) -> dict:
    return {"half_life_days": float(setting(c, "size.half_life_days") or 30),
            "age_floor": float(setting(c, "size.age_floor") or 0.05),
            "importance_w": float(setting(c, "size.importance_w") or 0.15)}


def size_parts(original_at: str | None, importance: float | None, placement_w: float | None, p: dict) -> dict:
    """size = placement × age_factor × importance_factor (CONTRACT.md "Home layout")."""
    try:
        age = (datetime.now(timezone.utc) - datetime.strptime(original_at[:19], "%Y-%m-%dT%H:%M:%S")
               .replace(tzinfo=timezone.utc)).total_seconds() / 86400
    except (TypeError, ValueError):
        age = 3650.0
    age = max(age, 0.0)
    age_factor = max(p["age_floor"], 0.5 ** (age / p["half_life_days"]))
    imp = 0.5 if importance is None else importance
    imp_factor = 1 - p["importance_w"] + p["importance_w"] * imp
    pl = 1.0 if placement_w is None else placement_w
    return {"placement": pl, "age_days": round(age, 1), "age_factor": round(age_factor, 4),
            "importance": importance, "importance_factor": round(imp_factor, 4),
            "size": round(pl * age_factor * imp_factor, 4)}


def layout(c) -> dict:
    mem = members(c)
    vec = vectors(c, set(mem))
    params = size_params(c)
    tiles_out: list = []
    tiles = {}
    for r in c.execute("SELECT * FROM layout"):
        m = mem.get(r["id"])
        if not m:
            continue
        hid = r["id"]
        t = {"id": hid[4:] if hid.startswith("hit:") else hid, "kind": m["kind"],
             "x": round(r["x"], 4), "y": round(r["y"], 4),
             "size": m["curation"], "level": m["level"], "source": m["source"],
             "placement": m["curation"], "placement_reason": m["curation_reason"], "curation": m["curation"],
             "importance": m["importance"],
             "label": m["label"], "taken_at": m["taken_at"]}
        tiles[hid] = t
        tiles_out.append(t)
    # images sit beside their video, smaller, in the video's half
    by_video: dict[str, list] = {}
    for img, vid in attachments(c, mem, vec).items():
        by_video.setdefault(vid, []).append(img)
    for vid, imgs in by_video.items():
        v = tiles.get(vid)
        if not v:
            continue
        imgs.sort(key=lambda i: mem[i]["taken_at"] or "", reverse=True)
        for k, img in enumerate(imgs):
            ang = math.pi / 4 + k * (2 * math.pi / max(len(imgs), 6))
            rad = 0.012 + 0.018 * v["size"]
            tiles_out.append({
                "id": img, "kind": "item", "attached_to": v["id"],
                "x": round(min(max(v["x"] + rad * math.cos(ang), 0), 1), 4),
                "y": round(min(max(v["y"] + rad * math.sin(ang), 0), 1), 4),
                "size": round(v["size"] * 0.45, 4), "curation": mem[img]["curation"],
                "level": mem[img]["level"], "source": "profile",
                "label": v["label"], "taken_at": mem[img]["taken_at"]})
    tiles_out.sort(key=lambda t: (t["taken_at"] or "", t.get("importance") or 0, t["id"]), reverse=True)  # newest first
    return {"tiles": tiles_out,
            "halves": {"top": [], "bottom": tiles_out},   # compatibility for one release: one panel now
            "updated_at": setting(c, "home.layout_at") or None,
            "display_exponent": float(setting(c, "size.display_exponent") or 2),
            "size_params": params}


def related(c, item_id: str, limit: int = 20) -> list[dict]:
    """Same half first, then the most related from the other half; ties go to the newer item."""
    import numpy as np
    mem = members(c)
    key = item_id if item_id in mem else ("hit:" + item_id if "hit:" + item_id in mem else None)
    if not key:
        return []
    vec = vectors(c, set(mem))
    if key not in vec:
        return []
    me = vec[key]
    scored = []
    for i, v in vec.items():
        if i == key:
            continue
        sim = float(v @ me)
        scored.append((sim * (0.5 + 0.5 * mem[i]["curation"]), mem[i]["taken_at"] or "", i, sim))
    def order(lst):   # most similar first (weighted by placement); equal: the newer first
        return sorted(lst, key=lambda s: (-round(s[0], 4), -_ts(s[1])))
    pick = order(scored)[:limit]
    att = attachments(c, mem, vec)   # an image follows its video when both are listed
    ids = [p[2] for p in pick]
    moved = [p for p in pick if att.get(p[2]) in ids]
    pick = [p for p in pick if p not in moved]
    for p in sorted(moved, key=lambda p: -p[0]):
        pos = next(k for k, q in enumerate(pick) if q[2] == att[p[2]])
        while pos + 1 < len(pick) and att.get(pick[pos + 1][2]) == att[p[2]]:
            pos += 1
        pick.insert(pos + 1, p)
    return [{"id": i[4:] if i.startswith("hit:") else i, "kind": mem[i]["kind"], "half": mem[i]["half"],
             "score": round(sim, 4), "rank": round(sc, 4), "curation": mem[i]["curation"]}
            for sc, _, i, sim in pick]


def _ts(s: str) -> float:
    try:
        return datetime.strptime(s[:19], "%Y-%m-%dT%H:%M:%S").timestamp()
    except ValueError:
        return 0.0


# ------------------------------------------------------------------ tag graph
def tag_graph(c, max_nodes: int = 300, edges_per_node: int = 6) -> dict:
    rows = c.execute("""SELECT t.item_id, t.tag, t.kind FROM item_tags t JOIN items i ON i.id=t.item_id
                        WHERE i.published_at IS NOT NULL""").fetchall()
    tag_items: dict[str, set] = {}
    kinds: dict[str, set] = {}
    for r in rows:
        t = r["tag"]
        if len(t) > 40 or len(t.split()) > 4 or any(ch in t for ch in "()[]:;,"):
            continue   # descriptive phrases stored before tags were kept short
        tag_items.setdefault(t, set()).add(r["item_id"])
        kinds.setdefault(r["tag"], set()).add(r["kind"])
    ranked = sorted(tag_items, key=lambda t: (-len(tag_items[t]), t))[:max_nodes]
    # Level 0 is the AI-defined facets' categories (CONTRACT.md "Facets"); tags follow, deeper.
    from .facets import public_view
    fnodes = []
    for f in public_view(c)["facets"]:
        for k in f["categories"]:
            fnodes.append({"tag": k["name"].lower(), "kinds": ["facet"], "facet": f["id"], "facet_name": f["name"],
                           "category": k["id"], "count": k["count"], "level": 0, "items": set(k["item_ids"])})
    base = 1 if fnodes else 0
    nodes = []
    for rank, t in enumerate(ranked):
        level = base + (0 if rank < 12 else 1 if rank < 48 else 2 if rank < 144 else 3)
        nodes.append({"tag": t, "kinds": sorted(kinds[t]), "count": len(tag_items[t]), "level": level})
    keep = set(ranked)
    pairs: dict[tuple, int] = {}
    by_item: dict[str, list] = {}
    for t in ranked:
        for i in tag_items[t]:
            by_item.setdefault(i, []).append(t)
    for tags in by_item.values():
        tags = sorted(set(tags))
        for a in range(len(tags)):
            for b in range(a + 1, len(tags)):
                pairs[(tags[a], tags[b])] = pairs.get((tags[a], tags[b]), 0) + 1
    edges_all = [{"a": a, "b": b, "count": n, "weight": round(n / math.sqrt(len(tag_items[a]) * len(tag_items[b])), 4)}
                 for (a, b), n in pairs.items() if a in keep and b in keep]
    edges_all.sort(key=lambda e: (-e["weight"], -e["count"]))
    deg: dict[str, int] = {}
    edges = []
    for e in edges_all:
        if deg.get(e["a"], 0) < edges_per_node or deg.get(e["b"], 0) < edges_per_node:
            edges.append(e)
            deg[e["a"]] = deg.get(e["a"], 0) + 1
            deg[e["b"]] = deg.get(e["b"], 0) + 1
    for fn in fnodes:   # each facet category links to the tags its items share most
        links = sorted(((len(fn["items"] & tag_items[t]), t) for t in ranked if fn["items"] & tag_items[t]),
                       key=lambda x: (-x[0], x[1]))[:edges_per_node]
        for n, t in links:
            edges.append({"a": fn["tag"], "b": t, "count": n,
                          "weight": round(n / math.sqrt(len(fn["items"]) * len(tag_items[t])), 4)})
    nodes = [{k: v for k, v in fn.items() if k != "items"} for fn in fnodes] + nodes
    return {"nodes": nodes, "edges": edges}


# ------------------------------------------------------------------ the worker's step
def store_curation(c) -> int:
    """Write each published item's curation, recomputed from highlight membership every refresh."""
    changed = 0
    with tx(c):
        for i, m in members(c).items():
            if m["kind"] != "item":
                continue
            r = c.execute("UPDATE items SET curation=?, curation_reason=? WHERE id=? AND "
                          "(curation IS NOT ? OR curation_reason IS NOT ?)",
                          (m["curation"], m["curation_reason"], i, m["curation"], m["curation_reason"]))
            changed += r.rowcount
    return changed


def refresh(c) -> bool:
    """Embed what changed, recompute curation and reconcile the layout (cheap when nothing changed)."""
    store_curation(c)
    n = update_embeddings(c)
    stats = update_layout(c)
    set_setting(c, "home.layout_at", now())
    return bool(n or stats)
