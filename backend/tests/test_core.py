"""Store, pipeline and composition tests: standard library only (python3 -m unittest discover tests)."""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE.parent))
os.environ.setdefault("EE_MEDIA_BASE_URL", "https://media.example")
os.environ.setdefault("EE_MEDIA_HOSTS", "d111111abcdef8.cloudfront.net")

from ee import compose, db, store  # noqa: E402

FIXTURES = json.loads((HERE / "fixtures" / "items.json").read_text())


class StoreTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.c = db.connect(Path(self.tmp.name) / "t.sqlite3")

    def tearDown(self):
        self.c.close()
        self.tmp.cleanup()

    def test_media_urls_become_keys_and_back(self):
        self.assertEqual(store.to_key("https://media.empire.earth/items/a/0.jpg"), "key:items/a/0.jpg")
        self.assertEqual(store.to_key("https://d111111abcdef8.cloudfront.net/items/a/0.jpg"), "key:items/a/0.jpg")
        self.assertEqual(store.to_key("items/a/0.jpg"), "key:items/a/0.jpg")
        self.assertEqual(store.to_url("key:items/a/0.jpg"), f"{store.config.MEDIA_BASE_URL}/items/a/0.jpg")

    def test_ingest_mirrors_the_accounts_own_and_video_reposts_at_once(self):
        counts = store.upsert_items(self.c, FIXTURES["items"])
        self.assertEqual(counts["inserted"], len(FIXTURES["items"]))
        st = store.pipeline_status(self.c)
        self.assertEqual(st["steps"]["analyze"]["pending"], len(FIXTURES["items"]))
        public = {r["id"] for r in self.c.execute("SELECT id FROM items WHERE published_at IS NOT NULL")}
        own = {i["id"] for i in FIXTURES["items"] if not i.get("repost_of") or store.has_video(i)}
        self.assertEqual(public, own)   # mirroring is never missed: own posts and video reposts before any analysis
        # the account's own first, oldest first; reposts after
        first = store.claim_next(self.c, "analyze")
        oldest = min((i for i in FIXTURES["items"] if not i.get("repost_of")), key=lambda i: i["taken_at"])["id"]
        self.assertEqual(first, oldest)

    def test_repeat_keeps_analysis_unless_content_changes(self):
        store.upsert_items(self.c, FIXTURES["items"])
        iid = FIXTURES["items"][0]["id"]
        from ee.analysis import apply_result
        apply_result(self.c, iid, {"categories": ["travel"], "new_categories": [
            {"slug": "travel", "name": "Travel", "description": "trips"}], "summary": "s", "description": "d",
            "keywords": ["sea"], "people": [], "what": "w", "when": {}, "where": {"place": "Lisbon"},
            "mood": "calm", "language": "en", "context": ""}, "test-model")
        row = self.c.execute("SELECT * FROM items WHERE id=?", (iid,)).fetchone()
        self.assertIsNotNone(row["published_at"])       # analyzed: public, scanned or not
        self.c.execute("UPDATE items SET detection=? WHERE id=?", ('{"matched": false, "hits": []}', iid))
        self.assertTrue(store.gate(self.c, iid)[0])          # a detection never hides an archive item
        tags = {(r["tag"], r["kind"]) for r in self.c.execute("SELECT tag, kind FROM item_tags WHERE item_id=?", (iid,))}
        self.assertIn(("lisbon", "place"), tags)
        self.assertIn(("travel", "category"), tags)
        # the same item again: analysis stays
        c = store.upsert_items(self.c, [FIXTURES["items"][0]])
        self.assertEqual(c["unchanged"], 1)
        self.assertEqual(json.loads(self.c.execute("SELECT categories FROM items WHERE id=?", (iid,)).fetchone()[0]), ["travel"])
        # caption changed: analysis cleared, step pending again
        changed = dict(FIXTURES["items"][0], caption="a new caption")
        c = store.upsert_items(self.c, [changed])
        self.assertEqual(c["changed"], 1)
        row = self.c.execute("SELECT * FROM items WHERE id=?", (iid,)).fetchone()
        self.assertEqual(row["categories"], "[]")
        st = self.c.execute("SELECT state FROM steps WHERE item_id=? AND step='analyze'", (iid,)).fetchone()
        self.assertEqual(st["state"], "pending")

    def test_new_items_go_first_newest_first_then_backlog_oldest_first(self):
        items = [dict(i) for i in FIXTURES["items"][:3]]
        items[0]["priority"] = "new"; items[0]["taken_at"] = "2020-01-01T00:00:00Z"
        items[1]["priority"] = "new"; items[1]["taken_at"] = "2021-01-01T00:00:00Z"
        items[2]["priority"] = "backfill"; items[2]["taken_at"] = "2019-01-01T00:00:00Z"
        store.upsert_items(self.c, items)
        order = [store.claim_next(self.c, "analyze") for _ in range(3)]
        self.assertEqual(order, [items[1]["id"], items[0]["id"], items[2]["id"]])

    def test_failure_backs_off_and_never_reposts(self):
        store.upsert_items(self.c, FIXTURES["items"])
        iid = FIXTURES["items"][0]["id"]
        store.fail_step(self.c, iid, "x", "boom")
        row = self.c.execute("SELECT * FROM steps WHERE item_id=? AND step='x'", (iid,)).fetchone()
        self.assertEqual((row["state"], row["attempts"]), ("failed", 1))
        self.assertIsNotNone(row["next_at"])
        store.set_step(self.c, iid, "x", "posted", remote_id="1")
        store.set_step(self.c, iid, "x", "pending")
        self.assertEqual(self.c.execute("SELECT state FROM steps WHERE item_id=? AND step='x'", (iid,)).fetchone()[0], "posted")

    def test_search_cursor(self):
        cur = store.encode_cursor("2024-05-01T12:00:00Z", "ig_1")
        self.assertEqual(store.decode_cursor(cur), ("2024-05-01T12:00:00Z", "ig_1"))
        self.assertEqual(store.decode_cursor("2024-01-01T00:00:00Z"), ("2024-01-01T00:00:00Z", None))
        self.assertEqual(store.fts_query('beach "x" OR'), '"beach"* "x"* "OR"*')


