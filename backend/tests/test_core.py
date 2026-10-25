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

    def test_ingest_creates_pipeline_and_hides_until_analyzed(self):
        counts = store.upsert_items(self.c, FIXTURES["items"])
        self.assertEqual(counts["inserted"], len(FIXTURES["items"]))
        st = store.pipeline_status(self.c)
        self.assertEqual(st["steps"]["analyze"]["pending"], len(FIXTURES["items"]))
        self.assertEqual(self.c.execute("SELECT COUNT(*) n FROM items WHERE published_at IS NOT NULL").fetchone()["n"], 0)
        # oldest first
        first = store.claim_next(self.c, "analyze")
        oldest = min(FIXTURES["items"], key=lambda i: i["taken_at"])["id"]
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


class CurationTest(unittest.TestCase):
    def test_rules(self):
        from ee.home import curation
        rep = {"repost_of": {"author": "a"}}
        ded, large = {"hl_small"}, "hl_big"
        self.assertEqual(curation(rep, "story", ["hl_small", large], ded)[0], 1.0)
        self.assertEqual(curation(rep, "story", [large], ded)[0], 0.5)
        self.assertEqual(curation({**rep, "extra": {"repost_source": "reposts tab"}}, "reel", [], ded)[0], 0.25)
        self.assertEqual(curation({}, "reel", [], ded)[0], 0.5)            # own post, the default
        self.assertEqual(curation({}, "story", [large], ded)[0], 0.5)
        self.assertEqual(curation(rep, "story", [], ded)[0], 0.25)


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
        self.assertTrue(all(e["item"] is None for e in st["activity"]["events"]))
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
        for fn in ("analyze_once", "thumbs_once", "home_once", "importance_once", "x_once", "facebook_once",
                   "house_once", "site_once", "main"):
            self.assertTrue(callable(getattr(w, fn, None)), fn)
