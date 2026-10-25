"""The worker and API over fixtures: no network, no audio, no browser.

Telegram pages are saved previews; Instagram and Facebook responses are fixtures in the shapes
their web apps receive (v1 media dicts; GraphQL video nodes), so the Instagram path is tested
before the downloader account is logged in.
"""
import json
import os
import sqlite3
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE.parents[1] / "collector"))
sys.path.insert(0, str(HERE.parents[1] / "backend"))
os.environ["EE_SECRET_ADMIN_TOKEN"] = "secret-admin"
os.environ["EE_TARGET"] = "trsmslv"
os.environ["EE_TELEGRAM_API"] = "off"
TMP = tempfile.mkdtemp()
os.environ["EE_MONITOR_DB"] = str(Path(TMP) / "m.sqlite3")
os.environ["EE_BACKEND_DB"] = str(Path(TMP) / "backend.sqlite3")

from eemonitor import db, worker, api  # noqa: E402
from eemonitor.platforms import facebook, telegram  # noqa: E402

FIX = HERE / "fixtures"


def c():
    return db.conn()


def transcript(words, lang="ru", probs=None):
    ws, t = [], 1.0
    for w in words.split():
        ws.append([" " + w, t, t + 0.35, 0.9])
        t += 0.4
    return {"model": "test", "duration": t + 1, "speech_s": t, "chunks": [
        {"start": 1.0, "end": t, "speech_s": t - 1, "lang": lang, "probs": probs or {lang: 0.95}, "text": words,
         "words": ws, "avg_logprob": -0.3, "no_speech_prob": 0.01}]}


def test_registry_and_telegram_discovery():
    worker.setup(c())
    acc = c().execute("SELECT * FROM accounts WHERE handle='MID_Russia'").fetchone()
    assert acc
    vids, cursor = telegram.parse((FIX / "telegram_MID_Russia.html").read_text(), "MID_Russia")
    assert vids and cursor
    for i, v in enumerate(vids):
        worker.insert_video(c(), v, acc, "official", queue=i == 0)
    states = {r["state"] for r in c().execute("SELECT state FROM videos")}
    assert "queued" in states


def test_fetch_request_queues_new_videos():
    n_new = c().execute("SELECT COUNT(*) n FROM videos WHERE state='new'").fetchone()["n"]
    r = worker.fetch_request(c(), 5)
    assert r["queued"] == min(5, n_new) and r["to_discover"] == 5 - r["queued"]


def test_detection_rescan_and_api():
    v = c().execute("SELECT * FROM videos WHERE source_id='ru_mid' LIMIT 1").fetchone()
    tr = transcript("Сегодня мы встретились с Тарасом Масловым и обсудили вопросы")
    c().execute("UPDATE videos SET state='done', transcript=?, languages=? WHERE id=?",
                (worker.store_transcript(tr), json.dumps({"ru": 4}), v["id"]))
    worker.rescan(c())
    hits = api.hits(kind=None, platform=None, source_kind=None, phrase=None, min_confidence=0, published=None,
                    sort="confidence", before=None, limit=10)["hits"]
    assert hits and hits[0]["phrase"] == "тарас маслов" and hits[0]["matched"] == "Тарасом Масловым"
    h = hits[0]
    assert h["source"]["name"].startswith("Ministry") and h["source_kind"] == "official"
    assert h["confidence_label"] in ("likely", "possible") and h["at_url"].startswith("https://t.me/MID_Russia/")
    # phrases changed: the stored transcript is matched again, no download
    worker.set_phrases(c(), ["маслов"], use_claude=False)
    worker.rescan(c())
    hits = api.hits(kind=None, platform=None, source_kind=None, phrase=None, min_confidence=0, published=None,
                    sort="confidence", before=None, limit=10)["hits"]
    assert [x["phrase"] for x in hits] == ["маслов"]
    worker.set_phrases(c(), ["тарас", "тарас маслов", "маслов"], use_claude=False)
    worker.rescan(c())


def test_language_mismatch_hit():
    v = c().execute("SELECT * FROM videos WHERE source_id='ru_mid' AND state!='done' LIMIT 1").fetchone()
    tr = transcript("Добрий день шановні колеги ми зібралися тут сьогодні щоб обговорити", "uk", {"uk": 0.8, "ru": 0.15})
    hits = worker.detect_all(c(), v, tr)
    assert [h["kind"] for h in hits] == ["language"] and hits[0]["language"] == "uk"


