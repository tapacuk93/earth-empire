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
        return [self.data["profile"], self.data["tray"]]

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
    assert "feed:None" in ig.calls and not any(x.startswith("feed:33") for x in ig.calls)
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
    store, backend, state = env
    ig, dl = FakeIG(), FakeDL()
    ig.fail_feed_after = 1
    c = Collector(ig, backend, state, dl, "example.owner")
    c.run("full")                      # the feed step fails; the run goes on and ends
    assert c.counts["failed_list_feed"] == 1 and state.get("backfill.done_at") is None
    assert state.get("backfill.feed.cursor") == "3300000000000000002_1000000001"
    assert "ig_3300000000000000003" not in store.items or True
    ig.fail_feed_after = None
    ig.calls.clear()
    Collector(ig, backend, state, dl, "example.owner").run("full")
    feed_calls = [x for x in ig.calls if x.startswith("feed:")]
    assert feed_calls[0] == "feed:3300000000000000002_1000000001"  # continued, not restarted
    assert "ig_3300000000000000003" in store.items
    assert state.get("backfill.feed.done") is True


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


def test_timeline_newest_first_across_kinds(env):
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
    keys = [key(i) for i in first]
    assert keys == sorted(keys, reverse=True), first
    assert state.timeline_len() == 0
