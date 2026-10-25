"""Pure parsers from Instagram's own JSON shapes to the contract's Item, Highlight and Profile.

Instagram's web client reads two families of responses, and both carry the same "v1 media"
dicts (snake_case: pk, code, taken_at, media_type, image_versions2, video_versions, ...):

- REST under /api/v1/ (feed/user, feed/reels_media, highlights_tray, media/<pk>/info, ...);
- GraphQL under /api/graphql or /graphql/query, whose xdt_api__v1__* fields wrap the same dicts.

So the parsers take v1 media dicts wherever they come from, and `find_media` digs them out of any
response. Nothing here does I/O. Media sources (Instagram CDN URLs) are kept under `_src` on each
media entry for the downloader; `strip_private` removes them before anything is sent anywhere.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any, Iterable, Iterator

SHORTCODE_ALPHABET = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_"

HASHTAG_RE = re.compile(r"(?<![\w&])#(\w+)", re.UNICODE)
MENTION_RE = re.compile(r"(?<![\w@])@([A-Za-z0-9._]{1,30})")

# Keys whose values are Instagram CDN URLs or lists of them; never kept in `extra`.
CDN_KEYS = {
    "image_versions2", "video_versions", "video_dash_manifest", "profile_pic_url",
    "profile_pic_url_hd", "hd_profile_pic_url_info", "hd_profile_pic_versions",
    "cropped_image_version", "display_url", "display_resources", "thumbnail_src",
    "thumbnail_resources", "video_url", "additional_candidates", "scrubber_spritesheet_info_candidates",
    "audio_reattribution_info", "progressive_download_url", "dash_manifest", "url",
    "video_codec", "image_url", "preview",
}


# ---------------------------------------------------------------- small helpers

def shortcode_to_pk(code: str) -> str:
    n = 0
    for ch in code[:11]:
        n = n * 64 + SHORTCODE_ALPHABET.index(ch)
    return str(n)


def pk_to_shortcode(pk: str | int) -> str:
    n = int(pk)
    out = ""
    while n > 0:
        n, r = divmod(n, 64)
        out = SHORTCODE_ALPHABET[r] + out
    return out or "A"


def iso(ts: Any) -> str | None:
    if ts in (None, "", 0):
        return None
    try:
        return datetime.fromtimestamp(int(float(ts)), tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    except (TypeError, ValueError):
        return None


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def media_pk(m: dict) -> str | None:
    pk = m.get("pk")
    if pk in (None, ""):
        mid = m.get("id") or m.get("media_id")
        if mid is None:
            return None
        pk = str(mid).split("_")[0]
    return str(pk)


def hashtags(text: str | None) -> list[str]:
    return _uniq(HASHTAG_RE.findall(text or ""))


def mentions(text: str | None) -> list[str]:
    return _uniq(m.rstrip(".") for m in MENTION_RE.findall(text or ""))


def _uniq(xs: Iterable[str]) -> list[str]:
    seen, out = set(), []
    for x in xs:
        if x and x not in seen:
            seen.add(x)
            out.append(x)
    return out


def _num(v: Any) -> float | None:
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def caption_text(m: dict) -> str | None:
    c = m.get("caption")
    if isinstance(c, dict):
        return c.get("text")
    if isinstance(c, str):
        return c
    # GraphQL (old) shape
    edges = (m.get("edge_media_to_caption") or {}).get("edges") or []
    if edges:
        return (edges[0].get("node") or {}).get("text")
    return None


def scrub(v: Any) -> Any:
    """A copy of a raw response with every CDN URL and URL list removed."""
    if isinstance(v, dict):
        return {k: scrub(x) for k, x in v.items() if k not in CDN_KEYS and not _is_cdn(x)}
    if isinstance(v, list):
        return [scrub(x) for x in v if not _is_cdn(x)]
    return v


def _is_cdn(x: Any) -> bool:
    return isinstance(x, str) and x.startswith("http") and (
        "cdninstagram.com" in x or "fbcdn.net" in x)


# ---------------------------------------------------------------- media sources

def best_image(m: dict) -> dict | None:
    cands = (m.get("image_versions2") or {}).get("candidates") or []
    cands = [c for c in cands if c.get("url")]
    if not cands:
        if m.get("display_url"):
            dims = m.get("dimensions") or {}
            return {"url": m["display_url"], "width": dims.get("width"), "height": dims.get("height")}
        return None
    return max(cands, key=lambda c: (c.get("width") or 0) * (c.get("height") or 0))


def best_video(m: dict) -> dict | None:
    vs = [v for v in (m.get("video_versions") or []) if v.get("url")]
    if not vs:
        if m.get("video_url"):
            dims = m.get("dimensions") or {}
            return {"url": m["video_url"], "width": dims.get("width"), "height": dims.get("height")}
        return None
    return max(vs, key=lambda v: ((v.get("width") or 0) * (v.get("height") or 0), v.get("bandwidth") or 0))


def is_video(m: dict) -> bool:
    return m.get("media_type") == 2 or bool(m.get("video_versions")) or bool(m.get("is_video"))


def media_entry(m: dict) -> dict:
    """One contract media entry, with the download sources under `_src`."""
    img = best_image(m)
    if is_video(m):
        vid = best_video(m) or {}
        return {
            "type": "video",
            "url": None, "thumbnail": None,
            "width": vid.get("width") or m.get("original_width") or (img or {}).get("width"),
            "height": vid.get("height") or m.get("original_height") or (img or {}).get("height"),
            "duration": _num(m.get("video_duration")),
            "_src": {"pk": media_pk(m), "video": vid.get("url"), "poster": (img or {}).get("url"),
                     "dash": m.get("video_dash_manifest")},
        }
    return {
        "type": "image",
        "url": None, "thumbnail": None,
        "width": (img or {}).get("width") or m.get("original_width"),
        "height": (img or {}).get("height") or m.get("original_height"),
        "duration": None,
        "_src": {"pk": media_pk(m), "image": (img or {}).get("url")},
    }


# ---------------------------------------------------------------- metadata

def tagged_users(m: dict) -> list[dict]:
    out = []
    nodes = [m] + list(m.get("carousel_media") or [])
    for i, node in enumerate(nodes):
        for t in ((node.get("usertags") or {}).get("in") or []):
            user = t.get("user") or {}
            pos = t.get("position") or [None, None]
            entry = {"username": user.get("username"),
                     "x": _num(pos[0]) if len(pos) > 0 else None,
                     "y": _num(pos[1]) if len(pos) > 1 else None}
            if node is not m:
                entry["media"] = i - 1
            if user.get("full_name"):
                entry["full_name"] = user["full_name"]
            out.append(entry)
        # GraphQL (old) shape
        for e in ((node.get("edge_media_to_tagged_user") or {}).get("edges") or []):
            n = e.get("node") or {}
            out.append({"username": (n.get("user") or {}).get("username"),
                        "x": _num(n.get("x")), "y": _num(n.get("y"))})
    # de-duplicate (a carousel may repeat the parent's tags)
    seen, uniq = set(), []
    for t in out:
        k = (t["username"], t.get("x"), t.get("y"), t.get("media"))
        if k not in seen and t["username"]:
            seen.add(k)
            uniq.append(t)
    return uniq


def location(m: dict) -> dict | None:
    loc = m.get("location")
    if not isinstance(loc, dict) or not (loc.get("name") or loc.get("pk") or loc.get("id")):
        return None
    out = {"name": loc.get("name"), "id": str(loc.get("pk") or loc.get("id") or "") or None,
           "lat": _num(loc.get("lat")), "lng": _num(loc.get("lng"))}
    for k in ("address", "city", "short_name", "external_source", "facebook_places_id"):
        if loc.get(k):
            out[k] = loc[k]
    return out


def music(m: dict) -> dict | None:
    cm = m.get("clips_metadata") or {}
    for info in (
        ((cm.get("music_info") or {}).get("music_asset_info")),
        (((m.get("music_metadata") or {}).get("music_info") or {}).get("music_asset_info")),
    ):
        if info and (info.get("title") or info.get("display_artist")):
            return {"title": info.get("title"), "artist": info.get("display_artist"),
                    "id": str(info.get("audio_cluster_id") or info.get("id") or "") or None}
    osi = cm.get("original_sound_info")
    if osi:
        artist = (osi.get("ig_artist") or {}).get("username")
        return {"title": osi.get("original_audio_title") or "Original audio", "artist": artist,
                "original": True}
    for s in m.get("story_music_stickers") or []:
        info = s.get("music_asset_info") or (s.get("music_sticker") or {}).get("music_asset_info") or {}
        if info.get("title"):
            return {"title": info.get("title"), "artist": info.get("display_artist")}
    return None


def counts(m: dict) -> dict:
    out = {}
    pairs = (("likes", ("like_count",)), ("comments", ("comment_count",)),
             ("views", ("view_count", "video_view_count")),
             ("plays", ("play_count", "ig_play_count", "video_play_count")))
    for name, keys in pairs:
        for k in keys:
            v = m.get(k)
            if isinstance(v, (int, float)) and v >= 0:
                out[name] = int(v)
                break
    if "likes" not in out:
        v = ((m.get("edge_media_preview_like") or m.get("edge_liked_by") or {}).get("count"))
        if isinstance(v, int):
            out["likes"] = v
    return out


def alt_texts(m: dict) -> list[str | None]:
    nodes = m.get("carousel_media") or [m]
    return [n.get("accessibility_caption") or n.get("alt_text") for n in nodes]


def labels(m: dict) -> dict:
    """Every visible label on a post, by name. Missing ones are left out."""
    out: dict[str, Any] = {}
    flags = ["is_paid_partnership", "is_pinned", "caption_is_edited", "comments_disabled",
             "like_and_view_counts_disabled", "has_audio", "is_dash_eligible", "is_reshare",
             "has_shared_to_fb", "is_affiliate", "is_ai_generated", "is_cutout_sticker_allowed",
             "can_viewer_reshare", "has_translation", "is_unified_video", "commerciality_status",
             "product_type", "is_artist_pick", "fundraiser_tag", "should_show_author_pog_for_tagged_media_shared_to_story"]
    for f in flags:
        if f in m and m[f] not in (None, False, "", []):
            out[f] = m[f]
    if m.get("timeline_pinned_user_ids") or m.get("clips_tab_pinned_user_ids"):
        out["is_pinned"] = True
    if m.get("sponsor_tags"):
        out["sponsors"] = [((s.get("sponsor") or {}).get("username")) for s in m["sponsor_tags"]]
    collabs = m.get("coauthor_producers") or []
    if collabs:
        out["collaborators"] = [c.get("username") for c in collabs]
    invited = m.get("invited_coauthor_producers") or []
    if invited:
        out["invited_collaborators"] = [c.get("username") for c in invited]
    gen_ai = m.get("gen_ai_detection_method") or m.get("gen_ai_label") or m.get("ai_info")
    if gen_ai:
        out["ai_info"] = scrub(gen_ai)
    if m.get("creative_config", {}) and isinstance(m.get("creative_config"), dict):
        cc = m["creative_config"]
        if cc.get("effect_configs") or cc.get("effect_ids"):
            out["effects"] = scrub(cc.get("effect_configs") or cc.get("effect_ids"))
    if m.get("partnership_details"):
        out["partnership"] = scrub(m["partnership_details"])
    owner = m.get("user") or m.get("owner") or {}
    if owner.get("username"):
        out["author"] = owner.get("username")
    return out


# ---------------------------------------------------------------- stories

def stickers(m: dict) -> list[dict]:
    out: list[dict] = []

    def pos(s: dict) -> dict:
        return {k: s[k] for k in ("x", "y", "width", "height", "rotation") if k in s}

    for s in m.get("reel_mentions") or []:
        u = s.get("user") or {}
        out.append({"type": "mention", "text": u.get("username"),
                    "extra": {**pos(s), "full_name": u.get("full_name"), "display_type": s.get("display_type")}})
    for s in m.get("story_bloks_stickers") or []:
        data = ((s.get("bloks_sticker") or {}).get("sticker_data") or {})
        ig = data.get("ig_mention") or {}
        if ig:
            out.append({"type": "mention", "text": ig.get("username"),
                        "extra": {**pos(s), "full_name": ig.get("full_name")}})
        else:
            out.append({"type": "bloks", "text": None, "extra": scrub(s)})
    for s in m.get("story_hashtags") or []:
        out.append({"type": "hashtag", "text": (s.get("hashtag") or {}).get("name"), "extra": pos(s)})
    for s in m.get("story_locations") or []:
        loc = s.get("location") or {}
        out.append({"type": "location", "text": loc.get("name"),
                    "extra": {**pos(s), "id": str(loc.get("pk") or ""), "lat": loc.get("lat"), "lng": loc.get("lng")}})
    for s in m.get("story_link_stickers") or []:
        link = s.get("story_link") or {}
        out.append({"type": "link", "text": link.get("link_title") or link.get("display_url") or link.get("url"),
                    "extra": {**pos(s), "url": link.get("url")}})
    for c in m.get("story_cta") or []:
        for link in c.get("links") or []:
            url = link.get("webUri") or link.get("url")
            if url:
                out.append({"type": "link", "text": url, "extra": {"url": url}})
    for s in m.get("story_polls") or []:
        p = s.get("poll_sticker") or {}
        out.append({"type": "poll", "text": p.get("question"),
                    "extra": {**pos(s), "options": [{"text": t.get("text"), "count": t.get("count")}
                                                    for t in p.get("tallies") or []]}})
    for s in m.get("story_questions") or []:
        q = s.get("question_sticker") or {}
        out.append({"type": "question", "text": q.get("question"), "extra": pos(s)})
    for s in m.get("story_sliders") or []:
        q = s.get("slider_sticker") or {}
        out.append({"type": "slider", "text": q.get("question"),
                    "extra": {**pos(s), "emoji": q.get("emoji"), "average": q.get("slider_vote_average")}})
    for s in m.get("story_quizs") or m.get("story_quizzes") or []:
        q = s.get("quiz_sticker") or {}
        out.append({"type": "quiz", "text": q.get("question"),
                    "extra": {**pos(s), "options": [t.get("text") for t in q.get("tallies") or []],
                              "correct": q.get("correct_answer")}})
    for s in m.get("story_countdowns") or []:
        q = s.get("countdown_sticker") or {}
        out.append({"type": "countdown", "text": q.get("text"), "extra": {**pos(s), "end": iso(q.get("end_ts"))}})
    for s in m.get("story_music_stickers") or []:
        info = s.get("music_asset_info") or (s.get("music_sticker") or {}).get("music_asset_info") or {}
        out.append({"type": "music", "text": " - ".join(x for x in (info.get("title"), info.get("display_artist")) if x),
                    "extra": {**pos(s), "title": info.get("title"), "artist": info.get("display_artist")}})
    for s in m.get("story_feed_media") or []:
        out.append({"type": "feed_media", "text": s.get("media_code"),
                    "extra": {**pos(s), "media_id": s.get("media_id"), "product_type": s.get("product_type")}})
    for key, kind in (("story_emoji_reactions", "emoji_reaction"), ("story_fundraisers", "fundraiser"),
                      ("story_product_items", "product"), ("story_antiphishing_stickers", "link"),
                      ("story_static_models", "static"), ("story_chats", "chat"),
                      ("story_donations", "donation"), ("story_add_yours", "add_yours")):
        for s in m.get(key) or []:
            out.append({"type": kind, "text": None, "extra": scrub(s)})
    return out


# ---------------------------------------------------------------- reposts

def repost_ref(m: dict) -> dict | None:
    """Where a story or post points at someone else's post or reel, as {pk, code}."""
    for s in m.get("story_feed_media") or []:
        pk = str(s.get("media_id") or "").split("_")[0] or None
        code = s.get("media_code")
        if not pk and code:
            pk = shortcode_to_pk(code)
        if pk:
            return {"pk": pk, "code": code or pk_to_shortcode(pk), "product_type": s.get("product_type")}
    for key in ("reshared_content", "reshared_media", "repost_source_media", "media_repost_source",
                "original_media"):
        src = m.get(key)
        if isinstance(src, dict):
            pk = media_pk(src)
            if pk:
                return {"pk": pk, "code": src.get("code") or pk_to_shortcode(pk),
                        "product_type": src.get("product_type"), "media": src if src.get("taken_at") else None}
    return None