def test_publish_flow():
    from fastapi.testclient import TestClient
    cl = TestClient(api.app)
    auth = {"Authorization": "Bearer secret-admin"}
    for path in ("/v1/monitor/hits", "/v1/monitor/sources", "/v1/monitor/phrases", "/v1/monitor/status"):
        assert cl.get(path).status_code == 401, path
        assert cl.get(path, headers={"Authorization": "Bearer wrong"}).status_code == 401, path
    assert cl.post("/v1/monitor/fetch", json={"n": 3}).status_code == 401
    hid = cl.get("/v1/monitor/hits", headers=auth).json()["hits"][0]["id"]
    assert cl.post(f"/v1/monitor/hits/{hid}/publish").status_code == 401
    r = cl.post(f"/v1/monitor/hits/{hid}/publish", headers=auth)
    assert r.status_code == 200 and r.json()["published_at"]
    pub = cl.get("/v1/published").json()["hits"]
    assert [p["id"] for p in pub] == [hid]
    assert cl.get("/v1/monitor/phrases", headers=auth).json()["phrases"][0]["text"] == "тарас"
    st = cl.get("/v1/monitor/status", headers=auth).json()
    assert st["scanned_total"] >= 1
    r = cl.post("/v1/monitor/fetch", json={"n": 3}, headers=auth)
    assert r.status_code == 200 and r.json()["n"] == 3


def test_media_urls():
    from eemonitor import media
    row = {"id": "h_x", "published_at": "2026-01-01T00:00:00Z"}
    h = {"clip_key": "monitor/clips/h_x.mp3"}
    assert media.url(row, h, "clip") == "https://media.empire.earth/monitor/public/h_x.mp3"
    assert media.url(row, h, "frame") is None
    assert media.private_key({"clip": "https://media.empire.earth/monitor/clips/h_y.mp3"}, "clip") == "monitor/clips/h_y.mp3"


def test_instagram_media_to_video():
    from eecollector import parse
    from eemonitor.platforms.instagram import to_video
    m = json.loads((FIX / "instagram_clips.json").read_text())["items"][0]["media"]
    v = to_video(m, parse)
    assert v["id"] == "ig:3456789012345678901" and v["media_url"].startswith("https://")
    assert v["extra"]["author"] == "un" and v["url"].endswith("/reel/C9xYz12AbCd/")


def test_facebook_graphql_nodes():
    text = (FIX / "facebook_graphql.txt").read_text()
    vids = [v for b in facebook.json_blobs(text) for v in facebook.videos_in(b)]
    ids = {v["id"] for v in vids}
    assert ids == {"fb:1234567890123456", "fb:2234567890123456"}
    v = next(x for x in vids if x["id"] == "fb:1234567890123456")
    assert v["media_url"].startswith("https://video") and v["duration"] == 95.5 and v["posted_at"]


def test_repost_seeds_from_backend_db():
    b = sqlite3.connect(os.environ["EE_BACKEND_DB"])
    b.execute("CREATE TABLE items (id TEXT PRIMARY KEY, data TEXT)")
    b.execute("INSERT INTO items VALUES (?, ?)", ("ig_story_1", json.dumps({"repost_of": {
        "author": "somejournalist", "author_name": "Some Journalist", "shortcode": "C9xYz12AbCd",
        "source_url": "https://www.instagram.com/reel/C9xYz12AbCd/", "taken_at": "2026-10-01T10:00:00Z",
        "media": [{"type": "video", "url": "https://media.empire.earth/items/ig_story_1/r0.mp4", "duration": 30}],
        "extra": {"pk": "3456789012345678901", "author_id": "42"}}})))
    b.commit()
    b.close()
    assert worker.repost_seeds(c()) == 1
    v = c().execute("SELECT * FROM videos WHERE via='ig_story_1'").fetchone()
    assert v["source_kind"] == "reposted" and v["state"] == "queued"
    s = c().execute("SELECT * FROM sources WHERE id='ig_somejournalist'").fetchone()
    assert s["source_kind"] == "reposted_author"