class PublishRuleTest(unittest.TestCase):
    def test_image_only_reposts_are_never_public(self):
        img = {"type": "image", "url": "items/x/0.jpg"}
        vid = {"type": "video", "url": "items/x/0.mp4"}
        self.assertFalse(store.publishable({"media": [img], "repost_of": {"author": "zuck", "media": [img]}})[0])
        self.assertFalse(store.publishable({"kind": "story", "media": [img], "repost_of": {"author": "a"}})[0])
        self.assertTrue(store.publishable({"media": [img], "repost_of": {"author": "a", "media": [vid]}})[0])
        self.assertTrue(store.publishable({"media": [img], "repost_of": None})[0])   # the owner's own photo
        self.assertTrue(store.publishable({"media": [vid]})[0])


class PlacementTest(unittest.TestCase):
    def test_rules(self):
        from ee.home import placement
        rep = {"repost_of": {"author": "a"}}
        ded, large = {"hl_small"}, "hl_big"
        self.assertEqual(placement(rep, "story", ["hl_small", large], ded)[0], 1.0)   # dedicated
        self.assertEqual(placement(rep, "story", [large], ded)[0], 0.5)               # shared highlight
        self.assertEqual(placement({**rep, "extra": {"repost_source": "reposts tab"}}, "reel", [], ded)[0], 0.25)
        self.assertEqual(placement({}, "reel", [], ded)[0], 1.0)                       # a post
        self.assertEqual(placement({}, "story", [large], ded)[0], 0.5)
        self.assertEqual(placement(rep, "story", [], ded)[0], 0.125)                   # story in no highlight
        self.assertEqual(placement({}, "story", [], ded)[0], 0.125)

    def test_size_formula(self):
        from ee.home import size_parts
        p = {"half_life_days": 30, "age_floor": 0.05, "importance_w": 0.15}
        from datetime import datetime, timedelta, timezone
        t = (datetime.now(timezone.utc) - timedelta(days=30)).strftime("%Y-%m-%dT%H:%M:%SZ")
        r = size_parts(t, 1.0, 0.5, p)
        self.assertAlmostEqual(r["age_factor"], 0.5, places=2)
        self.assertAlmostEqual(r["size"], 0.5 * 0.5 * 1.0, places=2)
        self.assertAlmostEqual(size_parts("2000-01-01T00:00:00Z", 0.0, 1.0, p)["size"], 0.05 * 0.85, places=4)


class AlignTest(unittest.TestCase):
    def test_align_maps_old_tiles_back_and_moves_all(self):
        try:
            import numpy as np
        except ImportError:
            self.skipTest("numpy not installed here")
        from ee.home import _align
        rng = np.random.default_rng(1)
        old = rng.random((5, 2))
        rot = np.array([[0, -1], [1, 0]])
        pts = np.vstack([old @ rot.T * 2 + 3, rng.random((4, 2))])   # 5 placed + 4 new
        out = _align(pts, list(range(5)), old)
        self.assertEqual(out.shape, (9, 2))
        self.assertTrue(np.allclose(out[:5], old, atol=1e-6))


