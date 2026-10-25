package com.oeaio.earthempire

import android.content.Intent
import android.os.Bundle
import android.util.Log
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import com.oeaio.earthempire.data.DeepLink
import com.oeaio.earthempire.data.TAG
import com.oeaio.earthempire.ui.EarthEmpireApp
import com.oeaio.earthempire.ui.VideoCache
import androidx.lifecycle.lifecycleScope
import kotlinx.coroutines.channels.Channel
import kotlinx.coroutines.launch
import kotlinx.coroutines.flow.receiveAsFlow

class MainActivity : ComponentActivity() {
    private val links = Channel<DeepLink>(Channel.BUFFERED)

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        enableEdgeToEdge()
        val container = (application as EarthEmpireApplication).container
        VideoCache.client = container.client
        if (savedInstanceState == null) handle(intent)
        setContent { EarthEmpireApp(container, links.receiveAsFlow()) }
        lifecycleScope.launch { container.recheckToken() }
    }

    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent)
        handle(intent)
    }

    /** An App Link (https://empire.earth/…) or an earthempire:// link. */
    private fun handle(intent: Intent?) {
        val uri = intent?.data ?: return
        val link = DeepLink.parse(uri)
        Log.i(TAG, "open $uri -> $link")
        if (link != null) links.trySend(link)
    }
}
