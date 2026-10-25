package com.oeaio.earthempire.data

import com.oeaio.earthempire.TestSupport
import kotlinx.coroutines.test.runTest
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Assert.fail
import org.junit.Test

class PagingTest {
    private val fixture = ContractJson.decodeFromString(Fixture.serializer(), TestSupport.fixtureJson)

    @Test fun pagerFollowsCursorsDropsRepeatsAndStops() = runTest {
        val pages = mapOf<String?, Pair<List<String>, String?>>(
            null to (listOf("a", "b") to "c1"),
            "c1" to (listOf("b", "c") to "c2"),   // "b" again: the list must not show it twice
            "c2" to (listOf("d") to null),
        )
        val asked = mutableListOf<String?>()
        val pager = Pager<String>({ it }) { c -> asked += c; pages.getValue(c) }
        pager.refresh()
        assertEquals(listOf("a", "b"), pager.items)
        assertTrue(pager.loadMore())
        assertTrue(pager.loadMore())
        assertEquals(listOf("a", "b", "c", "d"), pager.items)
        assertTrue(pager.isComplete)
        assertFalse(pager.loadMore())
        assertEquals(listOf(null, "c1", "c2"), asked)
    }

    @Test fun aCursorThatRepeatsItselfEndsPaging() = runTest {
        val pager = Pager<String>({ it }) { c -> (if (c == null) listOf("a") else listOf("b")) to "same" }
        pager.refresh(); pager.loadMore()
        assertEquals(listOf("a", "b"), pager.items)
        assertTrue(pager.isComplete)
    }

    @Test fun aFailedPageCanBeRetried() = runTest {
        var fail = true
        val pager = Pager<String>({ it }) { c ->
            if (c == "n" && fail) { fail = false; throw java.io.IOException("offline") }
            (if (c == null) listOf("a") else listOf("b")) to (if (c == null) "n" else null)
        }
        pager.refresh()
        try { pager.loadMore(); fail("expected the error") } catch (e: java.io.IOException) { }
        assertTrue(pager.loadMore())
        assertEquals(listOf("a", "b"), pager.items)
    }

    @Test fun refreshStartsOver() = runTest {
        var round = 0
        val pager = Pager<String>({ it }) { c -> if (c == null) listOf("r$round") to "x" else listOf("more") to null }
        pager.refresh(); pager.loadMore(); round = 1; pager.refresh()
        assertEquals(listOf("r1"), pager.items)
        assertFalse(pager.isComplete)
    }

    @Test fun sampleApiPagesThroughEverythingNewestFirst() = runTest {
        val api = SampleApi(fixture)
        val pager = Pager<Item>({ it.id }) { c -> val p = api.items(ItemQuery(), c, 4); p.items to p.next }
        pager.refresh()
        while (pager.loadMore()) Unit
        assertEquals(fixture.items.size, pager.items.size)
        val times = pager.items.map { Dates.parse(it.takenAt)!! }
        assertEquals(times.sortedDescending(), times)
    }

    @Test fun sampleApiFilters() = runTest {
        val api = SampleApi(fixture)
        assertTrue(api.items(ItemQuery(kind = ItemKind.Reel), null, 50).items.all { it.kind == ItemKind.Reel })
        val hl = fixture.highlights[0]
        assertTrue(api.items(ItemQuery(highlight = hl.id), null, 50).items.all { i -> i.highlights.any { it.id == hl.id } })
        val tag = api.tags(limit = 1).first().tag
        assertTrue(api.items(ItemQuery(tag = tag), null, 50).items.isNotEmpty())
    }

    @Test fun mockMonitorSortsByConfidenceAndPages() = runTest {
        val api = MockMonitorApi(latencyMs = 0)
        val pager = Pager<MonitorHit>({ it.id }) { c -> val p = api.hits(c, 2); p.hits to p.next }
        pager.refresh(); while (pager.loadMore()) Unit
        val conf = pager.items.map { it.confidence }
        assertEquals(conf.sortedDescending(), conf)
        assertEquals(MockMonitorApi.seed().size, pager.items.size)
        api.fetchMore(10)
        assertEquals(MockMonitorApi.seed().size + 2, api.hits(null, 100).hits.size)
    }

    @Test fun mockMonitorPublishNeedsToken() = runTest {
        val api = MockMonitorApi(latencyMs = 0)
        try { api.publish("mock_1", ""); fail("published without a token") } catch (e: ApiException.Status) { assertEquals(401, e.code) }
        assertTrue(api.publish("mock_1", "t").isPublished)
        assertTrue(api.published(null, 10).hits.any { it.id == "mock_1" })
        assertFalse(api.publish("mock_1", "t", publish = false).isPublished)
        assertTrue(api.hits(null, 50, kind = "language").hits.all { it.kind == "language" })
        assertEquals(listOf("тарас", "тарас маслов", "маслов"), api.phrases().map { it.text })
        assertEquals(listOf("тарас"), api.savePhrases(listOf(" тарас ", "тарас", ""), "t").map { it.text })
    }

    @Test fun storiesFollowTheHighlightOrder() {
        val items = fixture.items.take(3)
        val ids = items.map { it.id }.reversed()
        assertEquals(ids, com.oeaio.earthempire.ui.orderStories(items, ids).map { it.id })
    }
}