class HitLevelTest(unittest.TestCase):
    def test_hits_take_the_monitors_level(self):
        import sqlite3 as sq
        from ee import home
        tmp = tempfile.TemporaryDirectory()
        mon = Path(tmp.name) / "monitor.sqlite3"
        m = sq.connect(mon)
        m.execute("CREATE TABLE hits (id TEXT, data TEXT, published_at TEXT, section TEXT, level INTEGER, ai_level INTEGER)")
        m.execute("""INSERT INTO hits VALUES ('h1', '{"level_reason": "names the owner"}', '2026-10-25T20:00:00Z', NULL, NULL, 1)""")
        m.execute("INSERT INTO hits VALUES ('h2', '{}', '2026-10-25T20:00:00Z', NULL, 4, 2)")
        m.execute("INSERT INTO hits VALUES ('h3', '{}', '2026-10-25T20:00:00Z', 'dedicated', NULL, NULL)")
        m.commit(); m.close()
        old, home.MONITOR_DB = home.MONITOR_DB, mon
        try:
            c = db.connect(Path(tmp.name) / "b.sqlite3")
            mem = home.members(c)
            self.assertEqual((mem["hit:h1"]["level"], mem["hit:h1"]["curation"]), (1, 1.0))
            self.assertIn("names the owner", mem["hit:h1"]["curation_reason"])
            self.assertEqual(mem["hit:h2"]["level"], 4)
            self.assertIn("owner", mem["hit:h2"]["curation_reason"])
            self.assertEqual(mem["hit:h3"]["level"], 3)   # not rated yet
            c.close()
        finally:
            home.MONITOR_DB = old
            tmp.cleanup()


class StatusTest(unittest.TestCase):
    def test_scrub_removes_secrets_paths_and_queries(self):
        from ee import status
        t = status.scrub("HTTP 401 Bearer abcdefghijklmnopqrstuvwxyz0123456789ABCD at "
                         "https://x.s3.amazonaws.com/items/a.mp4?X-Amz-Signature=deadbeef screenshot "
                         "/var/lib/earth-empire/backend/facebook/1.png token=supersecret")
        for leak in ("abcdefghijklmnopqrstuvwxyz0123456789", "X-Amz", "deadbeef", "/var/lib", "supersecret"):
            self.assertNotIn(leak, t)

    def test_build_hides_unpublished_items(self):
        from ee import status
        tmp = tempfile.TemporaryDirectory()
        c = db.connect(Path(tmp.name) / "s.sqlite3")
        store.upsert_items(c, FIXTURES["items"])
        store.fail_step(c, "ig_test_post", "analyze", "boom with token=abc123456")
        st = status.build(c)
        ids = {x["id"] for x in st["components"]}
        for need in ("api", "db", "workers", "analyzer", "collector", "monitor", "x_poster", "facebook_poster",
                     "disk", "queues"):
            self.assertIn(need, ids)
        public = {r["id"] for r in c.execute("SELECT id FROM items WHERE published_at IS NOT NULL")}
        self.assertTrue(all(e["item"] is None or e["item"] in public for e in st["activity"]["events"]))
        self.assertNotIn("abc123456", json.dumps(st))
        c.close()
        tmp.cleanup()


class ComposeTest(unittest.TestCase):
    def item(self, **kw):
        base = {"id": "ig_1", "kind": "reel", "taken_at": "2024-05-01T12:00:00Z", "caption": "Sunset at the beach",
                "categories": ["travel", "street-food"], "description": "The owner films the sunset in Lisbon.",
                "highlights": [{"id": "hl_1", "title": "Portugal"}],
                "media": [{"type": "video", "url": "https://m/items/ig_1/0.mp4"}]}
        base.update(kw)
        return base

    def test_single_tweet(self):
        p = compose.build(self.item())
        t = compose.x_thread(p)
        self.assertEqual(len(t), 1)
        self.assertIn("1 May 2024", t[0]["text"])
        self.assertIn("Highlights: Portugal", t[0]["text"])
        self.assertIn("#travel #streetFood", t[0]["text"])
        self.assertEqual(t[0]["media"], [0])

    def test_thread_when_long(self):
        cap = " ".join(["Це довгий підпис про подорож."] * 40)
        t = compose.x_thread(compose.build(self.item(caption=cap)))
        self.assertGreater(len(t), 2)
        for tw in t:
            self.assertLessEqual(compose.x_len(tw["text"]), 280)
        self.assertTrue(t[0]["text"].startswith("Reel from 1 May 2024"))
        self.assertIn("#travel", t[-1]["text"])
        self.assertIn(f"(1/{len(t)})", t[0]["text"])

    def test_repost_credit_and_original_media(self):
        it = self.item(repost_of={"author": "someone", "source_url": "https://www.instagram.com/reel/ABC/",
                                  "media": [{"type": "video", "url": "https://m/items/ig_1/r0.mp4"}]})
        p = compose.build(it)
        self.assertEqual(p.media[0]["url"], "https://m/items/ig_1/r0.mp4")
        self.assertIn("Reel by @someone https://www.instagram.com/reel/ABC/", compose.x_thread(p)[0]["text"])

    def test_media_groups(self):
        media = [{"type": "image", "url": f"https://m/{i}.jpg"} for i in range(6)] + [{"type": "video", "url": "https://m/v.mp4"}]
        t = compose.x_thread(compose.build(self.item(kind="carousel", media=media)))
        self.assertEqual([x["media"] for x in t], [[0, 1, 2, 3], [4, 5], [6]])

    def test_weighted_length(self):
        self.assertEqual(compose.x_len("abc https://example.com/very/long/path"), 4 + 23)
        self.assertEqual(compose.x_len("日本"), 4)


