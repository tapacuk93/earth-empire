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
    os.environ["EE_SECRET_ADMIN_TOKEN"] = "secret-admin"
    cl = TestClient(api.app)
    hid = cl.get("/v1/monitor/hits").json()["hits"][0]["id"]
    assert cl.post(f"/v1/monitor/hits/{hid}/publish").status_code in (401, 503)
    sys.modules.pop("ee", None)
    r = cl.post(f"/v1/monitor/hits/{hid}/publish", headers={"Authorization": "Bearer secret-admin"})
    if r.status_code == 503:   # the backend package is not installed here
        c().execute("UPDATE hits SET published_at=? WHERE id=?", (db.now(), hid))
    else:
        assert r.status_code == 200 and r.json()["published_at"]
    pub = cl.get("/v1/published").json()["hits"]
    assert [p["id"] for p in pub] == [hid]
    assert cl.get("/v1/monitor/phrases").json()["phrases"][0]["text"] == "тарас"
    st = cl.get("/v1/monitor/status").json()
    assert st["scanned_total"] >= 1
    r = cl.post("/v1/monitor/fetch", json={"n": 3})
    assert r.status_code == 200 and r.json()["n"] == 3


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

    monkeypatch.setattr(instagram, "Instagram", FakeIG)
    monkeypatch.setattr(instagram, "session_exists", lambda: True)
    assert worker.expand_one(c()) == 1
    v = c().execute("SELECT * FROM videos WHERE id='ig:999'").fetchone()
    assert v["source_kind"] == "recommended" and v["via"] == "ig_story_1" and v["hop"] == 1
    hits = api.hits(kind=None, platform=None, source_kind="recommended", phrase=None, min_confidence=0,
                    published=None, sort="confidence", before=None, limit=10)
    assert hits["hits"] == []
