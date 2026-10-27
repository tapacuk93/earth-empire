"""One collector run, by time across every kind.

1. List (metadata only): the profile page's posts, the Reposts tab, the current stories, every
   changed highlight's stories (from the highlight viewer), and - in a backfill - older feed and
   Reels pages from a saved cursor.
2. Ingest one merged timeline, newest first: posts, reels, reposts, stories and highlight stories
   alike. The timeline lives in the state, so the next run continues down it.
"""

from __future__ import annotations

import logging
import time
from typing import Any

from . import parse
from .backend import Backend
from .igweb import IGError, IGStop, PaceFull
from .media import Downloader, MediaGone, fetch_video, image_size, thumb, to_jpeg, video_frame
from .state import State

log = logging.getLogger("ee.run")

BATCH = 12
STORY_EVERY = 45 * 60
PROFILE_EVERY = 6 * 3600
HIGHLIGHTS_PER_RUN = 15
CHECK_EVERY = 10 * 60      # during a backfill, look for new items this often


class Collector:
    def __init__(self, ig, backend: Backend, state: State, dl: Downloader, target: str,
                 limit: int | None = None, budget_s: float | None = None):
        self.ig, self.backend, self.state, self.dl, self.target = ig, backend, state, dl, target
        self.limit = limit
        self.deadline = time.time() + budget_s if budget_s else None
        if hasattr(ig, "pacer"):
            ig.pacer.deadline = self.deadline
        self.incomplete = False
        self.paced = False          # this hour's own requests are used up: the run winds down
        self.reposts_paced = False  # this hour's repost requests are used up: own items only
        self.mode = "incremental"
        self.started = parse.now_iso()
        self.total_posts: int | None = None
        self._beat_at = 0.0
        self._beat_what = ""
        self.harvested: list[dict] = []
        self.profile_bodies: list = []
        self.recent_cursor: str | None = None
        self.recent_new: int | None = None
        self.tray: list | None = None
        self.priority = 0
        self.watermark: float | None = None
        self.seen_max: float = 0.0
        self.last_check = 0.0
        self.uid: str | None = None
        self.counts: dict[str, int] = {}
        self.pending: list[dict] = []
        self.last_stories = 0.0

    def beat(self, what: str, progress: float | None = None, force: bool = False) -> None:
        """Tell /v1/status what the run is doing: at most once a minute, or when the step changes."""
        step = " ".join(what.split(" ")[:2]) if what.startswith("listing") else what.split(" ")[0]
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
        """List everything cheaply (metadata only), then ingest one merged timeline, newest first:
        posts, reels, reposts, stories and highlight stories alike. The timeline is kept in the
        state, so the next run continues down it."""
        assert mode in ("full", "incremental", "sample", "quick")
        self.mode = mode
        if mode == "sample":
            return self.run_sample()
        if mode == "quick":
            return self.run_quick()
        full = mode == "full"
        log.info("run %s: state has %d items, %d queued", mode, self.state.count_items(), self.state.timeline_len())
        self.do_profile()
        # 1. new items first: a cheap check, then ingest whatever is new before any backfill
        self.check_new(profile_done=True)
        self.step("ingest new", self.ingest_timeline, True)
        # 2. the backfill: list deeper (reposts, unread highlights, older grid pages), then ingest
        #    newest first, checking for new items again every ~10 minutes
        self.step("list reposts", self.list_reposts, full)
        self.step("list highlights", self.list_highlights, full)
        self.step("list feed", self.list_feed, full)
        self.step("list clips", self.list_clips, full)
        log.info("timeline: %d queued %s", self.state.timeline_len(), self.state.timeline_kinds())
        self.step("ingest", self.ingest_timeline)
        self.flush()
        self.step("highlights", self.send_highlights)
        failed = [k for k in self.counts if k.startswith("failed_")]
        left = self.state.timeline_len()
        if failed:
            log.info("not complete: %s failed; the next run continues", ", ".join(failed))
        if self.incomplete or left:
            log.info("run budget used up; %d items wait in the timeline for the next run", left)
            self.bump("backfill_incomplete")
        elif full and not failed and self.state.get("backfill.feed.done"):
            self.state.set("backfill.done_at", parse.now_iso())
        return self.counts

    def lane(self, name: str) -> None:
        """Whose requests these are, for the pacer: the owner's own profile, or reposts."""
        p = getattr(self.ig, "pacer", None)
        if p is not None:
            p.lane = name

    def out_of_time(self) -> bool:
        if self.paced or (self.deadline and time.time() > self.deadline):
            self.incomplete = True
            return True
        return False

    def step(self, name: str, fn, *args) -> None:
        """One step of a run. Only a 429, a challenge or a lost session (IGStop) stops the run;
        any other failure is logged and the run goes on to the next step."""
        try:
            fn(*args)
        except IGStop:
            raise
        except PaceFull as e:
            log.info("%s: stopped by pacing (%s); the next run continues", name, e)
            self.paced = self.incomplete = True
        except Exception as e:  # noqa: BLE001
            log.warning("step %s failed, skipped: %s: %s", name, type(e).__name__, str(e)[:300])
            self.bump("errors")
            self.bump("failed_" + name.replace(" ", "_"))
            try:
                self.flush()
            except Exception as e2:  # noqa: BLE001
                log.warning("flush after %s failed: %s", name, e2)

    def run_quick(self) -> dict:
        """Every ~10 minutes: only the cheap check for new items (the profile page, the stories, the
        Reposts tab's first page, changed highlights) and their ingest, so a new post or repost is on
        the site within minutes. Nothing deeper: the incremental run does that."""
        log.info("run quick: state has %d items", self.state.count_items())
        self.do_profile()
        self.check_new(profile_done=True)
        self.step("ingest new", self.ingest_timeline, True)
        self.flush()
        self.step("highlights", self.send_highlights)
        return self.counts

    def run_sample(self) -> dict:
        """The gentlest useful run: one view of the profile page, then the newest video on it."""
        log.info("run sample: the profile and the newest video")
        self.do_profile()
        videos = [m for m in self.harvested if parse.is_video(m) or m.get("media_type") == 2]
        if not videos:
            raise IGStop("page", f"the profile page showed {len(self.harvested)} posts and no video; "
                                 "stopping without any API request")
        newest = max(videos, key=lambda m: m.get("taken_at") or 0)
        self.beat("posts 0/1 (downloads)", 0.0, force=True)
        self.take(newest)
        self.flush()
        log.info("sample: sent ig_%s (%s, %s)", parse.media_pk(newest), parse.kind_of(newest), parse.iso(newest.get("taken_at")))
        return self.counts

    # ------------------------------------------------------------ profile

    def do_profile(self) -> None:
        self.beat("profile", force=True)
        uid = self.state.get("profile.uid")
        due = not uid or time.time() - self.state.get("profile.at", 0) > PROFILE_EVERY
        p = None
        if True:
            # the profile page as a person opens it: its own requests and embedded data carry the
            # profile and the newest posts. Never web_profile_info (throttled; looks like a bot).
            bodies = self.ig.browse(f"https://www.instagram.com/{self.target}/", scrolls=1)
            shown = self.ig.page_text() if hasattr(self.ig, "page_text") else ""
            if "isn't available" in shown or "Sorry, this page" in shown:
                raise IGStop("config", "the target profile is not available to the downloader account "
                                       "(Instagram shows \"isn't available\"): wrong username in earth-empire/target, "
                                       "the account was renamed or deactivated, or it blocks the downloader")
            self.profile_bodies = bodies
            for body in bodies:
                if "xdt_api__v1__feed__user_timeline_graphql_connection" in str(body)[:2000] or \
                        (isinstance(body, dict) and "edges" in str(body)[:500]):
                    media, nxt = parse.feed_page(body)
                    if media and nxt:
                        self.recent_cursor = nxt
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
        if p is None or not p["_id"]:
            raise IGStop("page", "the profile page did not yield the profile; stopping without any API request")
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

    # ------------------------------------------------------------ listing (metadata only)

    def enqueue(self, item_id: str, kind: str, m: dict, force_new: bool = False) -> bool:
        """Put one item on the timeline unless it is already in, complete."""
        prev = self.state.item(item_id)
        if prev and all(x.get("url") for x in prev.get("media") or [None]):
            return False
        taken = float(m.get("taken_at") or parse.pk_time(parse.media_pk(m)))
        self.seen_max = max(self.seen_max or 0.0, taken)
        priority = 1 if (force_new or self.is_new(taken)) else 0
        return self.state.enqueue(item_id, taken, kind, m, priority)

    def owner_media(self, bodies: list, story: bool) -> list[dict]:
        """The target's own media among what a page loaded (viewers preload other people's too)."""
        out, seen = [], set()
        for m in parse.find_media(bodies):
            owner = m.get("user") or m.get("owner") or {}
            if str(owner.get("pk") or owner.get("id") or "") != str(self.uid):
                continue
            is_story = m.get("product_type") == "story" or "expiring_at" in m
            pk = parse.media_pk(m)
            if is_story == story and pk not in seen:
                seen.add(pk)
                out.append(m)
        return out

    def is_new(self, taken: float) -> bool:
        """Newer than everything any earlier check had seen (none is new on the very first run)."""
        return self.watermark is not None and taken > self.watermark

    def check_new(self, profile_done: bool = False) -> None:
        """The cheap check for new items: the profile page's newest posts, the story viewer, the
        Reposts tab's first page, and highlights whose tray entry changed. Anything new goes to the
        front of the timeline (priority new)."""
        self.last_check = time.time()
        self.watermark = self.state.get("new.watermark")
        self.seen_max = self.watermark or 0.0
        before = self.state.timeline_priority_len()
        if not profile_done:
            self.step("profile", self.do_profile)
        self.step("list recent", self.list_recent)
        self.step("list stories", self.list_stories)
        self.step("list reposts", self.list_reposts, False, True)
        self.step("list highlights", self.list_highlights, False, True)
        self.state.set("new.watermark", self.seen_max or None)
        found = self.state.timeline_priority_len() - before
        if found > 0:
            log.info("new items: %d", found)
            self.bump("new_found", found)

    def list_recent(self) -> None:
        """The posts and reels the profile page itself loaded; no extra request."""
        new = sum(self.enqueue(f"ig_{parse.media_pk(m)}", "post", m) for m in self.harvested)
        self.recent_new = new
        log.info("list recent: %d on the profile page, %d to ingest", len(self.harvested), new)

    def list_reposts(self, full: bool, first_page: bool = False) -> None:
        """The profile's Reposts tab as the web app loads it (user_reposts_timeline grid items).
        The grid gives no repost time; an item is placed by its pk's creation time."""
        if not first_page and (not full or self.state.get("backfill.reposts.done") or self.out_of_time()):
            return
        self.beat("listing reposts", force=True)
        scrolls = 0 if first_page else int(self.state.get("backfill.reposts.scrolls", 8))
        bodies = self.ig.browse(f"https://www.instagram.com/{self.target}/reposts/", scrolls=scrolls)
        seen, new, flags = set(), 0, []
        for body in bodies:
            for d in parse.walk(body):
                if "repost_more_available" in d:
                    flags.append(bool(d.get("repost_more_available")))
                grid = d.get("repost_grid_items")
                for g in grid if isinstance(grid, list) else []:
                    m = g.get("media") if isinstance(g, dict) else None
                    pk = parse.media_pk(m) if isinstance(m, dict) else None
                    if not pk or pk in seen:
                        continue
                    seen.add(pk)
                    new += self.enqueue(f"ig_repost_{pk}", "repost", m)
        more = bool(flags) and all(flags)
        if not first_page:
            if more:
                self.state.set("backfill.reposts.scrolls", min(scrolls + 8, 80))
            else:
                self.state.set("backfill.reposts.done", True)
        log.info("list reposts: %d on the Reposts tab (%s), %d to ingest, more: %s",
                 len(seen), "first page" if first_page else f"{scrolls} scrolls", new, more)

    def list_stories(self) -> None:
        self.beat("listing stories", force=True)
        self.last_stories = time.time()
        # the story viewer, as a person opens it; not /api/v1/feed/reels_media/ directly
        bodies = self.ig.browse(f"https://www.instagram.com/stories/{self.target}/", scrolls=0,
                                click=("View story", "View Story"))
        items = self.owner_media(bodies, story=True)
        known = {parse.media_pk(m) for m in items}
        for body in bodies:  # items inside the target's reel may carry no owner of their own
            for rid, r in parse.reels(body).items():
                if rid == str(self.uid):
                    items += [m for m in r["items"] if parse.media_pk(m) not in known]
                    known |= {parse.media_pk(m) for m in r["items"]}
        new = sum(self.enqueue(f"ig_{parse.media_pk(m)}", "story", m) for m in items)
        log.info("list stories: %d current, %d to ingest", len(items), new)
        self.bump("stories_seen", len(items))

    def list_highlights(self, full: bool, changes_only: bool = False) -> None:
        tray = []
        for body in self.profile_bodies:
            tray = parse.highlight_tray(body)
            if tray:
                break
        if not tray:
            tray = parse.highlight_tray(self.ig.tray(self.uid))
        self.tray = tray
        def known(h):
            return self.state.highlight(h["id"])

        if changes_only:
            # a highlight read before whose tray entry changed, or one created after the last check
            changed = [h for h in tray if (known(h) and known(h)[1] != h["sig"])
                       or (not known(h) and h.get("created_at") and self.watermark is not None
                           and parse.iso(self.watermark) < h["created_at"])]
            if not changed:
                return
        else:
            changed = [h for h in tray if (full and not self.state.get(f"backfill.hl.{h['id']}"))
                       or not known(h) or known(h)[1] != h["sig"]]
        cap = HIGHLIGHTS_PER_RUN if full and not changes_only else len(changed)
        log.info("list highlights: %d in the tray, %d to read, up to %d this run", len(tray), len(changed), cap)
        changed = changed[:cap]
        loaded: dict[str, dict] = {}
        for i, h in enumerate(changed):
            self.beat(f"listing highlights {i}/{len(changed)}", i / len(changed))
            if self.out_of_time():
                break
            r = loaded.get(h["reel_id"])
            if r is None:
                # the highlight viewer, as a person opens it; it often preloads the next ones too
                pk = h["reel_id"].split(":")[-1]
                for body in self.ig.browse(f"https://www.instagram.com/stories/highlights/{pk}/", scrolls=0,
                                           click=("View story", "View Story")):
                    for rid, rr in parse.reels(body).items():
                        if rr["items"]:
                            loaded.setdefault(rid, rr)
                r = loaded.get(h["reel_id"])
            if r is None:
                log.warning("highlight %s (%s): the viewer showed no stories", h["id"], h["title"])
                self.bump("errors")
                continue
            self.record_highlight(h, r["items"], additions_are_new=changes_only)
            self.state.set(f"backfill.hl.{h['id']}", True)

    def record_highlight(self, h: dict, items: list[dict], additions_are_new: bool = False) -> None:
        """A highlight's title, cover, order and membership; its stories go on the timeline."""
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
        new = sum(self.enqueue(f"ig_{parse.media_pk(m)}", "story", m, force_new=additions_are_new)
                  for m in items)
        # stories already ingested whose highlight names changed are sent again right away
        for iid in touched:
            it = self.state.item(iid)
            if it and it.get("highlights") != self.state.highlights_of(iid):
                it["highlights"] = self.state.highlights_of(iid)
                self.state.save_item(it)
                self.queue(it)
        log.info("highlight %s %r: %d stories, %d to ingest", hid, h["title"], len(items), new)

    def send_highlights(self) -> None:
        tray = getattr(self, "tray", None)
        order = [h["id"] for h in tray] if tray else (self.state.get("highlights.order") or [])
        ordered = [self.state.highlight(hid)[0] for hid in order if self.state.highlight(hid)]
        for pos, h in enumerate(ordered):
            h.setdefault("extra", {})["position"] = pos
        if ordered:
            self.backend.put_highlights(ordered)
        self.state.set("highlights.order", order)
        self.bump("highlights", len(ordered))

    def list_feed(self, full: bool) -> None:
        """Older posts as the web app loads them: scrolling the profile grid (its own GraphQL
        timeline requests). /api/v1/feed/user/ is no longer served to the web session."""
        if not full or self.state.get("backfill.feed.done"):
            return  # the profile page's posts were listed already
        self._list_grid("feed", f"https://www.instagram.com/{self.target}/", story=False)

    def list_clips(self, full: bool) -> None:
        """Reels, some only in the Reels tab; once, during the backfill."""
        if full and not self.state.get("backfill.clips.done"):
            self._list_grid("clips", f"https://www.instagram.com/{self.target}/reels/", story=False)

    def _list_grid(self, name: str, url: str, story: bool) -> None:
        if self.out_of_time():
            return
        self.beat(f"listing {name}", force=True)
        scrolls = int(self.state.get(f"backfill.{name}.scrolls", 6))
        bodies = self.ig.browse(url, scrolls=scrolls)
        media = self.owner_media(bodies, story=story)
        flags = []   # one per loaded page of the grid; the last page says there is no more
        for body in bodies:
            for d in parse.walk(body):
                pi = d.get("page_info") if isinstance(d.get("page_info"), dict) else None
                if pi and "has_next_page" in pi and d.get("edges"):
                    flags.append(bool(pi.get("has_next_page")))
                if "more_available" in d and isinstance(d.get("items"), list):
                    flags.append(bool(d.get("more_available")))
                pg = d.get("paging_info") if isinstance(d.get("paging_info"), dict) else None
                if pg and "more_available" in pg:
                    flags.append(bool(pg.get("more_available")))
        more = bool(flags) and all(flags)
        new = sum(self.enqueue(f"ig_{parse.media_pk(m)}", "post", m) for m in media)
        log.info("list %s: %d on the page after %d scrolls, %d to ingest, more: %s", name, len(media), scrolls, new, more)
        if more:
            # the next run scrolls further down (the grid always starts at the top)
            self.state.set(f"backfill.{name}.scrolls", min(scrolls + 6, 60))
        else:
            self.state.set(f"backfill.{name}.done", True)

    # ------------------------------------------------------------ ingesting the timeline

    def ingest_timeline(self, priority_only: bool = False) -> None:
        total = self.state.timeline_priority_len() if priority_only else self.state.timeline_len()
        done = 0
        while True:
            self.lane("own")    # the checks for new items are the owner's own profile
            if not priority_only and time.time() - self.last_check > CHECK_EVERY and not self.out_of_time():
                self.flush()
                self.check_new()          # new items jump the queue
            row = self.state.timeline_next(priority_only, skip_reposts=self.reposts_paced)
            if row is None:
                break
            if self.out_of_time() or (self.limit and self.counts.get("items", 0) >= self.limit):
                break
            item_id, taken, kind, m, attempts, priority = row
            self.priority = priority
            self.beat(f"{'new items' if priority else 'timeline'} {done}/{total} ({parse.iso(taken)[:10]}) (downloads)",
                      done / max(total, 1))
            self.lane("repost" if kind == "repost" else "own")
            try:
                if kind == "repost":
                    self.take_repost_tab(m)
                else:
                    self.take(m, story=(kind == "story"))
                self.state.timeline_done(item_id)
            except IGStop:
                raise
            except PaceFull as e:
                if e.lane == "repost":
                    log.info("reposts wait for the next hour; the owner's own items go on")
                    self.reposts_paced = True
                    continue
                self.paced = self.incomplete = True
                break
            except MediaGone as e:
                # CDN links listed in an earlier run expire; a post can be read again once
                try:
                    if kind != "post":
                        raise
                    log.info("%s: media links expired (%s); reading the post again", item_id, e)
                    found = parse.find_media(self.ig.media_info(parse.media_pk(m)))
                    if not found:
                        raise
                    self.take(found[0])
                    self.state.timeline_done(item_id)
                except IGStop:
                    raise
                except Exception as e2:  # noqa: BLE001
                    log.warning("%s: media unavailable: %s", item_id, e2)
                    self.bump("errors")
                    self.state.timeline_done(item_id)
            except Exception as e:  # noqa: BLE001 - one bad item never stops the timeline
                n = self.state.timeline_failed(item_id)
                log.warning("%s (%s): %s: %s (attempt %d)", item_id, kind, type(e).__name__, str(e)[:200], n)
                self.bump("errors")
                if n >= 3:
                    log.warning("%s: dropped from the timeline after 3 attempts", item_id)
                    self.state.timeline_done(item_id)
            done += 1
        self.priority = 0
        self.flush()
        log.info("ingest%s: %d items, %d left in the timeline", " (new items)" if priority_only else "",
                 done, self.state.timeline_len())

    def take_repost_tab(self, grid_media: dict) -> None:
        """A Reposts-tab item: the grid has no date or video, so read the original's own record."""
        pk = parse.media_pk(grid_media)
        found = parse.find_media(self.ig.media_info(pk))
        if not found:
            raise IGError(f"original {pk} not found")
        self.take_repost_post(found[0])

    def take_repost_post(self, original: dict) -> None:
        it = parse.item(original)
        it["id"] = f"ig_repost_{parse.media_pk(original)}"
        it["extra"]["repost"] = True
        it["extra"]["repost_source"] = "reposts tab"
        it["repost_of"] = parse.repost_of(original)
        prev = self.state.item(it["id"])
        self.upload_media(it["id"], it["repost_of"]["media"], prefix="r")
        it["media"] = [dict(x) for x in it["repost_of"]["media"]]
        self.finish(it, prev)
        self.bump("items")
        self.bump("reposts")
        log.info("%s: repost of @%s %s", it["id"], it["repost_of"]["author"], it["repost_of"]["shortcode"])

    # ------------------------------------------------------------ one item

    def take(self, m: dict, story: bool = False) -> None:
        it = parse.item(m, story=story)
        prev = self.state.item(it["id"])
        it["highlights"] = self.state.highlights_of(it["id"])
        try:
            self.upload_media(it["id"], it["media"])
        except MediaGone as e:
            if not prev:
                raise
            log.warning("%s: media unavailable (%s); keeping what was uploaded before", it["id"], e)
            self.bump("errors")
            it["media"] = prev["media"]
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
        if self.priority or (prev or {}).get("priority") == "new":
            # appeared after the backfill began: the backend analyzes these first (CONTRACT.md)
            it["priority"] = "new"
            if self.priority:
                self.bump("new_items")
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
