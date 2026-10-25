package com.oeaio.earthempire.ui

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.statusBarsPadding
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.foundation.pager.VerticalPager
import androidx.compose.foundation.pager.rememberPagerState
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Close
import androidx.compose.material3.FilledTonalIconButton
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.window.Dialog
import androidx.compose.ui.window.DialogProperties

/** One video in a tab's fullscreen mode. */
data class FeedEntry(
    val id: String,
    val url: String,
    val poster: String?,
    val title: String,
    val subtitle: String? = null,
    val startAt: Double? = null,
    /** The detail screen behind it, if any ("Details"). */
    val detail: (() -> Unit)? = null,
)

/**
 * A tab's fullscreen video mode: every video of the tab, swiped vertically, the current one
 * playing (from [FeedEntry.startAt], e.g. the moment a monitor hit was heard).
 */
@Composable
fun VideoFeed(entries: List<FeedEntry>, start: Int, onClose: () -> Unit) {
    Dialog(onDismissRequest = onClose, properties = DialogProperties(usePlatformDefaultWidth = false, decorFitsSystemWindows = false)) {
        val pager = rememberPagerState(initialPage = start.coerceIn(0, (entries.size - 1).coerceAtLeast(0))) { entries.size }
        Box(Modifier.fillMaxSize().background(Color.Black).testTag("video.feed")) {
            VerticalPager(pager, Modifier.fillMaxSize(), key = { entries[it].id }) { page ->
                val e = entries[page]
                Box(Modifier.fillMaxSize()) {
                    VideoPlayer(
                        url = e.url, poster = e.poster, modifier = Modifier.fillMaxSize(),
                        autoPlay = pager.currentPage == page, startAt = e.startAt, loop = true,
                        description = "Video: ${e.title}",
                    )
                    Column(
                        Modifier.align(Alignment.BottomStart).fillMaxWidth()
                            .background(Brush.verticalGradient(listOf(Color.Transparent, Color.Black.copy(alpha = 0.7f))))
                            .navigationBarsPadding().padding(16.dp).padding(bottom = 48.dp),
                        verticalArrangement = Arrangement.spacedBy(4.dp),
                    ) {
                        Text(e.title, color = Color.White, style = MaterialTheme.typography.titleMedium, maxLines = 2, overflow = TextOverflow.Ellipsis)
                        e.subtitle?.let { Text(it, color = Color.White.copy(alpha = 0.85f), style = MaterialTheme.typography.bodyMedium, maxLines = 3, overflow = TextOverflow.Ellipsis) }
                        e.detail?.let { open -> TextButton(onClick = { onClose(); open() }) { Text("Details", color = Color.White) } }
                    }
                }
            }
            FilledTonalIconButton(onClick = onClose, modifier = Modifier.align(Alignment.TopEnd).statusBarsPadding().padding(12.dp).testTag("video.feed.close")) {
                Icon(Icons.Filled.Close, contentDescription = "Close fullscreen")
            }
        }
    }
}