def source_url(code: str | None, product_type: str | None) -> str | None:
    if not code:
        return None
    return f"https://www.instagram.com/{'reel' if product_type == 'clips' else 'p'}/{code}/"


def repost_of(original: dict) -> dict:
    """The contract's `repost_of` from the original media dict (media sources under `_src`)."""
    user = original.get("user") or original.get("owner") or {}
    code = original.get("code") or original.get("shortcode")
    nodes = original.get("carousel_media") or [original]
    return {
        "author": user.get("username"),
        "author_name": user.get("full_name"),
        "shortcode": code,
        "source_url": source_url(code, original.get("product_type")),
        "taken_at": iso(original.get("taken_at") or original.get("taken_at_timestamp")),
        "caption": caption_text(original),
        "media": [media_entry(n) for n in nodes],
        "extra": {
            "pk": media_pk(original), "kind": kind_of(original),
            "author_id": str(user.get("pk") or user.get("id") or "") or None,
            "author_verified": user.get("is_verified"),
            "counts": counts(original), "location": location(original), "music": music(original),
            "hashtags": hashtags(caption_text(original)), "mentions": mentions(caption_text(original)),
            "tagged_users": tagged_users(original), "labels": labels(original),
        },
    }


# ---------------------------------------------------------------- items

def kind_of(m: dict, story: bool = False) -> str:
    pt = m.get("product_type")
    if story or pt == "story":
        return "story"
    if pt == "clips":
        return "reel"
    if m.get("media_type") == 8 or m.get("carousel_media") or pt == "carousel_container":
        return "carousel"
    return "post"


