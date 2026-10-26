"""End to end: fixture Instagram -> Collector -> the mock backend over HTTP."""

import copy
import time
import io
import json
from pathlib import Path

import pytest
from PIL import Image

from eecollector import parse
from eecollector.backend import Backend
from eecollector.igweb import IGStop
from eecollector.pipeline import Collector
from eecollector.state import State
from mock_backend import serve

FX = Path(__file__).parent / "fixtures"


def fx(name):
    return json.loads((FX / name).read_text())


class FakeIG:
    def __init__(self):
        self.calls = []
        self.data = {k: fx(f) for k, f in (
            ("profile", "web_profile_info.json"), ("feed1", "feed_user_page1.json"), ("feed2", "feed_user_page2.json"),
            ("tray", "highlights_tray.json"), ("hl", "reels_media_highlights.json"), ("user", "reels_media_user.json"),
            ("info", "media_info_original.json"), ("clips", "clips_user.json"))}
        self.fail_feed_after = None

    def browse(self, url, scrolls=1, click=()):
        """The profile page: the user record only (its posts come from the feed fixture)."""
        self.calls.append("browse:" + url)
        if url.endswith("/reposts/"):
            return []
        if "/stories/highlights/" in url:
            return [self.data["hl"]]          # the viewer preloads the neighbouring highlights too
        if "/stories/" in url:
            return [self.data["user"]]
        if url.endswith("/reels/"):
            return [self.data["clips"]]
        # the profile grid: the first page on opening, the rest after scrolling
        if scrolls <= 1:
            return [self.data["profile"], self.data["tray"], self.data["feed1"]]
        return [self.data["profile"], self.data["tray"], self.data["feed1"], self.data["feed2"]]

    def feed(self, uid, cursor):
        self.calls.append(f"feed:{cursor}")
        if self.fail_feed_after is not None and cursor:
            raise RuntimeError("simulated crash mid-backfill")
        return self.data["feed2"] if cursor else self.data["feed1"]

    def clips(self, uid, cursor):
        self.calls.append("clips")
        return self.data["clips"]

    def tray(self, uid):
        self.calls.append("tray")
        return self.data["tray"]

    def reels(self, ids):
        self.calls.append("reels:" + ",".join(ids))
        if ids == ["1000000001"]:
            return self.data["user"]
        hl = self.data["hl"]
        return {"reels": {k: v for k, v in hl["reels"].items() if k in ids}, "status": "ok"}

    def media_info(self, pk):
        self.calls.append(f"info:{pk}")
        return self.data["info"]


class FakeDL:
    def __init__(self):
        self.urls = []

    def get(self, url):
        self.urls.append(url)
        assert "cdninstagram.com" in url
        if ".mp4" in url:
            return b"\x00\x00\x00\x18ftypmp42fake-video-" + url.encode()
        buf = io.BytesIO()
        Image.new("RGB", (1080, 1350), (30, 90, 160)).save(buf, "JPEG")
        return buf.getvalue()


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setattr("eecollector.media.shutil.which", lambda name: None)  # no ffmpeg: progressive MP4 path
    srv, store, base = serve(tmp_path / "uploads", "tok")
    yield store, Backend(base, "tok"), State(tmp_path / "state.sqlite")
    srv.shutdown()