class HeardTest(unittest.TestCase):
    """The phrase spoken per video, from cached transcripts; Claude stubbed (no network)."""

    def setUp(self):
        from unittest import mock
        from ee import aicoin, heard
        self.heard, self.mock = heard, mock
        self.tmp = tempfile.TemporaryDirectory()
        self.c = db.connect(Path(self.tmp.name) / "h.sqlite3")
        store.upsert_items(self.c, FIXTURES["items"])
        store.upsert_highlights(self.c, [{"id": "hl_3", "title": "3", "item_ids": ["ig_test_story", "ig_test_reel"]}])
        for key, segs in (("items/ig_test_story/0.mp4", [(0.0, 2.1, "ну що"), (2.1, 3.4, "у тебе 3")]),
                          ("items/ig_test_reel/0.mp4", [(1.0, 2.0, "у тебе 3, так")])):
            self.c.execute("INSERT INTO transcripts(media, language, text, segments, created_at) VALUES (?,?,?,?,?)",
                           (key, "uk", " ".join(t for *_, t in segs),
                            json.dumps([{"start": a, "end": b, "text": t} for a, b, t in segs]), "2026-10-26T00:00:00Z"))
        self.calls = []
        self.answer = None

        def claude(body, timeout=0):
            self.calls.append(body)
            prompt = body["messages"][0]["content"]
            items = self.answer(prompt) if self.answer else []
            return {"content": [{"type": "text", "text": json.dumps({"items": items})}], "model": "claude-test",
                    "stop_reason": "end_turn", "usage": {"input_tokens": 100, "output_tokens": 20}}, 1.0
        self.patch = mock.patch.object(aicoin, "claude", claude)
        self.patch.start()

    def tearDown(self):
        self.patch.stop()
        self.c.close()
        self.tmp.cleanup()

    def entry(self, n, text, hl, start=2.1, end=3.4, conf=0.9):
        return {"n": n, "text": text, "highlight_id": hl, "media": 0, "start": start, "end": end, "confidence": conf}

    def test_batch_stores_phrase_label_and_api_shapes(self):
        h = self.heard
        q = h.pending(self.c)
        self.assertEqual(set(q), {"ig_test_story", "ig_test_reel"})   # videos with cached speech only
        self.answer = lambda p: [self.entry(0, " «у тебе 3» ", "hl_3"), self.entry(1, "у тебе 3", "hl_bogus", conf=0.7)]
        res = h.run_batch(self.c, h.batch(self.c, q))
        self.assertEqual(len(self.calls), 1)                            # both items in one call
        prompt = self.calls[0]["messages"][0]["content"]
        self.assertIn("[2.1-3.4] у тебе 3", prompt)
        self.assertIn("hl_3: '3'", prompt)
        self.assertEqual(res["answered"], 2)
        self.assertEqual(h.pending(self.c), [])
        row = self.c.execute("SELECT * FROM items WHERE id=?", (q[0],)).fetchone()
        item = store.render_item(self.c, row)
        self.assertEqual(item["heard"]["text"], "у тебе 3")
        self.assertEqual((item["heard"]["highlight_id"], item["heard"]["start"], item["heard"]["end"]), ("hl_3", 2.1, 3.4))
        self.assertEqual(item["heard"]["model"], "claude-test")
        # the highlight keeps its title; the label is the phrase most of its videos say
        hl = store.render_highlight(self.c.execute("SELECT * FROM highlights WHERE id='hl_3'").fetchone())
        self.assertEqual((hl["title"], hl["heard_label"]), ("3", "у тебе 3"))
        self.assertIn("2 of its 2", hl["heard_reason"])
        # cost recorded under its own purpose
        self.assertEqual(self.c.execute("SELECT COUNT(*) n FROM costs WHERE purpose='heard'").fetchone()["n"], 1)
        # a changed highlight title means work it out again; the label survives re-ingest
        store.upsert_highlights(self.c, [{"id": "hl_3", "title": "у тебе 3", "item_ids": ["ig_test_story", "ig_test_reel"]}])
        self.assertEqual(set(h.pending(self.c)), {"ig_test_story", "ig_test_reel"})
        self.assertEqual(self.c.execute("SELECT heard_label FROM highlights WHERE id='hl_3'").fetchone()[0], "у тебе 3")

    def test_nothing_heard_is_null_and_done(self):
        h = self.heard
        self.answer = lambda p: [{"n": i, "text": None, "highlight_id": None, "media": None, "start": None,
                                  "end": None, "confidence": 0.1} for i in range(2)]
        h.run_batch(self.c, h.pending(self.c))
        self.assertEqual(h.pending(self.c), [])
        self.assertIsNone(store.render_item(self.c, self.c.execute(
            "SELECT * FROM items WHERE id='ig_test_reel'").fetchone())["heard"])
        hl = self.c.execute("SELECT * FROM highlights WHERE id='hl_3'").fetchone()
        self.assertIsNone(hl["heard_label"])
        self.assertIn("nothing", hl["heard_reason"])
        self.assertEqual(h.counts(self.c), {"with_speech": 2, "done": 2, "queue": 0, "heard": 0})

    def test_missing_answers_raise_and_new_transcript_requeues(self):
        h = self.heard
        self.answer = lambda p: [self.entry(0, "у тебе 3", "hl_3")]
        ids = h.pending(self.c)
        with self.assertRaises(h.PartialAnswer) as cm:
            h.run_batch(self.c, ids)
        self.assertEqual(cm.exception.missing, [ids[1]])
        self.assertEqual(h.pending(self.c), [ids[1]])
        h.give_up(self.c, cm.exception.missing)
        self.assertEqual(h.pending(self.c), [])
        self.c.execute("UPDATE transcripts SET created_at='2026-10-27T00:00:00Z' WHERE media='items/ig_test_reel/0.mp4'")
        self.assertEqual(h.pending(self.c), ["ig_test_reel"])

    def test_label_picks_the_most_common_phrase(self):
        lab, why = self.heard.label_for("3", [{"text": "У тебе 3!", "confidence": 0.6}, {"text": "у тебе 3", "confidence": 0.9},
                                              {"text": "в тебе три", "confidence": 0.95}, {"text": "щось", "confidence": 0.1}], 5)
        self.assertEqual(lab, "у тебе 3")
        self.assertIn("2 of its 5", why)
        self.assertIn("short for it", why)

    def test_lane_runs_alongside_analysis_and_status_shows_it(self):
        import types
        try:
            import httpx  # noqa: F401
        except ImportError:
            sys.modules["httpx"] = types.ModuleType("httpx")
        from ee import status, worker
        self.answer = lambda p: [self.entry(i, "у тебе 3", "hl_3") for i in range(2)]
        with self.mock.patch.object(worker.stop, "wait", lambda *_: None):
            # every job runs in parallel: heard does not wait while items wait for analysis
            self.assertTrue(worker.heard_once(self.c))
            self.assertFalse(worker.heard_once(self.c))      # nothing left
        comp = next(x for x in status.build(self.c)["components"] if x["id"] == "heard")
        self.assertEqual((comp["details"]["queue"], comp["details"]["done"], comp["details"]["heard"]), (0, 2, 2))
        self.assertEqual(comp["details"]["calls_today"], 1)
        self.assertIsNotNone(comp["last_success"])