def test_expand_instagram_seed_with_fake_browser(monkeypatch):
    from eemonitor.platforms import instagram

    class FakeIG:
        def __init__(self, *a):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            pass

        def around(self, code):
            return [{"id": "ig:999", "platform": "instagram", "url": "https://www.instagram.com/reel/Zz/",
                     "media_url": "https://cdn/x.mp4", "extra": {"code": "Zz", "author": "other"}}]

        def account_videos(self, author, uid=None):
            return [], None

    c().execute("UPDATE videos SET state='done' WHERE source_kind='reposted'")
    monkeypatch.setattr(worker, "INSTAGRAM_DIRECT", True)   # the later stage; off on the box
    monkeypatch.setattr(instagram, "Instagram", FakeIG)
    monkeypatch.setattr(instagram, "session_exists", lambda: True)
    assert worker.expand_one(c()) == 1
    v = c().execute("SELECT * FROM videos WHERE id='ig:999'").fetchone()
    assert v["source_kind"] == "recommended" and v["via"] == "ig_story_1" and v["hop"] == 1
    hits = api.hits(kind=None, platform=None, source_kind="recommended", phrase=None, min_confidence=0,
                    published=None, sort="confidence", before=None, limit=10)
    assert hits["hits"] == []


def test_learning_unknown_source_and_missing_variant():
    from eemonitor import learn
    # 1. a repost's original from an author the monitor never watched: a miss, the source is raised
    mv = c().execute("SELECT * FROM videos WHERE source_kind='reposted'").fetchone()
    tr = transcript("и отдельно спасибо Тарасу Маслову за помощь")
    hits = worker.detect_all(c(), mv, tr)
    res = learn.evaluate(c(), mv, hits, tr)
    assert res["matched"] and not res["found_first"] and "source_not_in_registry" in res["misses"]
    acc = c().execute("SELECT * FROM accounts WHERE handle='somejournalist'").fetchone()
    assert acc["priority"] >= 1
    imp = c().execute("SELECT * FROM improvements WHERE cause='source_not_in_registry'").fetchone()
    assert imp and imp["applied"] == 1 and "somejournalist" in imp["change"]
    # 2. the monitor had the same video (same Instagram pk) but only a fuzzy word: the variant is learned
    worker.insert_video(c(), {"id": "ig:777", "platform": "instagram", "url": "https://www.instagram.com/reel/Qq/",
                              "media_url": "https://cdn/q.mp4", "extra": {"code": "Qq"}},
                        {"id": acc["id"], "source_id": acc["source_id"]}, "followed")
    c().execute("UPDATE videos SET state='done', transcript=?, discovered_at='2026-01-01T00:00:00Z' WHERE id='ig:777'",
                (worker.store_transcript(transcript("we thank Tharas for the help", "en")),))
    worker.insert_video(c(), {"id": "mirror:ig:777", "platform": "instagram", "url": "https://www.instagram.com/reel/Qq/",
                              "media_url": "https://media.empire.earth/x.mp4",
                              "extra": {"pk": "777", "code": "Qq", "author": "somejournalist"}},
                        None, "reposted", via="ig_story_2")
    mv2 = c().execute("SELECT * FROM videos WHERE id='mirror:ig:777'").fetchone()
    tr2 = transcript("we thank Tharas for the help", "en")
    hits2 = worker.detect_all(c(), mv2, tr2)
    assert hits2 and hits2[0]["matched"] == "Tharas"
    res2 = learn.evaluate(c(), mv2, hits2, tr2)
    assert res2["misses"] == ["variant_missing"]
    assert "tharas" in worker.list_phrases(c())[0]["claude_variants"]
    again = worker.detect_all(c(), mv2, tr2)
    assert again[0]["scores"]["sound"] >= 0.6   # now a known spelling
    rep = learn.report(c())
    assert rep["matched"] == 2 and rep["found_first"] == 0 and rep["misses_by_cause"]["variant_missing"] == 1


