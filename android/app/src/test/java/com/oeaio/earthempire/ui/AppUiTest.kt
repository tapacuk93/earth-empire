package com.oeaio.earthempire.ui

import androidx.compose.ui.test.assertIsDisplayed
import androidx.compose.ui.test.assertIsSelected
import androidx.compose.ui.test.hasAnyAncestor
import androidx.compose.ui.test.hasTestTag
import androidx.compose.ui.test.hasText
import androidx.compose.ui.test.junit4.createComposeRule
import androidx.compose.ui.test.onAllNodesWithTag
import androidx.compose.ui.test.onAllNodesWithText
import androidx.compose.ui.test.onFirst
import androidx.compose.ui.test.onNodeWithContentDescription
import androidx.compose.ui.test.onNodeWithTag
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.performClick
import androidx.compose.ui.test.performScrollToNode
import androidx.test.ext.junit.runners.AndroidJUnit4
import com.oeaio.earthempire.TestSupport
import com.oeaio.earthempire.data.DeepLink
import kotlinx.coroutines.channels.Channel
import kotlinx.coroutines.flow.receiveAsFlow
import org.junit.Assert.assertEquals
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.annotation.Config

/** The app over the fixture and the mock monitor, driven through its semantics. */
@RunWith(AndroidJUnit4::class)
@Config(sdk = [35], qualifiers = "w411dp-h891dp-xxhdpi")
class AppUiTest {
    @get:Rule val rule = createComposeRule()

    private fun launch(token: String = "", links: Channel<DeepLink>? = null) {
        val c = TestSupport.container(adminToken = token)
        rule.setContent { EarthEmpireApp(c, links?.receiveAsFlow() ?: kotlinx.coroutines.flow.emptyFlow()) }
        rule.waitForIdle()
    }

    @Test fun opensOnMonitorWithHitsByConfidence() {
        launch()
        rule.onNodeWithTag("tab.monitor").assertIsSelected()
        rule.onNodeWithTag("banner.sample").assertIsDisplayed()
        rule.onNodeWithTag("hit.mock_1").assertIsDisplayed()
        rule.onNodeWithText("Thank you, Taras, for the question.").assertIsDisplayed()
        rule.onNode(hasTestTag("hit.confidence") and hasAnyAncestor(hasTestTag("hit.mock_1")), useUnmergedTree = true).assertExists()
        // The lowest-confidence hit is labelled.
        rule.onNodeWithTag("monitor.list").performScrollToNode(hasTestTag("hit.mock_5"))
        rule.onNode(hasTestTag("hit.low") and hasAnyAncestor(hasTestTag("hit.mock_5")), useUnmergedTree = true).assertExists()

    }

    @Test fun addWithoutTokenAsksForIt() {
        launch()
        rule.onAllNodesWithTag("hit.add", useUnmergedTree = true).onFirst().performClick()
        rule.waitForIdle()
        rule.onNodeWithText("Adding needs the owner's admin token", substring = true).assertIsDisplayed()
    }

    @Test fun addWithTokenPublishesToHome() {
        launch(token = "owner")
        rule.onAllNodesWithTag("hit.add", useUnmergedTree = true).onFirst().performClick()
        rule.waitUntil(3000) { rule.onAllNodesWithText("Added to Home and the site.").fetchSemanticsNodes().isNotEmpty() }
        rule.onNodeWithTag("tab.home").performClick()
        rule.waitForIdle()
        rule.onNodeWithTag("home.refresh").assertExists()
    }

    @Test fun homeShowsProfileCloudAndTimeline() {
        launch()
        rule.onNodeWithTag("tab.home").performClick()
        rule.waitForIdle()
        rule.onNodeWithTag("profile.header").assertIsDisplayed()
        rule.onNodeWithTag("highlights.row").assertIsDisplayed()
        rule.onNodeWithTag("tag.cloud").assertExists()
        rule.onNodeWithText("Chronological").performClick()
        rule.waitForIdle()
        rule.onNodeWithTag("tag.cloud").assertDoesNotExist()
        rule.onNodeWithTag("home.grid").performScrollToNode(hasTestTag("timeline.ig_3400000000000000012"))
    }

    @Test fun kindFilterNarrowsTheGrid() {
        launch()
        rule.onNodeWithTag("tab.home").performClick()
        rule.waitForIdle()
        rule.onNodeWithTag("home.grid").performScrollToNode(hasTestTag("filters"))
        rule.onNodeWithTag("filter.kind.reel").performClick()
        rule.waitForIdle()
        rule.onNodeWithTag("home.grid").performScrollToNode(hasTestTag("tile.ig_3400000000000000012"))
        rule.onNodeWithTag("tile.ig_3300000000000000000").assertDoesNotExist()
    }

    @Test fun itemLinkShowsAnalysisAndRepostCredit() {
        val links = Channel<DeepLink>(Channel.BUFFERED)
        launch(links = links)
        val repost = TestSupport.fixtureJson.let { com.oeaio.earthempire.data.SampleApi.decode(it).fixture.items.first { i -> i.repostOf != null } }
        links.trySend(DeepLink.parse("https://empire.earth/item/${repost.id}")!!)
        rule.waitForIdle()
        rule.onNodeWithTag("item.detail").performScrollToNode(hasTestTag("repost.card"))
        rule.onNodeWithContentDescription("Repost. Original by @${repost.repostOf!!.author}").assertIsDisplayed()
        rule.onNodeWithTag("item.detail").performScrollToNode(hasTestTag("analysis"))
        rule.onNodeWithText("About this").assertExists()
    }

    @Test fun statusShowsComponentsAndReadOnlyPhrases() {
        launch()
        rule.onNodeWithTag("tab.status").performClick()
        rule.waitUntil(3000) { rule.onAllNodesWithTag("status.overall").fetchSemanticsNodes().isNotEmpty() }
        rule.onNodeWithTag("component.monitor").assertExists()
        rule.onNodeWithTag("status.list").performScrollToNode(hasTestTag("phrases"))
        rule.onNodeWithText("тарас маслов").assertIsDisplayed()
        rule.onNodeWithContentDescription("Read-only: needs the admin token").assertExists()
        rule.onNodeWithTag("phrases.save").assertDoesNotExist()
    }

    @Test fun ownerEditsPhrases() {
        launch(token = "owner")
        rule.onNodeWithTag("tab.status").performClick()
        rule.waitForIdle()
        rule.onNodeWithTag("status.list").performScrollToNode(hasTestTag("phrases.rescan"))
        rule.onNodeWithTag("phrases.rescan").assertIsDisplayed()
        rule.onNodeWithContentDescription("Remove маслов").performClick()
        rule.onNodeWithTag("phrases.save").performClick()
        rule.waitUntil(3000) { rule.onAllNodesWithText("Phrases saved.").fetchSemanticsNodes().isNotEmpty() }
        assertEquals(0, rule.onAllNodes(hasText("Remove маслов")).fetchSemanticsNodes().size)
    }

    @Test fun highlightLinkOpensTheStoryViewer() {
        val links = Channel<DeepLink>(Channel.BUFFERED)
        launch(links = links)
        links.trySend(DeepLink.Highlight("hl_17900000000000001"))
        rule.waitForIdle()
        rule.onNodeWithTag("story.viewer").assertExists()
        rule.onNodeWithTag("story.close").performClick()
        rule.waitForIdle()
        rule.onNodeWithTag("story.viewer").assertDoesNotExist()
    }
}