def item(m: dict, story: bool = False) -> dict:
    """The contract's Item (without categories/summary/analysis) from a v1 media dict."""
    pk = media_pk(m)
    kind = kind_of(m, story)
    code = m.get("code") if kind != "story" else None
    cap = caption_text(m)
    nodes = m.get("carousel_media") or [m]
    alts = alt_texts(m)
    extra: dict[str, Any] = {
        "pk": pk,
        "product_type": m.get("product_type"),
        "media_type": m.get("media_type"),
        "labels": labels(m),
    }
    if len(alts) > 1:
        extra["alt_texts"] = alts
    if m.get("expiring_at"):
        extra["expiring_at"] = iso(m["expiring_at"])
    if m.get("video_dash_manifest"):
        extra["has_dash"] = True
    extra["raw"] = scrub(m)
    out = {
        "id": f"ig_{pk}",
        "kind": kind,
        "shortcode": code,
        "source_url": source_url(code, m.get("product_type")) if code else None,
        "taken_at": iso(m.get("taken_at") or m.get("taken_at_timestamp")),
        "caption": cap,
        "hashtags": hashtags(cap),
        "mentions": mentions(cap),
        "tagged_users": tagged_users(m),
        "location": location(m),
        "music": music(m),
        "alt_text": next((a for a in alts if a), None),
        "stickers": stickers(m) if kind == "story" else [],
        "counts": counts(m),
        "media": [media_entry(n) for n in nodes],
        "highlights": [],
        "repost_of": None,
        "extra": extra,
    }
    if kind == "story":
        # story mentions/hashtags count as the story's own mentions and hashtags
        for s in out["stickers"]:
            if s["type"] == "mention" and s["text"] and s["text"] not in out["mentions"]:
                out["mentions"].append(s["text"])
            if s["type"] == "hashtag" and s["text"] and s["text"] not in out["hashtags"]:
                out["hashtags"].append(s["text"])
        if not out["location"]:
            locs = [s for s in out["stickers"] if s["type"] == "location"]
            if locs:
                e = locs[0]["extra"]
                out["location"] = {"name": locs[0]["text"], "id": e.get("id") or None,
                                   "lat": _num(e.get("lat")), "lng": _num(e.get("lng"))}
    ref = repost_ref(m)
    if ref:
        extra["repost_ref"] = {k: v for k, v in ref.items() if k != "media"}
    return out