def test_full_then_incremental(env):
    store, backend, state = env
    ig, dl = FakeIG(), FakeDL()
    c = Collector(ig, backend, state, dl, "example.owner")
    c.run("full")

    # profile
    assert store.profile["username"] == "example.owner"
    assert store.profile["avatar"] == "https://media.empire.earth/profile/avatar.jpg"
    # every post, carousel, reel (incl. the reels-tab-only one) and story
    ids = set(store.items)
    assert {"ig_3300000000000000001", "ig_3300000000000000002", "ig_3300000000000000003",
            "ig_3300000000000000004", "ig_3300000000000000101", "ig_3300000000000000102",
            "ig_3300000000000000201"} <= ids
    for it in store.items.values():
        for m in it["media"]:
            assert m["url"].startswith("https://media.empire.earth/items/" + it["id"] + "/")
            assert m["thumbnail"].endswith(".thumb.jpg")
        assert "cdninstagram" not in json.dumps(it)
        assert "_src" not in json.dumps(it)
    # highlight names on stories, a story in two highlights
    s1 = store.items["ig_3300000000000000101"]
    assert [h["title"] for h in s1["highlights"]] == ["Travel", "Best"]
    assert [h["title"] for h in store.items["ig_3300000000000000102"]["highlights"]] == ["Travel"]
    # highlights in order, with re-hosted covers and their stories in order
    hls = [store.highlights[h] for h in store.highlight_order]
    assert [h["title"] for h in hls] == ["Travel", "Best"]
    assert hls[0]["cover"] == "https://media.empire.earth/highlights/hl_17900000000000001/cover.jpg"
    assert hls[0]["item_ids"] == ["ig_3300000000000000101", "ig_3300000000000000102"]
    # the repost: both the story and the original
    rep = store.items["ig_3300000000000000102"]["repost_of"]
    assert rep["author"] == "other.author" and rep["shortcode"] == "DBzzzzzzzzz"
    assert rep["media"][0]["url"] == "https://media.empire.earth/items/ig_3300000000000000102/r0.mp4"
    assert "items/ig_3300000000000000102/r0.mp4" in store.uploads
    # uploads have the right types
    assert store.uploads["items/ig_3300000000000000003/0.mp4"][0] == "video/mp4"
    assert store.uploads["items/ig_3300000000000000001/0.thumb.jpg"][0] == "image/jpeg"
    # carousel media count and order
    car = store.items["ig_3300000000000000002"]
    assert [m["type"] for m in car["media"]] == ["image", "video"]
    assert state.get("backfill.feed.done") is True

    # incremental: nothing new is downloaded again; the newest feed page only
    n_dl, n_up = len(dl.urls), len(store.uploads)
    ig.calls.clear()
    c2 = Collector(ig, backend, state, dl, "example.owner")
    c2.run("incremental")
    assert len(dl.urls) == n_dl + 0, dl.urls[n_dl:]
    assert len(store.uploads) == n_up
    assert not any(x.startswith("feed:") for x in ig.calls)       # no REST feed: the profile page lists
    assert ig.calls.count("browse:https://www.instagram.com/example.owner/") == 1
    assert not any("/stories/highlights/" in x for x in ig.calls)  # tray unchanged
    assert not any(x.startswith("info:") for x in ig.calls)            # repost already resolved


def test_new_story_added_to_highlight(env):
    store, backend, state = env
    ig, dl = FakeIG(), FakeDL()
    Collector(ig, backend, state, dl, "example.owner").run("full")
    # the current story (201) gets added to "Best"
    story3 = ig.data["user"]["reels"]["1000000001"]["items"][0]
    ig.data["hl"]["reels"]["highlight:17900000000000002"]["items"].append(copy.deepcopy(story3))
    ig.data["tray"]["tray"][1]["media_count"] = 2
    ig.data["tray"]["tray"][1]["latest_reel_media"] = 1714600000
    Collector(ig, backend, state, dl, "example.owner").run("incremental")
    assert [h["title"] for h in store.items["ig_3300000000000000201"]["highlights"]] == ["Best"]
    assert store.highlights["hl_17900000000000002"]["item_ids"][-1] == "ig_3300000000000000201"
    # and when it is removed again, the name goes away
    ig.data["hl"]["reels"]["highlight:17900000000000002"]["items"].pop()
    ig.data["tray"]["tray"][1]["media_count"] = 1
    Collector(ig, backend, state, dl, "example.owner").run("incremental")
    assert store.items["ig_3300000000000000201"]["highlights"] == []


def test_backfill_resumes_from_checkpoint(env):
    """A step that fails leaves the rest of the run and the timeline intact; the next run goes on."""
    store, backend, state = env
    ig, dl = FakeIG(), FakeDL()
    orig = ig.browse

    def grid_fails(url, scrolls=1, click=()):
        if url.endswith("/example.owner/") and scrolls > 1:
            raise RuntimeError("simulated crash while scrolling the grid")
        return orig(url, scrolls)
    ig.browse = grid_fails
    c = Collector(ig, backend, state, dl, "example.owner")
    c.run("full")                      # listing older posts fails; the run goes on and ends
    assert c.counts["failed_list_feed"] == 1 and state.get("backfill.done_at") is None
    assert "ig_3300000000000000001" in store.items            # the profile page's posts went in
    ig.browse = orig
    Collector(ig, backend, state, dl, "example.owner").run("full")
    assert "ig_3300000000000000003" in store.items
    assert state.get("backfill.feed.done") is True and state.get("backfill.done_at")


def test_budget_stops_backfill_at_checkpoint(env):
    store, backend, state = env
    ig, dl = FakeIG(), FakeDL()
    c = Collector(ig, backend, state, dl, "example.owner", budget_s=0.001)
    import time as _t
    _t.sleep(0.01)
    c.run("full")
    assert c.incomplete and state.get("backfill.done_at") is None
    Collector(ig, backend, state, dl, "example.owner").run("full")
    assert state.get("backfill.done_at") and "ig_3300000000000000003" in store.items


