import json
from pathlib import Path

from eecollector import parse
from eecollector.igweb import classify
from eecollector.media import dash_best

FX = Path(__file__).parent / "fixtures"


def fx(name):
    return json.loads((FX / name).read_text())


def test_shortcode_roundtrip():
    pk = "3300000000000000001"
    assert parse.shortcode_to_pk(parse.pk_to_shortcode(pk)) == pk
    # a known pair: instagram.com/p/B-ihJoRJ8ft/
    assert parse.pk_to_shortcode(parse.shortcode_to_pk("B-ihJoRJ8ft")) == "B-ihJoRJ8ft"


def test_profile():
    p = parse.profile(fx("web_profile_info.json"))
    assert p["_id"] == "1000000001"
    assert p["username"] == "example.owner"
    assert p["bio"].startswith("Somewhere")
    assert p["links"] == ["https://example.com/"]
    assert p["counts"] == {"posts": 3, "followers": 1234, "following": 321}
    assert "s320" in p["_avatar_src"]


def test_photo_post():
    media, nxt = parse.feed_page(fx("feed_user_page1.json"))
    assert nxt == "3300000000000000002_1000000001"
    it = parse.item(media[0])
    assert it["id"] == "ig_3300000000000000001"
    assert it["kind"] == "post"
    assert it["shortcode"] == "DAaaaaaaaaa"
    assert it["source_url"] == "https://www.instagram.com/p/DAaaaaaaaaa/"
    assert it["taken_at"] == "2024-05-01T12:00:00Z"
    assert it["hashtags"] == ["sunrise", "travel"]
    assert it["mentions"] == ["friend.one"]
    assert it["tagged_users"] == [{"username": "friend.one", "x": 0.42, "y": 0.61, "full_name": "Friend One"}]
    assert it["location"]["name"] == "Lisbon, Portugal" and it["location"]["id"] == "213385402"
    assert it["music"]["title"] == "Ocean Song" and it["music"]["artist"] == "Sea Band"
    assert it["alt_text"].startswith("Photo by")
    assert it["counts"] == {"likes": 120, "comments": 7}
    m = it["media"][0]
    assert m["type"] == "image" and m["width"] == 1080 and m["height"] == 1350 and m["url"] is None
    assert "photo1_1080" in m["_src"]["image"]
    lab = it["extra"]["labels"]
    assert lab["is_pinned"] is True and lab["caption_is_edited"] is True
    # no CDN URL survives into what is sent
    sent = json.dumps(parse.strip_private(it))
    assert "cdninstagram" not in sent and "fbcdn" not in sent


def test_carousel():
    media, _ = parse.feed_page(fx("feed_user_page1.json"))
    it = parse.item(media[1])
    assert it["kind"] == "carousel"
    assert [m["type"] for m in it["media"]] == ["image", "video"]
    assert it["media"][1]["duration"] == 9.5 and it["media"][1]["width"] == 720
    assert {"username": "friend.two", "x": 0.1, "y": 0.2, "media": 0} in it["tagged_users"]
    lab = it["extra"]["labels"]
    assert lab["collaborators"] == ["friend.one"] and lab["sponsors"] == ["brand.co"]
    assert lab["is_paid_partnership"] is True
    assert it["extra"]["alt_texts"] == ["May be an image of a beach.", None]
    assert it["alt_text"] == "May be an image of a beach."


def test_reel_and_dash():
    media, nxt = parse.feed_page(fx("feed_user_page2.json"))
    assert nxt is None
    it = parse.item(media[0])
    assert it["kind"] == "reel" and it["source_url"] == "https://www.instagram.com/reel/DAccccccccc/"
    assert it["music"]["title"] == "Beat Track"
    assert it["counts"]["plays"] == 9000
    assert it["media"][0]["_src"]["video"].split("?")[0].endswith("reel1_720.mp4")
    v, a = dash_best(it["media"][0]["_src"]["dash"])
    assert v["height"] == 1920 and a["bandwidth"] == 128000


def test_graphql_timeline_shape():
    media, nxt = parse.feed_page(fx("graphql_timeline.json"))
    assert [parse.media_pk(m) for m in media] == ["3300000000000000001", "3300000000000000002"]
    assert nxt == "3300000000000000002_1000000001"


def test_highlights():
    tray = parse.highlight_tray(fx("highlights_tray.json"))
    assert [(h["id"], h["title"]) for h in tray] == [("hl_17900000000000001", "Travel"), ("hl_17900000000000002", "Best")]
    assert tray[0]["reel_id"] == "highlight:17900000000000001" and "hl1_cover" in tray[0]["cover_src"]
    g = parse.highlight_tray(fx("graphql_highlights.json"))
    assert g[0]["title"] == "Travel"
    rs = parse.reels(fx("reels_media_highlights.json"))
    assert len(rs["highlight:17900000000000001"]["items"]) == 2


def test_story_stickers_and_repost():
    rs = parse.reels(fx("reels_media_highlights.json"))
    s1, s2 = rs["highlight:17900000000000001"]["items"]
    it = parse.item(s1, story=True)
    assert it["kind"] == "story" and it["shortcode"] is None and it["source_url"] is None
    types = [s["type"] for s in it["stickers"]]
    assert types == ["mention", "hashtag", "location", "poll", "music"]
    poll = [s for s in it["stickers"] if s["type"] == "poll"][0]
    assert poll["extra"]["options"] == [{"text": "Beach", "count": 10}, {"text": "City", "count": 4}]
    assert it["mentions"] == ["friend.one"] and it["hashtags"] == ["lisbon"]
    assert it["location"]["name"] == "Lisbon, Portugal"
    assert it["music"] == {"title": "Fado", "artist": "Amália"}
    it2 = parse.item(s2, story=True)
    assert it2["extra"]["repost_ref"] == {"pk": "3400000000000000009", "code": "DBzzzzzzzzz", "product_type": "clips"}
    orig = parse.find_media(fx("media_info_original.json"))[0]
    rep = parse.repost_of(orig)
    assert rep["author"] == "other.author" and rep["author_name"] == "Other Author"
    assert rep["source_url"] == "https://www.instagram.com/reel/DBzzzzzzzzz/"
    assert rep["caption"] == "The original reel #original" and rep["media"][0]["type"] == "video"
    assert rep["extra"]["music"]["original"] is True


def test_link_sticker_current_story():
    rs = parse.reels(fx("reels_media_user.json"))
    it = parse.item(rs["1000000001"]["items"][0], story=True)
    assert it["stickers"][0]["type"] == "link" and it["stickers"][0]["extra"]["url"] == "https://example.com/post"


def test_clips_page():
    media, nxt = parse.clips_page(fx("clips_user.json"))
    assert len(media) == 2 and nxt is None


def test_classify():
    assert classify(400, {"message": "checkpoint_required", "checkpoint_url": "/challenge/x"}).kind == "checkpoint"
    assert classify(400, {"message": "challenge_required"}).kind == "checkpoint"
    assert classify(429, {"message": "Please wait a few minutes before you try again."}).kind == "rate_limit"
    assert classify(401, {"message": "Please wait a few minutes before you try again.", "require_login": True}).kind == "login"
    assert classify(200, {"message": "login_required"}).kind == "login"
    assert classify(200, None, "https://www.instagram.com/challenge/?next=/").kind == "checkpoint"
    assert classify(200, {"status": "ok"}) is None


def test_scrub_removes_cdn():
    raw = parse.scrub(fx("feed_user_page1.json"))
    assert "cdninstagram" not in json.dumps(raw)