def strip_private(v: Any) -> Any:
    """Drop the `_src` download hints before an item leaves the collector."""
    if isinstance(v, dict):
        return {k: strip_private(x) for k, x in v.items() if k != "_src"}
    if isinstance(v, list):
        return [strip_private(x) for x in v]
    return v


# ---------------------------------------------------------------- finding things in responses

def walk(v: Any) -> Iterator[dict]:
    if isinstance(v, dict):
        yield v
        for x in v.values():
            yield from walk(x)
    elif isinstance(v, list):
        for x in v:
            yield from walk(x)


def looks_like_media(d: dict) -> bool:
    return ("taken_at" in d and ("image_versions2" in d or "carousel_media" in d or "video_versions" in d)
            and media_pk(d) is not None)


def find_media(resp: Any) -> list[dict]:
    """Every top-level v1 media dict in a response (carousel children are not listed apart)."""
    out, seen = [], set()

    def rec(v: Any) -> None:
        if isinstance(v, dict):
            if looks_like_media(v):
                pk = media_pk(v)
                if pk not in seen:
                    seen.add(pk)
                    out.append(v)
                return
            for x in v.values():
                rec(x)
        elif isinstance(v, list):
            for x in v:
                rec(x)
    rec(resp)
    return out


# ---------------------------------------------------------------- feed pages

