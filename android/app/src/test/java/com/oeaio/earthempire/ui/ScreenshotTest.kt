package com.oeaio.earthempire.ui

import android.graphics.Bitmap
import android.os.Looper
import androidx.compose.ui.test.junit4.createAndroidComposeRule
import androidx.compose.ui.test.onRoot
import androidx.compose.ui.test.performScrollToNode
import androidx.compose.ui.test.performClick
import androidx.test.ext.junit.runners.AndroidJUnit4
import com.oeaio.earthempire.AppContainer
import com.oeaio.earthempire.TestSupport
import com.oeaio.earthempire.data.DeepLink
import kotlinx.coroutines.channels.Channel
import kotlinx.coroutines.flow.receiveAsFlow
import org.junit.Assume.assumeTrue
import org.junit.Before
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.Shadows.shadowOf
import org.robolectric.annotation.Config
import org.robolectric.annotation.GraphicsMode
import java.io.File

/**
 * Renders the main screens with Robolectric's native graphics into app/build/screenshots/.
 * Native graphics exist for macOS and x86_64 Linux only, so on another machine (the arm64 box
 * without its x86_64 JDK) these are skipped.
 */
@RunWith(AndroidJUnit4::class)
@GraphicsMode(GraphicsMode.Mode.NATIVE)
@Config(sdk = [35], qualifiers = "w411dp-h891dp-xxhdpi")
class ScreenshotTest {
    @get:Rule val rule = createAndroidComposeRule<androidx.activity.ComponentActivity>()
    private val out = File("build/screenshots").apply { mkdirs() }

    @Before fun platform() {
        val os = System.getProperty("os.name").lowercase(); val arch = System.getProperty("os.arch")
        assumeTrue("no Robolectric native graphics for $os/$arch", os.contains("mac") || arch == "amd64" || arch == "x86_64")
    }

    private fun settle() {
        // Let images decode on their threads, then let the UI draw them.
        repeat(15) { Thread.sleep(120); shadowOf(Looper.getMainLooper()).idle(); rule.waitForIdle() }
    }

    private fun shot(name: String) {
        settle()
        // Draw the window's views in software (captureToImage waits for a hardware frame that
        // Robolectric never produces).
        val root = rule.activity.window.decorView
        val bmp = Bitmap.createBitmap(root.width, root.height, Bitmap.Config.ARGB_8888)
        root.draw(android.graphics.Canvas(bmp))
        File(out, "$name.png").outputStream().use { bmp.compress(Bitmap.CompressFormat.PNG, 100, it) }
    }

    private fun app(theme: String = "light", token: String = "owner", tab: Tab = Tab.Home, link: DeepLink? = null): AppContainer {
        val c = TestSupport.container(adminToken = token, theme = theme)
        val links = Channel<DeepLink>(Channel.BUFFERED)
        link?.let { links.trySend(it) }
        rule.setContent { EarthEmpireApp(c, links.receiveAsFlow(), startTab = tab) }
        return c
    }

    @Test fun homeVisitor() { app(token = ""); shot("home-visitor") }
    @Test fun homeDark() { app("dark"); shot("home-owner-dark") }
    @Test fun homeSections() {
        app()
        settle()
        rule.onNode(androidx.compose.ui.test.hasTestTag("home.list")).performScrollToNode(androidx.compose.ui.test.hasTestTag("section.dedicated"))
        shot("home-sections")
    }
    @Test fun detectedLight() { app(tab = Tab.Monitor); shot("detected-light") }
    @Test fun detectedDark() { app("dark", tab = Tab.Monitor); shot("detected-dark") }
    @Test fun statusLight() { app(tab = Tab.Status); shot("status-light") }
    @Test fun settingsLight() { app(tab = Tab.Settings); shot("settings-light") }
    @Test fun feedItem() { app(link = DeepLink.Item("ig_3400000000000000010")); shot("feed-item") }
    @Test fun feedItemExpanded() {
        app("dark", link = DeepLink.Item("ig_3400000000000000005"))
        settle()
        rule.onNode(androidx.compose.ui.test.hasTestTag("feed.more")).performClick()
        shot("feed-item-analysis-dark")
    }
    @Test fun feedHit() { app(link = DeepLink.MonitorHit("mock_1")); shot("feed-hit") }
}
