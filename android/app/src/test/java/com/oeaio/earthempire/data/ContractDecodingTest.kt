package com.oeaio.earthempire.data

import com.oeaio.earthempire.TestSupport
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/** CONTRACT.md "The data", decoded the way the app reads the API. */
class ContractDecodingTest {
    private fun item(json: String) = ContractJson.decodeFromString(Item.serializer(), json)

    @Test fun fixtureDecodesCompletely() {
        val f = ContractJson.decodeFromString(Fixture.serializer(), TestSupport.fixtureJson)
        assertEquals(14, f.items.size)
        assertEquals(3, f.highlights.size)
        assertTrue(f.items.all { it.kind != ItemKind.Unknown })
        assertTrue(f.items.all { it.analysis != null })
        val carousel = f.items.first { it.kind == ItemKind.Carousel }
        assertEquals(listOf("image", "image", "video", "image"), carousel.media.map { it.type })
        assertTrue(f.items.any { it.repostOf != null })
    }

    @Test fun fullItemAsTheLiveApiSendsIt() {
        val i = item("""
        {"id": "ig_test_repost", "kind": "story", "shortcode": null, "source_url": null, "taken_at": "2024-04-01T08:00:00Z",
         "caption": null, "hashtags": [], "mentions": ["blender_test"], "tagged_users": [{"username": "a", "x": 0.5}],
         "location": null, "music": null, "alt_text": null,
         "stickers": [{"type": "mention", "text": "@blender_test", "extra": {}}], "counts": {"likes": 12.0, "views": 3},
         "media": [{"type": "image", "url": "https://media.empire.earth/items/ig_test_post/0.jpg", "width": 1280, "height": 853, "duration": null}],
         "highlights": [{"id": "hl_1", "title": "Travel"}],
         "repost_of": {"author": "blender_test", "author_name": "Blender Test", "shortcode": "TESTorig1",
           "source_url": "https://www.instagram.com/reel/TESTorig1/", "taken_at": "2024-03-30T10:00:00Z", "caption": "Lava",
           "media": [{"type": "video", "url": "https://media.empire.earth/items/ig_test_repost/r0.mp4", "width": 1280, "height": 720,
                      "duration": 10.0, "cover": "https://media.empire.earth/items/ig_test_repost/r0.cover.jpg", "cover_at": 6.26}]},
         "extra": {"test": true}, "collected_at": "2026-10-25T12:29:13Z", "categories": ["travel"], "summary": "S", "description": "D",
         "analysis": {"people": [{"who": "@blender_test", "description": "Author", "basis": "mention", "role": "original author"},
                                 {"who": null, "description": "Legs", "basis": "description only", "appears": [{"media": 1, "from": 8, "to": 10}]}],
                      "what": "W", "events": [{"media": 1, "at": 1.2, "text": "Title card"}],
                      "when": {"date": "2024-03-30", "basis": "caption"}, "where": {"place": "Hawaii", "kind": "volcano", "basis": "signage"},
                      "speech": {"language": "en", "transcript": "Hello"}, "keywords": ["lava"], "future_field": [1, 2]},
         "published_at": "2026-10-25T12:30:00Z", "brand_new_top_level": {"x": 1}}
        """)
        assertEquals(ItemKind.Story, i.kind)
        assertEquals(12L, i.count("likes"))
        assertNull(i.count("comments"))
        assertEquals("blender_test", i.repostOf?.author)
        // Analysis media indices count the item's own media, then the original's.
        assertEquals(2, i.allMedia.size)
        assertTrue(i.allMedia[i.analysis!!.events[0].media].isVideo)
        assertEquals("https://media.empire.earth/items/ig_test_repost/r0.cover.jpg", i.allMedia[1].poster)
        assertEquals(6.26, i.allMedia[1].coverAt!!, 1e-9)
        assertEquals("mention", i.analysis!!.people[0].basis)
        assertNull(i.analysis!!.people[1].who)
        assertEquals(8.0, i.analysis!!.people[1].appears[0].from!!, 1e-9)
        assertEquals("Hawaii", i.analysis!!.where?.place)
        assertTrue(i.extra!!.containsKey("test"))
    }

    @Test fun minimalAndUnknownValuesStillDecode() {
        val i = item("""{"id": "ig_1", "kind": "guide", "media": [{"url": "u"}], "analysis": null, "counts": {"likes": null}}""")
        assertEquals(ItemKind.Unknown, i.kind)
        assertEquals("image", i.media[0].type)
        assertFalse(i.media[0].isVideo)
        assertEquals("u", i.poster)
        assertNull(i.count("likes"))
        assertTrue(i.hashtags.isEmpty())
    }

    @Test fun nullListsAreCoercedToEmpty() {
        val i = item("""{"id": "ig_2", "kind": "post", "hashtags": null, "media": [], "highlights": null}""")
        assertTrue(i.hashtags.isEmpty())
        assertTrue(i.highlights.isEmpty())
        assertNull(i.poster)
    }