def test_highlight_suggestions_and_sections(monkeypatch):
    from fastapi.testclient import TestClient
    from eemonitor import highlights, judge
    hls = [{"id": "hl_1", "title": "Масловы", "item_ids": [], "summaries": ["family reunion in Lviv"]},
           {"id": "hl_2", "title": "Food", "item_ids": [], "summaries": ["pizza"]}]
    monkeypatch.setattr(highlights, "fetch_highlights", lambda: hls)
    answers = {"phrase-suggestions": '{"text": "львів", "why": "Масловы: Lviv", "uk": "Львів", "ru": "Львов", "en": "Lviv"}\n'
                                     '{"text": "тарас", "why": "already there"}',
               "review": '{"n": 0, "en": "and thanks to Taras Maslov", "name_probability": 0.8, "reason": "a name", '
                         '"level": 2, "level_reason": "matters"}'}
    monkeypatch.setattr(judge, "ask", lambda c_, prompt, purpose, *a, **k: answers.get(purpose))
    cl = TestClient(api.app)
    auth = {"Authorization": "Bearer secret-admin"}
    assert highlights.suggest_phrases(c()) == 1
    ph = cl.get("/v1/monitor/phrases", headers=auth).json()
    assert [s["text"] for s in ph["suggested"]] == ["львів"] and "львів" not in [p["text"] for p in ph["phrases"]]
    ph = cl.post("/v1/monitor/phrases/suggested/львів/accept", headers=auth).json()
    assert "львів" in [p["text"] for p in ph["phrases"]] and ph["suggested"] == []
    lv = next(p for p in ph["phrases"] if p["text"] == "львів")
    assert "lviv" in lv["claude_variants"] and "львов" in lv["claude_variants"]
    # levels: Claude's level comes with the review; "+" approves at it; the owner may override
    hit = {"kind": "name", "phrase": "тарас маслов", "matched": "Тарасу Маслову", "language": "ru", "confidence": 0.8,
           "excerpt": "и спасибо Тарасу Маслову", "scores": {"sound": 0.9, "asr": 0.9, "name": 0.85}}
    judge.review(c(), {"id": "v", "title": "t", "platform": "telegram", "url": "u"}, [hit])
    assert hit["level"] == 2 and hit["level_reason"] and hit["excerpt_en"]
    v = c().execute("SELECT * FROM videos WHERE state='done' AND transcript IS NOT NULL LIMIT 1").fetchone()
    hit.update({"start": 50.0, "end": 51.0, "excerpt_start": 49, "excerpt_end": 52})
    worker.save_hits(c(), v, worker.detect_all(c(), v, worker.load_transcript(v["transcript"])) + [hit], "test")
    hid = worker.hit_id(v["id"], hit)
    got = cl.get(f"/v1/monitor/hits/{hid}", headers=auth).json()
    assert got["level"] == 2 and got["level_by"] == "ai" and got["level_reason"] == "matters"
    r = cl.post(f"/v1/monitor/hits/{hid}/publish", headers=auth).json()
    assert r["level"] == 2 and r["published_at"]
    assert hid in [h["id"] for h in cl.get("/v1/published").json()["hits"]]
    r = cl.put(f"/v1/monitor/hits/{hid}/level", json={"level": "L1"}, headers=auth).json()
    assert r["level"] == 1 and r["level_by"] == "owner" and r["ai_level"] == 2
    assert cl.post(f"/v1/monitor/hits/{hid}/publish", json={"level": 7}, headers=auth).status_code == 400
    assert cl.get("/v1/monitor/sections", headers=auth).status_code == 404

def test_tiktok_items():
    from eemonitor.platforms import tiktok
    blob = json.loads((FIX / "tiktok_item_list.json").read_text())
    vids = {v["id"]: v for v in tiktok.videos_in(blob)}
    v = vids["tt:7430000000000000001"]
    assert v["platform"] == "tiktok" and v["url"] == "https://www.tiktok.com/@nato/video/7430000000000000001"
    assert v["media_url"].endswith("play.mp4") and v["duration"] == 42 and v["posted_at"].startswith("2025-10-01")
    assert vids["tt:7430000000000000002"]["media_url"] == "https://v16/bitrate.mp4"
    html = '<script id="__UNIVERSAL_DATA_FOR_REHYDRATION__" type="application/json">' + json.dumps(
        {"__DEFAULT_SCOPE__": {"webapp.video-detail": {"itemInfo": {"itemStruct": blob["itemList"][0]}}}}) + "</script>"
    assert [x["id"] for b in tiktok.blobs_in(html) for x in tiktok.videos_in(b)] == ["tt:7430000000000000001"]


def test_telegram_api_unblocks_large_videos(monkeypatch, tmp_path):
    from eemonitor.platforms import telegram_api
    vids, _ = telegram.parse((FIX / "telegram_zelenskiy.html").read_text(), "V_Zelenskiy_official")
    acc = c().execute("SELECT * FROM accounts WHERE handle='V_Zelenskiy_official'").fetchone()
    for v in vids:
        worker.insert_video(c(), v, acc, "official")
    blocked = c().execute("SELECT COUNT(*) n FROM videos WHERE platform='telegram' AND state='blocked'").fetchone()["n"]
    assert blocked >= 1
    monkeypatch.setattr(telegram_api, "credentials", lambda: (1, "h", "s" * 60))
    worker.setup(c())
    assert c().execute("SELECT COUNT(*) n FROM videos WHERE platform='telegram' AND state='blocked'").fetchone()["n"] == 0
    got = {}
    monkeypatch.setattr(telegram, "refresh_media_url", lambda c_, v: None)
    monkeypatch.setattr(telegram_api, "download", lambda c_, post, dest: got.setdefault("post", post) and dest)
    v = c().execute("SELECT * FROM videos WHERE id=?", (vids[0]["id"],)).fetchone()
    worker.download(c(), v, tmp_path)
    assert got["post"] == vids[0]["extra"]["post"]


