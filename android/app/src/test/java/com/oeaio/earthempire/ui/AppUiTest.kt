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
import androidx.compose.ui.test.performTextInput
import androidx.test.ext.junit.runners.AndroidJUnit4
import com.oeaio.earthempire.AppContainer
import com.oeaio.earthempire.TestSupport
import com.oeaio.earthempire.data.DeepLink
import kotlinx.coroutines.channels.Channel
import kotlinx.coroutines.flow.receiveAsFlow
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.annotation.Config

/** The app over the fixture and the mock monitor, driven through its semantics. */
@RunWith(AndroidJUnit4::class)
@Config(sdk = [35], qualifiers = "w411dp-h891dp-xxhdpi")
class AppUiTest {
    @get:Rule val rule = createComposeRule()

    private fun launch(token: String = "", links: Channel<DeepLink>? = null, tab: Tab = Tab.Home): AppContainer {
        val c = TestSupport.container(adminToken = token)
        rule.setContent { EarthEmpireApp(c, links?.receiveAsFlow() ?: kotlinx.coroutines.flow.emptyFlow(), startTab = tab) }
        rule.waitForIdle()
        return c
    }

    @Test fun withoutTokenOnlyHomeAndADiscreetWayIn() {
        val c = launch()
        rule.onNodeWithTag("profile.header").assertIsDisplayed()
        rule.onNodeWithTag("tabs").assertDoesNotExist()
        rule.onNodeWithTag("owner.signin").performClick()
        rule.onNodeWithTag("owner.token").performTextInput("owner")
        rule.onNodeWithTag("owner.submit").performClick()
        rule.waitUntil(3000) { rule.onAllNodesWithTag("tabs").fetchSemanticsNodes().isNotEmpty() }
        assertTrue(c.owner.value)
        assertEquals("owner", c.settings.adminToken)
        rule.onNodeWithTag("tab.monitor").assertIsDisplayed()
        rule.onNodeWithTag("tab.status").assertIsDisplayed()
        rule.onNodeWithTag("tab.settings").assertIsDisplayed()
        rule.onNodeWithTag("owner.signin").assertDoesNotExist()
    }

    @Test fun ownerSeesDetectedByConfidence() {
        launch(token = "owner")
        rule.onNodeWithTag("tab.monitor").performClick()
        rule.waitForIdle()
        rule.onNodeWithTag("tab.monitor").assertIsSelected()
        rule.onNodeWithText("Thank you, Taras, for the question.").assertIsDisplayed()
        rule.onNode(hasTestTag("hit.confidence") and hasAnyAncestor(hasTestTag("hit.mock_1")), useUnmergedTree = true).assertExists()
        // The lowest-confidence hit is labelled.
        rule.onNodeWithTag("monitor.list").performScrollToNode(hasTestTag("hit.mock_5"))
        rule.onNode(hasTestTag("hit.low") and hasAnyAncestor(hasTestTag("hit.mock_5")), useUnmergedTree = true).assertExists()
    }

    @Test fun plusPublishesToHome() {
        launch(token = "owner")
        rule.onNodeWithTag("tab.monitor").performClick()
        rule.waitForIdle()
        rule.onAllNodesWithTag("hit.add", useUnmergedTree = true).onFirst().performClick()
        rule.waitUntil(3000) { rule.onAllNodesWithText("Published to Home and the site.").fetchSemanticsNodes().isNotEmpty() }
        rule.onNode(hasTestTag("hit.published") and hasAnyAncestor(hasTestTag("hit.mock_1")), useUnmergedTree = true).assertExists()
        rule.onNodeWithTag("tab.home").performClick()
        rule.onNodeWithTag("home.refresh").assertExists()
    }

    @Test fun kindFilterOnDetected() {
        launch(token = "owner", tab = Tab.Monitor)
        rule.onNodeWithTag("kind.language").performClick()
        rule.waitForIdle()
        rule.onNodeWithTag("hit.mock_1").assertDoesNotExist()
        rule.onNodeWithTag("hit.mock_2").assertExists()
    }