if __name__ == "__main__":
    unittest.main()


class WorkerTest(unittest.TestCase):
    def test_worker_imports_and_has_every_lane(self):
        import importlib
        import types
        try:
            import httpx  # noqa: F401
        except ImportError:   # the box has it; a bare local python may not
            sys.modules["httpx"] = types.ModuleType("httpx")
        w = importlib.import_module("ee.worker")
        for fn in ("analyze_once", "thumbs_once", "home_once", "importance_once", "heard_once", "facets_once", "rubric_once", "x_once", "facebook_once",
                   "house_once", "site_once", "main"):
            self.assertTrue(callable(getattr(w, fn, None)), fn)


class ExplainTest(unittest.TestCase):
    """The "?" of the fullscreen viewer: a post by its caption, anything else by its analysis; cached; capped."""

    def setUp(self):
        from ee import aicoin, explain
        self.tmp = tempfile.TemporaryDirectory()
        self.c = db.connect(Path(self.tmp.name) / "t.sqlite3")
        self.explain, self.prompts = explain, []

        def fake(body, timeout=300):
            self.prompts.append(body["messages"][0]["content"])
            return {"model": "claude-test", "usage": {"input_tokens": 10, "output_tokens": 5},
                    "content": [{"type": "text", "text": "Що відбувається."}]}, 0.01
        self.real, aicoin.claude = aicoin.claude, fake

    def tearDown(self):
        from ee import aicoin
        aicoin.claude = self.real
        self.c.close()
        self.tmp.cleanup()

    def row(self, kind, data, analysis=None):
        self.c.execute("INSERT INTO items(id, kind, taken_at, data, content_hash, analysis, summary, published_at, updated_at) "
                       "VALUES (?,?,?,?,?,?,?,?,?)", (f"ig_{kind}", kind, "2026-10-24T10:00:00Z", json.dumps(data), "h",
                                                      json.dumps(analysis or {"what": "a walk"}), "A walk", db.now(), db.now()))
        return self.c.execute("SELECT * FROM items WHERE id=?", (f"ig_{kind}",)).fetchone()

    def test_language_tags(self):
        self.assertEqual(self.explain.normalize("uk-UA"), "uk")
        self.assertEqual(self.explain.normalize("en_GB"), "en")
        self.assertIsNone(self.explain.normalize("<script>"))

    def test_post_uses_its_caption_story_its_analysis(self):
        post = self.row("post", {"caption": "Мій ранок у Лісабоні"})
        out = self.explain.explain(self.c, post, "en")
        self.assertEqual(out["mode"], "caption")
        self.assertIn("Мій ранок у Лісабоні", self.prompts[-1])
        story = self.row("story", {"caption": "ignored"}, {"what": "surfing at Ericeira"})
        self.assertEqual(self.explain.explain(self.c, story, "uk")["mode"], "analysis")
        self.assertIn("surfing at Ericeira", self.prompts[-1])
        self.assertIn("Ukrainian", self.prompts[-1])

    def test_cached_then_capped(self):
        post = self.row("post", {"caption": "Hello"})
        self.assertFalse(self.explain.explain(self.c, post, "de")["cached"])
        self.assertTrue(self.explain.explain(self.c, post, "de")["cached"])
        self.assertEqual(len(self.prompts), 1)
        db.set_setting(self.c, "explain.daily_cap", "1")
        with self.assertRaises(self.explain.CapReached):
            self.explain.explain(self.c, post, "fr")