def feed_page(resp: dict) -> tuple[list[dict], str | None]:
    """(media, next cursor) from /api/v1/feed/user/<id>/ or the GraphQL timeline connection."""
    if "items" in resp and isinstance(resp["items"], list):
        nxt = resp.get("next_max_id") if resp.get("more_available") else None
        return [x for x in resp["items"] if looks_like_media(x)], nxt
    for d in walk(resp):
        if "edges" in d and "page_info" in d:
            nodes = [e.get("node") or {} for e in d["edges"]]
            nodes = [n.get("media") if isinstance(n.get("media"), dict) else n for n in nodes]
            pi = d["page_info"] or {}
            return [n for n in nodes if looks_like_media(n)], (pi.get("end_cursor") if pi.get("has_next_page") else None)
    return find_media(resp), None


def clips_page(resp: dict) -> tuple[list[dict], str | None]:
    """(media, next cursor) from /api/v1/clips/user/."""
    items = [x.get("media") or x for x in resp.get("items") or []]
    pi = resp.get("paging_info") or {}
    return [x for x in items if looks_like_media(x)], (pi.get("max_id") if pi.get("more_available") else None)


# ---------------------------------------------------------------- highlights

def highlight_id(raw_id: Any) -> str:
    return "hl_" + str(raw_id).split(":")[-1]


