package com.oeaio.earthempire.ui

import android.graphics.Bitmap
import android.os.Looper
import androidx.compose.ui.test.junit4.createAndroidComposeRule
import androidx.compose.ui.test.onRoot
import androidx.compose.ui.test.performScrollToNode
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

    private fun app(theme: String = "light", token: String = "", tab: Tab = Tab.Monitor, link: DeepLink? = null): AppContainer {
        val c = TestSupport.container(adminToken = token, theme = theme)
        val links = Channel<DeepLink>(Channel.BUFFERED)
        link?.let { links.trySend(it) }
        rule.setContent { EarthEmpireApp(c, links.receiveAsFlow(), startTab = tab) }
        return c
    }

    @Test fun monitorLight() { app(); shot("monitor-light") }
    @Test fun monitorDark() { app("dark"); shot("monitor-dark") }
    @Test fun homeLight() { app(tab = Tab.Home); shot("home-light") }
    @Test fun homeDark() { app("dark", tab = Tab.Home); shot("home-dark") }
    @Test fun homeTimeline() { app(tab = Tab.Home, link = DeepLink.Home(view = "timeline")); shot("home-timeline") }
    @Test fun statusLight() { app(tab = Tab.Status); shot("status-light") }
    @Test fun statusSettingsOwner() {
        app(token = "owner", tab = Tab.Status)
        settle()
        rule.onNode(androidx.compose.ui.test.hasTestTag("status.list")).performScrollToNode(androidx.compose.ui.test.hasTestTag("phrases.rescan"))
        shot("status-phrases-owner")
    }
    @Test fun itemDetail() { app(link = DeepLink.Item("ig_3400000000000000012")); shot("item-reel") }
    @Test fun itemRepost() { app("dark", link = DeepLink.Item("ig_3400000000000000005")); shot("item-repost-dark") }
}