class HeardDescriptionTest(unittest.TestCase):
    """Videos in no highlight: the post's description is the reference the spoken words are matched to."""

    def test_description_is_the_caption_line_else_the_first_sentence(self):
        from ee import heard
        tmp = tempfile.TemporaryDirectory()
        c = db.connect(Path(tmp.name) / "t.sqlite3")
        data = {"caption": "#ukraine\nВітаю з днем міста @kyiv #kyiv\nmore", "media": [{"type": "video", "url": "key:items/a/0.mp4"}]}
        c.execute("INSERT INTO items(id, kind, taken_at, data, content_hash, description, updated_at) VALUES (?,?,?,?,?,?,?)",
                  ("ig_a", "reel", "2026-10-24T10:00:00Z", json.dumps(data), "h", "A greeting. Then more.", db.now()))
        row = c.execute("SELECT * FROM items WHERE id='ig_a'").fetchone()
        self.assertEqual(heard.description(row), "Вітаю з днем міста")
        c.execute("UPDATE items SET data=? WHERE id='ig_a'", (json.dumps({"media": data["media"]}),))
        self.assertEqual(heard.description(c.execute("SELECT * FROM items WHERE id='ig_a'").fetchone()), "A greeting.")
        c.close()
        tmp.cleanup()

    def test_owner_label_stands_and_empty_hands_it_back(self):
        from ee import heard
        tmp = tempfile.TemporaryDirectory()
        c = db.connect(Path(tmp.name) / "t.sqlite3")
        data = {"caption": "Hi", "media": [{"type": "video", "url": "key:items/b/0.mp4"}]}
        c.execute("INSERT INTO items(id, kind, taken_at, data, content_hash, updated_at) VALUES (?,?,?,?,?,?)",
                  ("ig_b", "reel", "2026-10-24T10:00:00Z", db.j(data), "h", db.now()))
        c.execute("INSERT INTO transcripts(media, language, text, segments, created_at) VALUES (?,?,?,?,?)",
                  ("items/b/0.mp4", "uk", "у тебе 3", json.dumps([{"start": 1, "end": 2, "text": "у тебе 3"}]), db.now()))
        self.assertIn("ig_b", heard.pending(c))
        h = heard.set_by_owner(c, "ig_b", "  у  тебе 3 ")
        self.assertEqual((h["text"], h["by"]), ("у тебе 3", "owner"))
        self.assertNotIn("ig_b", heard.pending(c))       # the job leaves the owner's label alone
        self.assertIsNone(heard.set_by_owner(c, "ig_b", ""))
        self.assertIn("ig_b", heard.pending(c))          # handed back
        c.close()
        tmp.cleanup()