def highlight_tray(resp: dict) -> list[dict]:
    """Highlights in the profile's order: {id, reel_id, title, cover_src, sig, media_count}."""
    tray = resp.get("tray")
    if tray is None:
        for d in walk(resp):
            if isinstance(d.get("edges"), list) and d["edges"] and \
                    str((d["edges"][0].get("node") or {}).get("id", "")).startswith("highlight:"):
                tray = [e["node"] for e in d["edges"]]
                break
    out = []
    for h in tray or []:
        rid = str(h.get("id") or "")
        if not rid.startswith("highlight:"):
            continue
        cover = h.get("cover_media") or {}
        cv = cover.get("cropped_image_version") or cover.get("full_image_version") or {}
        url = cv.get("url") or (best_image(cover) or {}).get("url")
        out.append({
            "id": highlight_id(rid), "reel_id": rid, "title": h.get("title"),
            "cover_src": url, "cover_media_id": cover.get("media_id"),
            "media_count": h.get("media_count"),
            "sig": f"{h.get('media_count')}:{h.get('latest_reel_media')}:{h.get('title')}:{cover.get('media_id')}",
            "created_at": iso(h.get("created_at")),
        })
    return out


def reels(resp: dict) -> dict[str, dict]:
    """reel id -> {"items": [media], "title": ...} from /api/v1/feed/reels_media/ or its GraphQL twin."""
    out: dict[str, dict] = {}
    rs = resp.get("reels")
    if isinstance(rs, dict):
        for rid, r in rs.items():
            out[str(rid)] = r
    for key in ("reels_media",):
        for r in resp.get(key) or []:
            out.setdefault(str(r.get("id")), r)
    if not out:
        for d in walk(resp):
            if isinstance(d.get("reels_media"), list):
                for r in d["reels_media"]:
                    out.setdefault(str(r.get("id")), r)
            elif "items" in d and "id" in d and isinstance(d["items"], list) and \
                    (d.get("reel_type") or str(d["id"]).startswith("highlight:")):
                out.setdefault(str(d["id"]), d)
    return {k: {"title": v.get("title"), "items": [x for x in v.get("items") or [] if looks_like_media(x)]}
            for k, v in out.items()}


