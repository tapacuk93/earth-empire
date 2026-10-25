package com.oeaio.earthempire.data

import androidx.test.ext.junit.runners.AndroidJUnit4
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test
import org.junit.runner.RunWith

/** The site's routes (web/src/main.tsx) and the iOS app's aliases. */
@RunWith(AndroidJUnit4::class)
class DeepLinkTest {
    private fun p(s: String) = DeepLink.parse(s)

    @Test fun siteRoutes() {
        assertEquals(DeepLink.Home(), p("https://empire.earth/"))
        assertEquals(DeepLink.Home(), p("https://empire.earth"))
        assertEquals(DeepLink.Item("ig_123"), p("https://empire.earth/item/ig_123"))
        assertEquals(DeepLink.Category("travel"), p("https://www.empire.earth/category/travel"))
        assertEquals(DeepLink.Category("travel", ItemKind.Reel), p("https://empire.earth/category/travel?kind=reel"))
        assertEquals(DeepLink.Highlight("hl_1", "ig_5"), p("https://empire.earth/highlight/hl_1?item=ig_5"))
        assertEquals(DeepLink.Highlight("hl_1", "ig_5"), p("https://empire.earth/highlight/hl_1/5"))
    }

    @Test fun homeFilters() {
        assertEquals(DeepLink.Home(ItemQuery(kind = ItemKind.Reel, category = "food", tag = "beach", q = "sea"), "tags"),
            p("https://empire.earth/?kind=reel&category=food&tag=beach&q=sea&view=tags"))
        assertEquals(DeepLink.Home(ItemQuery(), "timeline"), p("https://empire.earth/?view=timeline"))
        assertEquals(DeepLink.Home(ItemQuery(q = "lava")), p("https://empire.earth/search?q=lava"))
    }

    @Test fun aliasesSchemeAndHashRoutes() {
        assertEquals(DeepLink.Item("ig_42"), p("https://empire.earth/p/42"))
        assertEquals(DeepLink.Item("ig_42"), p("https://empire.earth/reel/42"))
        assertEquals(DeepLink.Item("ig_7"), p("earthempire://item/ig_7"))
        assertEquals(DeepLink.Item("ig_7"), p("https://empire.earth/#/item/ig_7"))
        assertEquals(DeepLink.Categories, p("earthempire://categories"))
        assertEquals(DeepLink.Monitor, p("https://empire.earth/monitor"))
        assertEquals(DeepLink.MonitorHit("h1"), p("earthempire://monitor/h1"))
    }

    @Test fun foreignOrUnknownLinksAreIgnored() {
        assertNull(p("https://example.com/item/ig_1"))
        assertNull(p("https://empire.earth/nope/x"))
        assertNull(p("mailto:someone@empire.earth"))
        assertNull(p("https://empire.earth/item"))
    }

    @Test fun webUrlsRoundTrip() {
        for (link in listOf(DeepLink.Item("ig_1"), DeepLink.Category("food"), DeepLink.Highlight("hl_1", "ig_2"), DeepLink.Home(ItemQuery(q = "a b")))) {
            assertEquals(link, p(DeepLink.webUrl(link)))
        }
    }
}