def test_heartbeats(env):
    store, backend, state = env
    Collector(FakeIG(), backend, state, FakeDL(), "example.owner").run("full")
    whats = [j["what"] for h in store.heartbeats for j in h.get("jobs") or []]
    assert whats[0] == "profile" and "listing stories" in whats
    assert any(w.startswith("listing highlights 0/2") for w in whats)
    tl = [j for h in store.heartbeats for j in h.get("jobs") or [] if j["what"].startswith("timeline ")]
    assert tl and tl[0]["what"].endswith("(downloads)") and 0 <= tl[0]["progress"] <= 1
    assert all("example.owner" not in json.dumps(h) for h in store.heartbeats)


class BrowsingIG(FakeIG):
    """Like the live client: the profile page's own responses carry the user and newest posts."""

    def browse(self, url, scrolls=1, click=()):
        self.calls.append("browse:" + url)
        if url.endswith("/reposts/") or "/stories/" in url:
            return FakeIG.browse(self, url, scrolls)
        u = dict(self.data["profile"]["data"]["user"])
        u.pop("edge_followed_by")
        u["follower_count"] = 1500
        timeline = fx("graphql_timeline.json")
        return [{"data": {"user": u}}, timeline]



def test_profile_page_instead_of_web_profile_info(env):
    store, backend, state = env
    ig, dl = BrowsingIG(), FakeDL()
    Collector(ig, backend, state, dl, "example.owner").run("full")
    assert store.profile["counts"]["followers"] == 1500
    assert state.get("profile.uid") == "1000000001"
    ig.calls.clear()
    Collector(ig, backend, state, dl, "example.owner").run("incremental")
    # the profile page's posts were all known: no REST feed request at all
    assert not any(c.startswith("feed:") for c in ig.calls), ig.calls


def test_sample_newest_video_only(env):
    store, backend, state = env
    ig = BrowsingIG()
    # the profile page shows a photo and a carousel, no video: stop, with no API request
    with pytest.raises(IGStop) as e:
        Collector(ig, backend, state, FakeDL(), "example.owner").run("sample")
    assert e.value.kind == "page" and ig.calls == ["browse:https://www.instagram.com/example.owner/"]
    # with a reel on the page, the newest video is the only item sent
    reel = fx("feed_user_page2.json")["items"][0]
    ig.browse = lambda url, scrolls=1: [{"data": {"user": fx("web_profile_info.json")["data"]["user"]}},
                                        fx("graphql_timeline.json"), {"items": [reel]}]
    Collector(ig, backend, state, FakeDL(), "example.owner").run("sample")
    assert list(store.items) == ["ig_3300000000000000003"]


def test_failing_step_does_not_end_the_run(env):
    store, backend, state = env
    ig = FakeIG()
    orig = ig.browse

    def broken(url, scrolls=1, click=()):
        if "/stories/" in url and "/highlights/" not in url:
            raise RuntimeError("500 from the story viewer")
        return orig(url, scrolls)
    ig.browse = broken
    c = Collector(ig, backend, state, FakeDL(), "example.owner")
    c.run("full")
    assert c.counts["failed_list_stories"] == 1
    assert "ig_3300000000000000003" in store.items      # posts were still reached


def test_timeline_own_items_then_reposts_newest_first(env):
    """Reposts (placed by the original's pk time), stories, highlight stories and posts are
    ingested in one order, newest first."""
    store, backend, state = env
    ig = FakeIG()
    orig = ig.browse
    original = fx("media_info_original.json")["items"][0]
    grid = {"pk": original["pk"], "code": original["code"], "media_type": 2, "product_type": "clips",
            "user": original["user"], "image_versions2": original["image_versions2"]}   # no taken_at

    def with_reposts(url, scrolls=1, click=()):
        if url.endswith("/reposts/"):
            ig.calls.append("browse:" + url)
            return [{"data": {"fetch__XDTUserDict": {"user_reposts_timeline": {
                "repost_grid_items": [{"media": grid}], "repost_more_available": False}}}}]
        return orig(url, scrolls)
    ig.browse = with_reposts
    sent = []
    put = backend.put_items
    backend.put_items = lambda items: (sent.extend(i["id"] for i in items), put(items))[1]
    Collector(ig, backend, state, FakeDL(), "example.owner").run("full")
    rep = store.items["ig_repost_3400000000000000009"]
    assert rep["repost_of"]["author"] == "other.author" and rep["media"][0]["url"].endswith("/r0.mp4")
    assert rep["taken_at"] == "2024-04-23T19:20:00Z"
    first = []
    for i in sent:
        if i not in first:
            first.append(i)
    # the repost is placed by its pk's time (the grid has no date); everything else by taken_at
    import calendar
    def key(i):
        if i.startswith("ig_repost_"):
            return parse.pk_time(i.rsplit("_", 1)[1])
        return calendar.timegm(time.strptime(store.items[i]["taken_at"], "%Y-%m-%dT%H:%M:%SZ"))
    # the owner's own items before reposts (beyond the new ones the cheap check put first); newest first within each
    own = [key(i) for i in first if not i.startswith("ig_repost_")]
    rep = [key(i) for i in first if i.startswith("ig_repost_")]
    assert own == sorted(own, reverse=True) and rep == sorted(rep, reverse=True), first
    assert state.timeline_len() == 0


