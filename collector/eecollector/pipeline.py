"""One collector run: profile, current stories, highlights, posts and reels, reposts -> the backend.

`full` (backfill) walks the whole feed from a saved cursor, so it can stop and continue.
`incremental` reads the newest pages until it reaches items it already has, every highlight whose
tray entry changed, and the current stories. Both refresh stories at least every 45 minutes.
"""

from __future__ import annotations

import logging
import time
from typing import Any

from . import parse
from .backend import Backend
from .igweb import IGError, IGStop
from .media import Downloader, MediaGone, fetch_video, image_size, thumb, to_jpeg, video_frame
from .state import State

log = logging.getLogger("ee.run")

BATCH = 12
STORY_EVERY = 45 * 60
PROFILE_EVERY = 6 * 3600


class Collector:
    def __init__(self, ig, backend: Backend, state: State, dl: Downloader, target: str,
                 limit: int | None = None, budget_s: float | None = None):
        self.ig, self.backend, self.state, self.dl, self.target = ig, backend, state, dl, target
        self.limit = limit
        self.deadline = time.time() + budget_s if budget_s else None
        self.incomplete = False
        self.mode = "incremental"
        self.started = parse.now_iso()
        self.total_posts: int | None = None
        self._beat_at = 0.0
        self._beat_what = ""
        self.harvested: list[dict] = []
        self.recent_new: int | None = None
        self.uid: str | None = None
        self.counts: dict[str, int] = {}
        self.pending: list[dict] = []
        self.last_stories = 0.0

    def beat(self, what: str, progress: float | None = None, force: bool = False) -> None:
        """Tell /v1/status what the run is doing: at most once a minute, or when the step changes."""
        step = what.split(" ")[0]
        if not force and step == self._beat_what and time.time() - self._beat_at < 60:
            return
        self._beat_at, self._beat_what = time.time(), step
        job = {"what": what, "progress": progress, "started_at": self.started}
        self.backend.heartbeat(ok=True, jobs=[job], detail=self.detail())

    def beat_posts(self, name: str) -> None:
        have = self.state.count_posts()
        total = self.total_posts if name == "feed" else None
        if total:
            self.beat(f"{'posts' if name == 'feed' else name} {have}/{total} (downloads)", min(1.0, have / total))
        else:
            self.beat(f"{'posts' if name == 'feed' else name} {have} (downloads)")

    def detail(self) -> dict:
        keys = ("items", "posts", "carousels", "reels", "stories", "highlights", "reposts",
                "media_uploaded", "errors")
        d = {"mode": "backfill" if self.mode == "full" else "incremental",
             "items_known": self.state.count_items(),
             "backfill_done": bool(self.state.get("backfill.done_at"))}
        d.update({f"run_{k}": self.counts[k] for k in keys if k in self.counts})
        return d

    def bump(self, k: str, n: int = 1) -> None:
        self.counts[k] = self.counts.get(k, 0) + n

    # ------------------------------------------------------------ run

    def run(self, mode: str) -> dict:
        assert mode in ("full", "incremental", "sample")
        self.mode = mode
        if mode == "sample":
            return self.run_sample()
        log.info("run %s: target set, state has %d items", mode, self.state.count_items())
        self.do_profile()
        self.do_recent()        # newest first: what the profile page shows, before anything else
        self.do_stories()
        self.do_highlights(full=(mode == "full"))
        self.do_feed(full=(mode == "full"))
        self.do_clips(full=(mode == "full"))
        self.do_reposts_tab(full=(mode == "full"))
        self.flush()
        if mode == "full" and not self.incomplete:
            self.state.set("backfill.done_at", parse.now_iso())
        elif self.incomplete:
            log.info("run budget used up; the backfill continues from its checkpoint next run")
            self.bump("backfill_incomplete")
        return self.counts

    def out_of_time(self) -> bool:
        if self.deadline and time.time() > self.deadline:
            self.incomplete = True
            return True
        return False

    def run_sample(self) -> dict:
        """The gentlest useful run: the profile and the newest video only (a page view, at most
        one more request)."""
        log.info("run sample: the profile and the newest video")
        self.do_profile()
        videos = [m for m in self.harvested if parse.is_video(m) or m.get("media_type") == 2]
        if not videos:
            log.info("sample: no video on the profile page; reading the first Reels page")
            media, _ = parse.clips_page(self.ig.clips(self.uid, None))
            videos = [m for m in media if parse.is_video(m)]
        if not videos:
            log.warning("sample: no video found")
            return self.counts
        newest = max(videos, key=lambda m: m.get("taken_at") or 0)
        self.beat("posts 0/1 (downloads)", 0.0, force=True)
        self.take(newest)
        self.flush()
        log.info("sample: sent ig_%s (%s, %s)", parse.media_pk(newest), parse.kind_of(newest), parse.iso(newest.get("taken_at")))
        return self.counts

    def maybe_stories(self) -> None:
        if time.time() - self.last_stories > STORY_EVERY:
            self.flush()
            self.do_stories()

    # ------------------------------------------------------------ profile

    def do_profile(self) -> None:
        self.beat("profile", force=True)
        uid = self.state.get("profile.uid")
        due = not uid or time.time() - self.state.get("profile.at", 0) > PROFILE_EVERY
        p = None
        if hasattr(self.ig, "browse"):
            # the profile page as a person opens it; its own requests carry the profile and the
            # newest posts, so web_profile_info is not needed
            bodies = self.ig.browse(f"https://www.instagram.com/{self.target}/", scrolls=1)
            shown = self.ig.page_text() if hasattr(self.ig, "page_text") else ""
            if "isn't available" in shown or "Sorry, this page" in shown:
                raise IGStop("config", "the target profile is not available to the downloader account "
                                       "(Instagram shows \"isn't available\"): wrong username in earth-empire/target, "
                                       "the account was renamed or deactivated, or it blocks the downloader")
            user = parse.find_user(bodies, self.target)
            if user:
                p = parse.profile({"user": user})
                uid = p["_id"]
            if uid:
                self.harvested = [m for m in parse.find_media(bodies)
                                  if str((m.get("user") or m.get("owner") or {}).get("pk")
                                         or (m.get("user") or m.get("owner") or {}).get("id") or "") == str(uid)
                                  and m.get("product_type") != "story"]
                log.info("profile page: user %s, %d recent posts", "found" if user else "not found", len(self.harvested))
        if p is None and uid and not due:
            self.uid = uid
            self.total_posts = self.state.get("profile.posts")
            log.info("profile: fresh enough, not fetched")
            return
        if p is None:
            log.info("profile: fetching web_profile_info (no cached user id)")
            p = parse.profile(self.ig.profile(self.target))
        if not p["_id"]:
            raise IGError("profile response had no user id")
        self.uid = p.pop("_id")
        self.state.set("profile.uid", self.uid)
        self.state.set("profile.at", time.time())
        self.state.set("profile.posts", p["counts"].get("posts"))
        src = p.pop("_avatar_src")
        sig = (src or "").split("?")[0].rsplit("/", 1)[-1]
        known = self.state.media("profile/avatar.jpg")
        if src and (not known or known[0] != sig):
            data = to_jpeg(self.dl.get(src))
            url = self.backend.upload("profile/avatar.jpg", data, "image/jpeg")
            self.state.save_media("profile/avatar.jpg", sig, url, None)
            self.bump("media_uploaded")
            known = (sig, url, None)
        p["avatar"] = known[1] if known else None
        p["updated_at"] = parse.now_iso()
        self.backend.put_profile(p)
        self.bump("profile")
        self.total_posts = p["counts"].get("posts")
        log.info("profile: %s posts, %s followers", p["counts"].get("posts"), p["counts"].get("followers"))

    # ------------------------------------------------------------ stories

    def do_stories(self) -> None:
        self.beat("stories", force=True)
        self.last_stories = time.time()
        rs = parse.reels(self.ig.reels([self.uid]))
        items = next(iter(rs.values()), {}).get("items", []) if rs else []
        for m in items:
            self.take(m, story=True)
        self.flush()
        log.info("stories: %d current", len(items))
        self.bump("stories_seen", len(items))

    # ------------------------------------------------------------ highlights

    def do_highlights(self, full: bool) -> None:
        tray = parse.highlight_tray(self.ig.tray(self.uid))
        changed = []
        for h in tray:
            known = self.state.highlight(h["id"])
            if full and not self.state.get(f"backfill.hl.{h['id']}") or not known or known[1] != h["sig"]:
                changed.append(h)
        log.info("highlights: %d in tray, %d to read", len(tray), len(changed))
        for i in range(0, len(changed), 4):
            self.beat(f"highlights {i}/{len(changed)}", i / len(changed))
            if full and self.out_of_time():
                break
            self.maybe_stories()
            chunk = changed[i:i + 4]
            rs = parse.reels(self.ig.reels([h["reel_id"] for h in chunk]))
            for h in chunk:
                r = rs.get(h["reel_id"])
                if r is None:
                    log.warning("highlight %s (%s) missing from reels_media", h["id"], h["title"])
                    self.bump("errors")
                    continue
                self.save_highlight(h, r["items"])
                self.state.set(f"backfill.hl.{h['id']}", True)
        # the profile's order, every time
        ordered = [self.state.highlight(h["id"])[0] for h in tray if self.state.highlight(h["id"])]
        for pos, h in enumerate(ordered):
            h.setdefault("extra", {})["position"] = pos
        self.flush()
        if ordered:
            self.backend.put_highlights(ordered)
        self.state.set("highlights.order", [h["id"] for h in tray])
        self.bump("highlights", len(ordered))

    def save_highlight(self, h: dict, items: list[dict]) -> None:
        hid = h["id"]
        cover = None
        key = f"highlights/{hid}/cover.jpg"
        sig = h.get("cover_media_id") or (h.get("cover_src") or "").split("?")[0]
        known = self.state.media(key)
        if known and known[0] == sig:
            cover = known[1]
        elif h.get("cover_src"):
            try:
                cover = self.backend.upload(key, to_jpeg(self.dl.get(h["cover_src"])), "image/jpeg")
                self.state.save_media(key, sig, cover, None)
                self.bump("media_uploaded")
            except MediaGone as e:
                log.warning("highlight %s cover: %s", hid, e)
                cover = known[1] if known else None
        ids = [f"ig_{parse.media_pk(m)}" for m in items]
        hl = {"id": hid, "title": h["title"], "cover": cover, "item_ids": ids, "updated_at": parse.now_iso(),
              "extra": {"media_count": h.get("media_count"), "created_at": h.get("created_at")}}
        self.state.save_highlight(hl, h["sig"])
        touched = self.state.set_membership(hid, ids)
        fresh = set()
        for m in items:
            self.take(m, story=True)
            fresh.add(f"ig_{parse.media_pk(m)}")
        # items that left this highlight (or are known and unchanged) still need their names updated
        for iid in touched - fresh:
            it = self.state.item(iid)
            if it:
                it["highlights"] = self.state.highlights_of(iid)
                self.queue(it)
        log.info("highlight %s %r: %d stories", hid, h["title"], len(items))

    # ------------------------------------------------------------ posts and reels

    def do_recent(self) -> None:
        """The posts and reels the profile page itself loaded, newest first, with no extra request."""
        self.recent_new = None
        if not self.harvested:
            return
        ordered = sorted(self.harvested, key=lambda m: m.get("taken_at") or 0, reverse=True)
        self.recent_new = sum(not self.state.has_item(f"ig_{parse.media_pk(m)}") for m in ordered)
        for m in ordered:
            self.beat_posts("feed")
            self.take(m)
        self.flush()
        log.info("recent: %d posts from the profile page, %d new", len(ordered), self.recent_new)

    def do_feed(self, full: bool) -> None:
        if (not full or self.state.get("backfill.feed.done")) and self.recent_new is not None \
                and self.recent_new < len(self.harvested):
            log.info("feed: caught up from the profile page alone")
            return
        self._paged("feed", self.ig.feed, parse.feed_page, full)

    def do_clips(self, full: bool) -> None:
        try:
            self._paged("clips", self.ig.clips, parse.clips_page, full)
        except IGError as e:
            # reels that are only in the Reels tab; the feed already holds most of them
            log.warning("clips tab unavailable: %s", e)
            self.bump("errors")

    def _paged(self, name: str, fetch, parse_page, full: bool) -> None:
        key = f"backfill.{name}.cursor"
        done_key = f"backfill.{name}.done"
        if full and self.state.get(done_key):
            log.info("%s: backfill already complete; checking the newest page only", name)
            full = False
        cursor = self.state.get(key) if full else None
        if cursor:
            log.info("%s: resuming backfill from a saved cursor", name)
        pages = 0
        while True:
            self.maybe_stories()
            media, nxt = parse_page(fetch(self.uid, cursor))
            pages += 1
            new = 0
            for m in media:
                if not self.state.has_item(f"ig_{parse.media_pk(m)}"):
                    new += 1
                self.beat_posts(name)
                self.take(m)
            self.flush()
            log.info("%s page %d: %d items, %d new", name, pages, len(media), new)
            if full:
                self.state.set(key, nxt)
            if not nxt:
                if full:
                    self.state.set(done_key, True)
                break
            if not full and new == 0 and pages >= 1:
                break  # caught up; pinned posts make page 1 never fully new, so stop on the first all-known page
            if full and self.out_of_time():
                log.info("%s: run budget used up; stopping at the checkpoint", name)
                break
            if self.limit and self.counts.get("items", 0) >= self.limit:
                log.info("%s: stopping at --limit %d", name, self.limit)
                break
            cursor = nxt

    def do_reposts_tab(self, full: bool) -> None:
        """Posts the account reposted from others (profile's Reposts tab), read as the web app loads it."""
        if not hasattr(self.ig, "browse"):
            return
        try:
            bodies = self.ig.browse(f"https://www.instagram.com/{self.target}/reposts/", scrolls=8 if full else 2)
        except IGError as e:
            log.info("reposts tab: %s", e)
            return
        n = 0
        for body in bodies:
            for m in parse.find_media(body):
                owner = (m.get("user") or m.get("owner") or {})
                if str(owner.get("pk") or owner.get("id") or "") in ("", self.uid):
                    continue
                self.take_repost_post(m)
                n += 1
        self.flush()
        log.info("reposts tab: %d reposted posts seen", n)

    def take_repost_post(self, original: dict) -> None:
        it = parse.item(original)
        it["id"] = f"ig_repost_{parse.media_pk(original)}"
        it["extra"]["repost"] = True
        it["repost_of"] = parse.repost_of(original)
        prev = self.state.item(it["id"])
        if prev and prev.get("repost_of", {}).get("media") and all(x.get("url") for x in prev["repost_of"]["media"]):
            return
        self.upload_media(it["id"], it["repost_of"]["media"], prefix="r")
        it["media"] = [dict(x) for x in it["repost_of"]["media"]]
        self.finish(it)
        self.bump("reposts")

    # ------------------------------------------------------------ one item

    def take(self, m: dict, story: bool = False) -> None:
        it = parse.item(m, story=story)
        prev = self.state.item(it["id"])
        it["highlights"] = self.state.highlights_of(it["id"])
        try:
            self.upload_media(it["id"], it["media"])
        except MediaGone as e:
            log.warning("%s: media unavailable (%s)", it["id"], e)
            self.bump("errors")
            if prev:
                it["media"] = prev["media"]
            else:
                return
        ref = it["extra"].get("repost_ref")
        if ref:
            if prev and prev.get("repost_of") and prev["repost_of"].get("shortcode"):
                it["repost_of"] = prev["repost_of"]
            else:
                it["repost_of"] = self.fetch_repost(it["id"], ref)
        self.finish(it, prev)
        self.bump("items")
        self.bump({"story": "stories"}.get(it["kind"], it["kind"] + "s"))

    def finish(self, it: dict, prev: dict | None = None) -> None:
        now = parse.now_iso()
        it["collected_at"] = (prev or {}).get("collected_at") or now
        it["updated_at"] = now
        self.state.save_item(it)
        self.queue(it)

    def fetch_repost(self, item_id: str, ref: dict) -> dict | None:
        try:
            src = ref.get("media")
            if not src:
                found = parse.find_media(self.ig.media_info(ref["pk"]))
                src = found[0] if found else None
            if not src:
                raise IGError("original not found")
            rep = parse.repost_of(src)
            self.upload_media(item_id, rep["media"], prefix="r")
            self.bump("reposts")
            log.info("%s: repost of @%s %s", item_id, rep["author"], rep["shortcode"])
            return rep
        except (IGError, MediaGone) as e:
            # the original may be private or deleted; keep what the story itself says
            log.warning("%s: original %s unavailable: %s", item_id, ref.get("code"), e)
            self.bump("errors")
            return {"author": None, "author_name": None, "shortcode": ref.get("code"),
                    "source_url": parse.source_url(ref.get("code"), ref.get("product_type")),
                    "taken_at": None, "caption": None, "media": [], "extra": {"unavailable": str(e)}}

    def upload_media(self, item_id: str, media: list[dict], prefix: str = "") -> None:
        for i, e in enumerate(media):
            src = e.get("_src") or {}
            ext = "mp4" if e["type"] == "video" else "jpg"
            key = f"items/{item_id}/{prefix}{i}.{ext}"
            tkey = f"items/{item_id}/{prefix}{i}.thumb.jpg"
            known = self.state.media(key)
            if known and known[0] == src.get("pk"):
                e["url"], e["thumbnail"] = known[1], known[2]
                continue
            if e["type"] == "video":
                data = fetch_video(self.dl, src, e)
                poster = None
                if src.get("poster"):
                    try:
                        poster = self.dl.get(src["poster"])
                    except MediaGone:
                        poster = None
                poster = poster or video_frame(data)
                url = self.backend.upload(key, data, "video/mp4")
            else:
                if not src.get("image"):
                    raise MediaGone("no image source")
                data = to_jpeg(self.dl.get(src["image"]))
                if not e.get("width"):
                    e["width"], e["height"] = image_size(data)
                poster = data
                url = self.backend.upload(key, data, "image/jpeg")
            turl = self.backend.upload(tkey, thumb(poster), "image/jpeg") if poster else None
            self.state.save_media(key, src.get("pk"), url, turl)
            self.bump("media_uploaded", 2 if turl else 1)
            self.bump("bytes", len(data))
            e["url"], e["thumbnail"] = url, turl

    # ------------------------------------------------------------ sending

    def queue(self, it: dict) -> None:
        self.pending = [x for x in self.pending if x["id"] != it["id"]] + [it]
        if len(self.pending) >= BATCH:
            self.flush()

    def flush(self) -> None:
        if not self.pending:
            return
        out = [parse.strip_private(x) for x in self.pending]
        self.backend.put_items(out)
        self.bump("items_sent", len(out))
        self.pending = []


def summarize(counts: dict[str, Any]) -> str:
    return ", ".join(f"{k}={v}" for k, v in sorted(counts.items()))
