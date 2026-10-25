package com.oeaio.earthempire

import android.content.Context
import androidx.test.core.app.ApplicationProvider
import com.oeaio.earthempire.data.MockMonitorApi
import com.oeaio.earthempire.data.SampleApi
import okhttp3.OkHttpClient
import java.io.File

object TestSupport {
    /** The fixture the app bundles (the iOS app's), read from the source tree. */
    val fixtureJson: String by lazy { File("src/main/assets/fixture/fixture.json").readText() }

    /** An app over the fixture and the mock monitor, answering at once. */
    fun container(adminToken: String = "", theme: String = "light"): AppContainer {
        val ctx = ApplicationProvider.getApplicationContext<Context>()
        val prefs = ctx.getSharedPreferences("test-settings", Context.MODE_PRIVATE).also { it.edit().clear().commit() }
        val settings = Settings(prefs).apply { this.adminToken = adminToken; this.theme = theme; useSample = true }
        com.oeaio.earthempire.data.MediaUrls.sampleKeys = sampleKeys()
        return AppContainer(settings, OkHttpClient(), { SampleApi.decode(fixtureJson) }, { MockMonitorApi(latencyMs = 0) }, null, { fixtureJson })
    }

    fun sampleKeys(): Set<String> {
        val root = File("src/main/assets/fixture/media")
        return root.walkTopDown().filter { it.isFile }.map { it.relativeTo(root).path }.toSet()
    }
}