def test_new_items_first(env):
    """After the first run, anything newer than what was seen jumps the queue and is marked new."""
    store, backend, state = env
    ig, dl = FakeIG(), FakeDL()
    Collector(ig, backend, state, dl, "example.owner", budget_s=3600).run("full")
    assert state.get("new.watermark")
    assert all("priority" not in i for i in store.items.values())   # nothing is "new" on the first run
    # a backfill item still waiting, and then a brand-new post and story appear
    old = copy.deepcopy(ig.data["feed2"]["items"][0])
    old.update(pk="3300000000000000099", id="3300000000000000099_1000000001", code="DAold000099", taken_at=1600000000)
    state.enqueue("ig_3300000000000000099", 1600000000, "post", old)
    post = copy.deepcopy(ig.data["feed1"]["items"][0])
    post.update(pk="3300000000000000777", id="3300000000000000777_1000000001", code="DAnew000777",
                taken_at=1900000000, timeline_pinned_user_ids=[])
    ig.data["feed1"]["items"].insert(0, post)
    story = copy.deepcopy(ig.data["user"]["reels"]["1000000001"]["items"][0])
    story.update(pk="3300000000000000888", id="3300000000000000888_1000000001", taken_at=1900000100)
    ig.data["user"]["reels"]["1000000001"]["items"].append(story)
    sent = []
    put = backend.put_items
    backend.put_items = lambda items: (sent.extend(i["id"] for i in items), put(items))[1]
    Collector(ig, backend, state, dl, "example.owner", budget_s=3600).run("full")
    assert store.items["ig_3300000000000000777"]["priority"] == "new"
    assert store.items["ig_3300000000000000888"]["priority"] == "new"
    assert "priority" not in store.items["ig_3300000000000000099"]
    order = [i for i in sent if i in ("ig_3300000000000000777", "ig_3300000000000000888", "ig_3300000000000000099")]
    assert order.index("ig_3300000000000000099") > order.index("ig_3300000000000000777")
    assert order.index("ig_3300000000000000888") < order.index("ig_3300000000000000777")   # newest first


def test_pacing_keeps_room_for_the_owner_and_never_sleeps_past_the_run():
    from eecollector.config import Settings
    from eecollector.igweb import PaceFull, Pacer
    s = Settings()
    s.per_hour, s.own_reserve, s.min_gap, s.max_gap = 10, 3, 0, 0
    p = Pacer(s)
    p.window = [(time.time() - 10, "own")] * 7        # 7 requests this hour
    p.lane = "repost"
    try:
        p.wait()
        assert False, "reposts may use only per_hour - own_reserve"
    except PaceFull as e:
        assert e.lane == "repost"
    p.lane = "own"
    p.n = 1
    p.wait()                                          # the owner still has room
    p.window = [(time.time() - 10, "own")] * 10
    p.deadline = time.time() + 60                     # a pause of ~an hour would outlast the run
    try:
        p.wait()
        assert False, "never sleeps past the run's deadline"
    except PaceFull as e:
        assert e.lane == "own" and e.wait_s > 60


def test_pacing_is_shared_with_the_monitor_which_never_takes_the_owners_room(tmp_path):
    from eecollector.config import Settings
    from eecollector.igweb import PaceFull, Pacer
    s = Settings()
    s.per_hour, s.own_reserve, s.monitor_per_hour, s.min_gap, s.max_gap = 10, 3, 2, 0, 0
    log_ = tmp_path / "requests.log"
    col, mon = Pacer(s, log_), Pacer(s, log_)
    mon.lane = "monitor"
    mon.wait(); mon.wait()
    try:
        mon.wait()
        assert False, "the monitor has its own small hourly cap"
    except PaceFull as e:
        assert e.lane == "monitor"
    col.lane = "repost"
    for _ in range(5):
        col.wait()                                    # 2 monitor + 5 reposts = 7 = per_hour - own_reserve
    try:
        col.wait()
        assert False, "the collector counts the monitor's requests too"
    except PaceFull:
        pass
    col.lane = "own"
    col.wait()                                        # the owner's profile still has its room
    assert log_.read_text().split().count("monitor") == 2