class OwnFirstTest(unittest.TestCase):
    """The analyzer takes the owner's own posts and stories before reposts; own_only leaves reposts waiting."""

    def test_own_before_reposts_and_reserve(self):
        tmp = tempfile.TemporaryDirectory()
        c = db.connect(Path(tmp.name) / "t.sqlite3")
        for iid, data, taken in (("ig_rep", {"repost_of": {"author": "x"}, "media": []}, "2026-01-01T00:00:00Z"),
                                 ("ig_own", {"repost_of": None, "media": []}, "2026-06-01T00:00:00Z")):
            c.execute("INSERT INTO items(id, kind, taken_at, data, content_hash, updated_at) VALUES (?,?,?,?,?,?)",
                      (iid, "story", taken, db.j(data), "h", db.now()))
            c.execute("INSERT INTO steps(item_id, step, state, attempts, updated_at) VALUES (?,?,?,?,?)",
                      (iid, "analyze", "pending", 0, db.now()))
        self.assertEqual(store.claim_next(c, "analyze"), "ig_own")   # older repost waits behind the owner's own
        self.assertIsNone(store.claim_next(c, "analyze", own_only=True))
        self.assertEqual(store.claim_next(c, "analyze"), "ig_rep")
        c.close()
        tmp.cleanup()


class FacetsTest(unittest.TestCase):
    """Categories improve from Claude's own notes; new videos join their categories between runs."""

    def setUp(self):
        from ee import aicoin, facets
        self.tmp = tempfile.TemporaryDirectory()
        self.c = db.connect(Path(self.tmp.name) / "t.sqlite3")
        db.set_setting(self.c, "analysis.enabled", "1")
        self.facets, self.prompts = facets, []
        self.notes = "Royals keep growing; split by country next time."

        def fake(body, timeout=300):
            self.prompts.append(body["messages"][0]["content"])
            out = {"notes": self.notes, "facets": [{"id": "themes", "name": "Themes", "description": "",
                   "categories": [{"id": "royals", "name": "Royals", "description": "", "items": [0, 1]}]}]}
            return {"model": "claude-test", "usage": {"input_tokens": 10, "output_tokens": 5}, "stop_reason": "end_turn",
                    "content": [{"type": "text", "text": json.dumps(out)}]}, 0.01
        self.real, aicoin.claude = aicoin.claude, fake
        self.real_hits, facets.published_hit_ids = facets.published_hit_ids, lambda: []
        for n in range(3):
            self.add(f"ig_{n}", f"2026-10-2{n}T10:00:00Z")

    def tearDown(self):
        from ee import aicoin
        aicoin.claude = self.real
        self.facets.published_hit_ids = self.real_hits
        self.c.close()
        self.tmp.cleanup()

    def add(self, i, at):
        self.c.execute("INSERT INTO items(id, kind, taken_at, data, content_hash, summary, published_at, updated_at) "
                       "VALUES (?,?,?,?,?,?,?,?)", (i, "reel", at, "{}", "h", "A king", db.now(), db.now()))

    def test_notes_are_kept_and_read_by_the_next_run(self):
        self.facets.run(self.c)
        self.assertIn("first run", self.prompts[-1])
        self.assertEqual(self.facets.current(self.c)["notes"], self.notes)
        self.c.execute("UPDATE settings SET value='2000-01-01T00:00:00Z' WHERE key='facets.last_run'")
        self.facets.run(self.c)
        self.assertIn(self.notes, self.prompts[-1])
        self.assertIn('"in_no_category"', self.prompts[-1])
        self.assertEqual(self.c.execute("SELECT COUNT(*) FROM facet_notes").fetchone()[0], 2)

    def test_runs_are_spread_over_the_day(self):
        self.facets.run(self.c)
        self.add("ig_new", "2026-10-26T10:00:00Z")
        ok, why = self.facets.due(self.c)
        self.assertFalse(ok, why)   # 12 a day: not again within 2 hours, however much arrives

    def test_new_videos_join_their_nearest_category_without_ai(self):
        try:
            import numpy as np
        except ImportError:
            self.skipTest("numpy")
        from ee import home
        self.facets.run(self.c)
        self.add("ig_new", "2026-10-26T10:00:00Z")
        v = {"ig_0": [1, 0], "ig_1": [0.9, 0.1], "ig_2": [0, 1], "ig_new": [0.95, 0.05]}
        real, home.vectors = home.vectors, lambda c, ids=None: {k: np.array(x, dtype=np.float32) / np.linalg.norm(x) for k, x in v.items()}
        try:
            self.assertEqual(self.facets.place_new(self.c), 1)
            self.assertEqual(self.facets.place_new(self.c), 0)
        finally:
            home.vectors = real
        cat = self.facets.public_view(self.c)["facets"][0]["categories"][0]
        self.assertIn("ig_new", cat["item_ids"])
        self.assertEqual(self.facets.fared(self.c, self.facets.current(self.c))["categories"][0]["joined_by_similarity_since"], 1)