# ---------------------------------------------------------------- profile

def profile(resp: dict) -> dict:
    """The contract's Profile (avatar under `_avatar_src`) plus `_id`, from web_profile_info or users/<id>/info."""
    u = (resp.get("data") or {}).get("user") or resp.get("user") or resp
    links = []
    for bl in u.get("bio_links") or []:
        if bl.get("url"):
            links.append(bl["url"])
    if u.get("external_url") and u["external_url"] not in links:
        links.append(u["external_url"])
    avatar = ((u.get("hd_profile_pic_url_info") or {}).get("url") or u.get("profile_pic_url_hd")
              or u.get("profile_pic_url"))
    c = {}
    for name, keys in (("posts", ("media_count", "edge_owner_to_timeline_media")),
                       ("followers", ("follower_count", "edge_followed_by")),
                       ("following", ("following_count", "edge_follow"))):
        for k in keys:
            v = u.get(k)
            if isinstance(v, dict):
                v = v.get("count")
            if isinstance(v, int):
                c[name] = v
                break
    return {
        "_id": str(u.get("id") or u.get("pk") or ""),
        "_avatar_src": avatar,
        "username": u.get("username"),
        "full_name": u.get("full_name"),
        "bio": u.get("biography"),
        "avatar": None,
        "links": links,
        "counts": c,
        "extra": {k: u.get(k) for k in ("is_verified", "category_name", "is_business_account",
                                         "is_professional_account", "pronouns", "highlight_reel_count",
                                         "is_private") if u.get(k) not in (None, "", [])},
    }


def find_user(bodies: list, username: str) -> dict | None:
    """The fullest user record for `username` among responses the profile page loaded."""
    best, score = None, 0
    for body in bodies:
        for d in walk(body):
            if d.get("username") != username or not (d.get("id") or d.get("pk")):
                continue
            sc = sum(k in d for k in ("biography", "follower_count", "edge_followed_by", "media_count",
                                      "edge_owner_to_timeline_media", "full_name", "bio_links",
                                      "hd_profile_pic_url_info", "profile_pic_url_hd"))
            if sc > score and ("biography" in d or "follower_count" in d or "edge_followed_by" in d):
                best, score = d, sc
    return best
