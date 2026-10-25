package com.oeaio.earthempire.data

import com.oeaio.earthempire.TestSupport
import kotlinx.coroutines.test.runTest
import kotlinx.serialization.json.JsonPrimitive
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test
import java.time.YearMonth

/** Home's infographics and its two parts, from the fixture. */
class InsightsTest {
    private val fixture = ContractJson.decodeFromString(Fixture.serializer(), TestSupport.fixtureJson)

    @Test fun monthsCoverEveryMonthInOrder() {
        val months = Insights.months(fixture.items)
        assertEquals(YearMonth.of(2026, 4), months.first().month)
        assertEquals(YearMonth.of(2026, 10), months.last().month)
        assertEquals(7, months.size)
        assertEquals(fixture.items.size, months.sumOf { it.items.size })
    }

    @Test fun placesGroupWithCoordinates() {
        val places = Insights.places(fixture.items)
        val lisbon = places.first { it.name == "Lisbon, Portugal" }
        assertEquals(3, lisbon.count)
        assertEquals(38.7223, lisbon.lat!!, 1e-6)
        assertEquals(places.map { it.count }.sortedDescending(), places.map { it.count })
    }

    @Test fun sectionsFromHighlightsAndPublishedHits() = runTest {
        val surf = fixture.highlights.first { it.title == "Surf" }
        assertEquals(Section.Dedicated, surf.homeSection)
        assertEquals(Section.Common, fixture.highlights.first { it.title == "Food" }.homeSection)
        assertEquals(Section.Dedicated, surf.copy(section = null, dedicated = true).homeSection)
        val published = MockMonitorApi(0).published(null, 10).hits
        val panels = Insights.panels(fixture.items, fixture.highlights, published)
        // Dedicated first, then common; the published hit sits in its section's panel.
        assertEquals(Section.Dedicated, panels.first().section)
        assertTrue(panels.first { it.section == Section.Dedicated && it.highlight == null }.hits.any { it.id == "mock_3" })
        assertEquals(surf.itemIds, panels.first { it.highlight?.id == surf.id }.items.map { it.id }.take(surf.itemIds.size))
        // Every item appears in some panel.
        assertEquals(fixture.items.map { it.id }.toSet(), panels.flatMap { p -> p.items.map { it.id } }.toSet())
    }

    @Test fun panelPeopleAreOnlyNamedOnes() {
        val panel = Insights.Panel(Section.Common, null, fixture.items, emptyList())
        assertTrue(panel.people.none { it.basis == "description only" })
        assertTrue(panel.moments.all { m -> m.item.allMedia[m.media].isVideo })
    }

    @Test fun suggestionAsStringOrObject() {
        val h = MonitorHit("h", suggestedSection = JsonPrimitive("dedicated"))
        assertEquals(Section.Dedicated, h.suggestion?.section)
        assertNull(h.suggestion?.reason)
        val obj = MockMonitorApi.seed().first()
        assertEquals(Section.Dedicated, obj.suggestion?.section)
        assertTrue(obj.suggestion?.reason!!.isNotEmpty())
        assertEquals(Section.Common, MonitorHit("x").homeSection)
    }
}