class HighlightRenameTest(unittest.TestCase):
    """A renamed highlight: every item shows its new name, whatever name the item was collected with."""

    def test_items_show_the_current_name(self):
        tmp = tempfile.TemporaryDirectory()
        c = db.connect(Path(tmp.name) / "t.sqlite3")
        data = {"caption": "", "media": [], "highlights": [{"id": "hl_1", "title": "Old name"}]}
        c.execute("INSERT INTO items(id, kind, taken_at, data, content_hash, published_at, updated_at) VALUES (?,?,?,?,?,?,?)",
                  ("ig_h", "story", "2026-10-24T10:00:00Z", db.j(data), "h", db.now(), db.now()))
        store.upsert_highlights(c, [{"id": "hl_1", "title": "New name", "item_ids": ["ig_h"]}])
        d = store.render_item(c, c.execute("SELECT * FROM items WHERE id='ig_h'").fetchone())
        self.assertEqual([h["title"] for h in d["highlights"]], ["New name"])
        c.close()
        tmp.cleanup()


class ExpandTest(unittest.TestCase):
    """A shortened highlight name is written out once; cards get it; renaming asks again."""

    def test_shortened_names_are_written_out(self):
        from ee import aicoin, expand
        tmp = tempfile.TemporaryDirectory()
        c = db.connect(Path(tmp.name) / "t.sqlite3")
        asked = []

        def fake(body, timeout=120):
            asked.append(body["messages"][0]["content"])
            names = [{"n": 0, "full": "планета"}, {"n": 1, "full": "у Тараса 3"}]
            return {"model": "claude-test", "usage": {}, "content": [{"type": "text", "text": json.dumps({"names": names})}]}, 0.01
        real, aicoin.claude = aicoin.claude, fake
        try:
            c.execute("INSERT INTO items(id, kind, taken_at, data, content_hash, published_at, updated_at) VALUES (?,?,?,?,?,?,?)",
                      ("ig_p", "story", "2026-10-24T10:00:00Z", db.j({"media": []}), "h", db.now(), db.now()))
            store.upsert_highlights(c, [{"id": "hl_1", "title": "плнт", "item_ids": ["ig_p"]},
                                        {"id": "hl_2", "title": "у Тараса 3", "item_ids": []}])
            self.assertEqual(expand.run(c), 2)
            self.assertEqual(expand.run(c), 0)          # done once
            d = store.render_item(c, c.execute("SELECT * FROM items WHERE id='ig_p'").fetchone())
            self.assertEqual((d["highlights"][0]["title"], d["highlights"][0]["title_full"]), ("плнт", "планета"))
            hl2 = store.render_highlight(c.execute("SELECT * FROM highlights WHERE id='hl_2'").fetchone())
            self.assertIsNone(hl2["title_full"])          # not shortened: nothing to write out
            store.upsert_highlights(c, [{"id": "hl_1", "title": "прзд", "item_ids": ["ig_p"]}])
            d = store.render_item(c, c.execute("SELECT * FROM items WHERE id='ig_p'").fetchone())
            self.assertIsNone(d["highlights"][0]["title_full"])   # renamed: the old full name is not shown
            self.assertEqual(len(expand.pending(c)), 1)
        finally:
            aicoin.claude = real
            c.close()
            tmp.cleanup()