    @Test fun pagesAndListsDecode() {
        val page = ContractJson.decodeFromString(ItemPage.serializer(), """{"items": [{"id": "a", "kind": "reel"}], "next": "Y3Vy"}""")
        assertEquals("Y3Vy", page.next)
        val end = ContractJson.decodeFromString(ItemPage.serializer(), """{"items": [], "next": null}""")
        assertNull(end.next)
        val tags = ContractJson.decodeFromString(TagList.serializer(), """{"tags":[{"tag":"eiffel tower","kind":"keyword","count":2},{"tag":"eiffel tower","kind":"object","count":3}]}""").tags
        assertEquals(1, TagIndex.dedupe(tags).size)
        assertEquals("object", TagIndex.dedupe(tags)[0].kind)
        val hl = ContractJson.decodeFromString(HighlightList.serializer(), """{"highlights":[{"id":"hl_test_events","title":"Events","cover":null,"item_ids":["ig_test_story"],"updated_at":"2026-10-25T12:30:04Z"}]}""")
        assertEquals(listOf("ig_test_story"), hl.highlights[0].itemIds)
        val p = ContractJson.decodeFromString(Profile.serializer(), """{"username":"earth_empire_test","full_name":"Test Profile","bio":"Fixture profile","avatar":null,"links":[],"counts":{"posts":5,"followers":10,"following":3}}""")
        assertEquals(10L, p.count("followers"))
    }

    @Test fun statusAsTheContractDefinesIt() {
        val s = ContractJson.decodeFromString(StatusReport.serializer(), """
        {"generated_at": "2026-10-25T13:00:00Z", "overall": "degraded",
         "components": [{"id": "api", "name": "API", "state": "ok", "last_success": "2026-10-25T13:00:00Z", "last_error": null, "details": {"rps": 1.5}},
                        {"id": "queues", "name": "Queues", "state": "ok", "details": {"analyze": {"pending": 3, "done": 10}}},
                        {"id": "x_poster", "state": "off", "last_error": {"at": "2026-10-25T12:00:00Z", "message": "429"}}],
         "activity": {"jobs": [{"component": "analyzer", "what": "Analyzing ig_1", "item": null, "progress": 0.4, "started_at": "2026-10-25T12:59:00Z", "elapsed_s": 60}],
                      "events": [{"at": "2026-10-25T12:58:00Z", "component": "collector", "kind": "run", "text": "Run finished", "item": "ig_1", "ok": true}]}}
        """)
        assertEquals("degraded", s.overall)
        assertEquals(3, s.components.size)
        assertEquals("x_poster", s.components[2].title)
        assertEquals("429", s.components[2].lastError?.message)
        assertEquals(0.4f, s.activity.jobs[0].fraction!!, 1e-6f)
        assertEquals("ig_1", s.activity.events[0].item)
    }

    @Test fun monitorHitsAndPhrases() {
        val page = ContractJson.decodeFromString(MonitorPage.serializer(), """
        {"hits": [{"id": "h1", "reason": "name", "matched": "Тарасе", "language": "uk", "excerpt": "Дякую, Тарасе", "translation": "Thank you, Taras",
                   "confidence": 0.42, "at": 102.5, "video": {"id": "v", "url": "https://x/v.mp4"}, "source": {"id": "s", "account": "mfa"}}], "next": null}""")
        val h = page.hits[0]
        assertTrue(h.isLowConfidence)
        assertEquals("Name heard: “Тарасе”", h.reasonLabel)
        assertFalse(h.isAdded)
        val flagged = h.copy(confidence = 0.9, lowConfidenceFlag = true)
        assertTrue(flagged.isLowConfidence)
        val phrases = ContractJson.decodeFromString(PhraseList.serializer(), """{"phrases":[{"text":"тарас","variants":["тараса","taras"]},{"text":"маслов"}]}""").phrases
        assertEquals(listOf("тараса", "taras"), phrases[0].variants)
        assertTrue(phrases[1].variants.isEmpty())
    }

    @Test fun queryParamsSkipEmptyFilters() {
        assertEquals(emptyList<Pair<String, String>>(), ItemQuery(q = "  ", category = "").params())
        assertEquals(listOf("kind" to "reel", "tag" to "beach", "q" to "sea"), ItemQuery(kind = ItemKind.Reel, tag = "beach", q = " sea ").params())
    }

    @Test fun datesAndClock() {
        assertNotNull(Dates.parse("2024-05-01T12:00:00Z"))
        assertNotNull(Dates.parse("2024-05-01T12:00:00.123+02:00"))
        assertNotNull(Dates.parse("2024-05-01"))
        assertNull(Dates.parse("soon"))
        assertEquals("1:05", Dates.clock(65.9))
        assertEquals("1:02:03", Dates.clock(3723.0))
        assertEquals("1.2K", Dates.compact(1234))
    }
}