    @Test fun homeShowsProfileCloudPublishedAndTimeline() {
        launch()
        rule.onNodeWithTag("profile.header").assertIsDisplayed()
        rule.onNodeWithTag("highlights.row").assertIsDisplayed()
        rule.onNodeWithTag("published.row").assertExists()
        rule.onNodeWithTag("home.grid").performScrollToNode(hasTestTag("tag.cloud"))
        rule.onNodeWithText("Chronological").performClick()
        rule.waitForIdle()
        rule.onNodeWithTag("tag.cloud").assertDoesNotExist()
        rule.onNodeWithTag("home.grid").performScrollToNode(hasTestTag("timeline.ig_3400000000000000012"))
    }

    @Test fun kindFilterNarrowsTheGrid() {
        launch()
        rule.onNodeWithTag("home.grid").performScrollToNode(hasTestTag("filters"))
        rule.onNodeWithTag("filter.kind.reel").performClick()
        rule.waitForIdle()
        rule.onNodeWithTag("home.grid").performScrollToNode(hasTestTag("tile.ig_3400000000000000012"))
        rule.onNodeWithTag("tile.ig_3300000000000000000").assertDoesNotExist()
    }

    @Test fun itemLinkShowsAnalysisAndRepostCredit() {
        val links = Channel<DeepLink>(Channel.BUFFERED)
        launch(links = links)
        links.trySend(DeepLink.parse("https://empire.earth/item/ig_3400000000000000005")!!)
        rule.waitForIdle()
        rule.onNodeWithTag("item.detail").performScrollToNode(hasTestTag("repost.card"))
        rule.onNodeWithContentDescription("Repost. Original by @", substring = true).assertIsDisplayed()
        rule.onNodeWithTag("item.detail").performScrollToNode(hasTestTag("analysis"))
        rule.onNodeWithText("About this").assertExists()
    }

    @Test fun monitorLinkWithoutTokenAsksForIt() {
        val links = Channel<DeepLink>(Channel.BUFFERED)
        launch(links = links)
        links.trySend(DeepLink.Monitor)
        rule.waitForIdle()
        rule.onNodeWithTag("owner.token").assertExists()
    }

    @Test fun statusShowsComponents() {
        launch(token = "owner", tab = Tab.Status)
        rule.waitUntil(3000) { rule.onAllNodesWithTag("status.overall").fetchSemanticsNodes().isNotEmpty() }
        rule.onNodeWithTag("component.monitor").assertExists()
    }

    @Test fun settingsEditsPhrasesWithVariants() {
        launch(token = "owner", tab = Tab.Settings)
        rule.waitUntil(3000) { rule.onAllNodesWithTag("phrase.0").fetchSemanticsNodes().isNotEmpty() }
        rule.onAllNodesWithTag("phrase.variants", useUnmergedTree = true).onFirst().assertExists()
        rule.onNodeWithContentDescription("Remove маслов").performClick()
        rule.onNodeWithTag("phrases.save").performClick()
        rule.waitUntil(3000) { rule.onAllNodesWithText("Phrases saved", substring = true).fetchSemanticsNodes().isNotEmpty() }
        assertEquals(0, rule.onAllNodes(hasText("Remove маслов")).fetchSemanticsNodes().size)
        rule.onNodeWithTag("phrases.rescan").assertIsDisplayed()
    }

    @Test fun signingOutLeavesOnlyHome() {
        val c = launch(token = "owner", tab = Tab.Settings)
        rule.onNodeWithTag("settings").performScrollToNode(hasTestTag("settings.signout"))
        rule.onNodeWithTag("settings.signout").performClick()
        rule.waitForIdle()
        assertEquals("", c.settings.adminToken)
        rule.onNodeWithTag("tabs").assertDoesNotExist()
        rule.onNodeWithTag("owner.signin").assertExists()
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