def test_no_instagram_requests_by_default(monkeypatch):
    from eemonitor.platforms import instagram

    def boom(*a, **k):
        raise AssertionError("the monitor must not open Instagram")
    monkeypatch.setattr(instagram, "Instagram", boom)
    monkeypatch.setattr(instagram, "session_exists", lambda: True)
    assert worker.INSTAGRAM_DIRECT is False
    c().execute("UPDATE videos SET expanded=0 WHERE platform='instagram'")
    assert worker.expand_one(c()) == 0
    v = c().execute("SELECT * FROM videos WHERE id='ig:999'").fetchone()
    import pytest
    with pytest.raises(worker.youtube.Blocked):
        worker.download(c(), v, Path(TMP))


def test_detection_gate(monkeypatch):
    from eemonitor import gate
    b = sqlite3.connect(os.environ["EE_BACKEND_DB"])
    cols = [r[1] for r in b.execute("PRAGMA table_info(items)")]
    if "published_at" not in cols:
        b.execute("ALTER TABLE items ADD COLUMN published_at TEXT")
    b.execute("UPDATE items SET published_at='2026-10-01T00:00:00Z'")
    b.execute("INSERT OR REPLACE INTO items VALUES (?, ?, ?)", ("ig_dog", json.dumps({"media": [
        {"type": "video", "url": "key:items/ig_dog/0.mp4", "duration": 12}]}), "2026-10-01T00:00:00Z"))
    b.execute("INSERT OR REPLACE INTO items VALUES (?, ?, ?)", ("ig_photo", json.dumps({"media": [
        {"type": "image", "url": "key:items/ig_photo/0.jpg"}]}), "2026-10-01T00:00:00Z"))
    b.execute("INSERT OR REPLACE INTO items VALUES (?, ?, ?)", ("ig_capt", json.dumps({"caption": "з Тарасом у Львові",
        "media": [{"type": "image", "url": "key:items/ig_capt/0.jpg"}]}), None))
    b.commit()
    b.close()
    worker.repost_seeds(c())
    dog = c().execute("SELECT * FROM videos WHERE id='mirror:ig_dog#0'").fetchone()
    assert dog["priority"] == 30 and dog["media_url"] == "https://media.empire.earth/items/ig_dog/0.mp4"
    # the dog video: scanned, no speech that matches -> not matched; the repost original has a phrase hit
    c().execute("UPDATE videos SET state='done', model='test' WHERE id='mirror:ig_dog#0'")
    rep = c().execute("SELECT * FROM videos WHERE via='ig_story_1' AND source_kind='reposted'").fetchone()
    tr = transcript("и отдельно спасибо Тарасу Маслову за помощь")
    worker.save_hits(c(), rep, worker.detect_all(c(), rep, tr), "test")
    c().execute("UPDATE videos SET state='done' WHERE id=?", (rep["id"],))
    pushed = []
    monkeypatch.setattr(gate, "push", lambda c_: pushed.append(1) or 0)
    gate.refresh(c())
    d = {r["item_id"]: json.loads(r["detection"]) for r in c().execute("SELECT * FROM detections")}
    assert d["ig_dog"]["matched"] is False and d["ig_dog"]["complete"] is True
    assert d["ig_photo"]["matched"] is False and "no video" in d["ig_photo"]["reason"]
    assert d["ig_capt"]["matched"] is True and d["ig_capt"]["hits"][0]["source"] == "caption"
    s1 = d["ig_story_1"]
    assert s1["matched"] is True and s1["hits"][0]["phrase"] == "тарас маслов"
    assert s1["hits"][0]["media"] == 0 and s1["hits"][0]["repost"] is True
    assert s1["hits"][0]["label"] in ("likely", "possible", "low confidence")
    summ = gate.summary(c(), True)
    assert summ["matched"] >= 1 and summ["not_matched"] >= 2
