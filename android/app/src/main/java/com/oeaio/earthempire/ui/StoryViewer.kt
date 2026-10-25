package com.oeaio.earthempire.ui

import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.interaction.MutableInteractionSource
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxHeight
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.statusBarsPadding
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Close
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableFloatStateOf
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.semantics.CustomAccessibilityAction
import androidx.compose.ui.semantics.customActions
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.unit.dp
import androidx.compose.ui.window.Dialog
import androidx.compose.ui.window.DialogProperties
import com.oeaio.earthempire.data.ArchiveApi
import com.oeaio.earthempire.data.Dates
import com.oeaio.earthempire.data.Item
import com.oeaio.earthempire.data.ItemQuery
import kotlinx.coroutines.delay

/** Orders a highlight's stories by its `item_ids`; stories it does not list go last, oldest first. */
fun orderStories(items: List<Item>, ids: List<String>): List<Item> {
    val pos = ids.withIndex().associate { it.value to it.index }
    return items.sortedWith(compareBy<Item> { pos[it.id] ?: Int.MAX_VALUE }.thenBy { it.takenAt })
}

/**
 * A highlight's stories, full screen: tap the right side for the next, the left for the previous,
 * hold to pause; images last five seconds and videos their length. Swiping past the last moves to
 * the next highlight.
 */
@Composable
fun StoryViewer(highlightId: String, startItem: String?, api: ArchiveApi, onClose: () -> Unit) {
    val nav = LocalNav.current
    var hlId by remember { mutableStateOf(highlightId) }
    var highlights by remember { mutableStateOf(emptyList<com.oeaio.earthempire.data.Highlight>()) }
    var stories by remember { mutableStateOf<List<Item>?>(null) }
    var index by remember { mutableIntStateOf(0) }
    var progress by remember { mutableFloatStateOf(0f) }
    var paused by remember { mutableStateOf(false) }
    var error by remember { mutableStateOf<Throwable?>(null) }

    LaunchedEffect(hlId) {
        stories = null
        try {
            if (highlights.isEmpty()) highlights = api.highlights()
            val h = highlights.firstOrNull { it.id == hlId }
            val all = mutableListOf<Item>()
            var cursor: String? = null
            do { val p = api.items(ItemQuery(highlight = hlId), cursor, 100); all += p.items; cursor = p.next } while (cursor != null && all.size < 500)
            val ordered = orderStories(all, h?.itemIds ?: emptyList())
            stories = ordered
            index = if (hlId == highlightId) ordered.indexOfFirst { it.id == startItem }.coerceAtLeast(0) else 0
        } catch (e: Exception) { error = e }
    }

    fun nextHighlight(step: Int): Boolean {
        val i = highlights.indexOfFirst { it.id == hlId } + step
        if (i !in highlights.indices) return false
        hlId = highlights[i].id; return true
    }
    fun next() { val s = stories ?: return; if (index < s.size - 1) { index++; progress = 0f } else if (!nextHighlight(1)) onClose() }
    fun previous() { if (index > 0) { index--; progress = 0f } else if (!nextHighlight(-1)) progress = 0f }

    val current = stories?.getOrNull(index)
    val media = current?.let { it.media.firstOrNull() ?: it.repostOf?.media?.firstOrNull() }
    val duration = ((if (media?.isVideo == true) media.duration else null) ?: 5.0) * 1000

    LaunchedEffect(current?.id, paused) {
        if (current == null) return@LaunchedEffect
        while (!paused && progress < 1f) { delay(50); progress += (50 / duration).toFloat() }
        if (progress >= 1f) next()
    }

    Dialog(onDismissRequest = onClose, properties = DialogProperties(usePlatformDefaultWidth = false, decorFitsSystemWindows = false)) {
        Box(Modifier.fillMaxSize().background(Color.Black).testTag("story.viewer")) {
            when {
                current != null && media != null -> {
                    if (media.isVideo) VideoPlayer(media.url, media.poster, Modifier.fillMaxSize(), autoPlay = !paused, description = current.accessibilityLabel)
                    else RemoteImage(media.url, current.accessibilityLabel, Modifier.fillMaxSize(), ContentScale.Fit)
                }
                error != null -> Text(error?.message ?: "", color = Color.White, modifier = Modifier.align(Alignment.Center).padding(24.dp))
                stories?.isEmpty() == true -> Text("No stories in this highlight.", color = Color.White, modifier = Modifier.align(Alignment.Center))
                else -> CircularProgressIndicator(Modifier.align(Alignment.Center))
            }
            // Tap zones: a third for back, the rest for forward.
            Row(Modifier.fillMaxSize().semantics {
                customActions = listOf(
                    CustomAccessibilityAction("Next story") { next(); true },
                    CustomAccessibilityAction("Previous story") { previous(); true },
                    CustomAccessibilityAction(if (paused) "Resume" else "Pause") { paused = !paused; true },
                )
            }) {
                val none = remember { MutableInteractionSource() }
                Box(Modifier.weight(1f).fillMaxHeight().clickable(none, null, onClickLabel = "Previous story") { previous() }.testTag("story.prev"))
                Box(Modifier.weight(2f).fillMaxHeight().clickable(none, null, onClickLabel = "Next story") { next() }.testTag("story.next"))
            }
            Column(Modifier.fillMaxWidth().statusBarsPadding().padding(8.dp)) {
                Row(horizontalArrangement = Arrangement.spacedBy(3.dp)) {
                    stories?.forEachIndexed { i, _ ->
                        LinearProgressIndicator(
                            progress = { if (i < index) 1f else if (i == index) progress.coerceIn(0f, 1f) else 0f },
                            color = Color.White, trackColor = Color.White.copy(alpha = 0.35f), modifier = Modifier.weight(1f).height(3.dp),
                        )
                    }
                }
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Column(Modifier.weight(1f).padding(top = 6.dp)) {
                        Text(highlights.firstOrNull { it.id == hlId }?.title ?: "", color = Color.White, style = MaterialTheme.typography.titleSmall)
                        current?.let { c -> Dates.parse(c.takenAt)?.let { Text(Dates.medium(it), color = Color.White.copy(alpha = 0.8f), style = MaterialTheme.typography.labelSmall) } }
                    }
                    IconButton(onClick = { paused = !paused }) { Text(if (paused) "▶" else "❚❚", color = Color.White) }
                    IconButton(onClick = onClose, modifier = Modifier.testTag("story.close")) { Icon(Icons.Filled.Close, "Close stories", tint = Color.White) }
                }
            }
            current?.let { c ->
                Column(Modifier.align(Alignment.BottomStart).fillMaxWidth().background(Color.Black.copy(alpha = 0.45f)).navigationBarsPadding().padding(12.dp)) {
                    c.repostOf?.let { Text("Original by @${it.author}" + (it.authorName?.let { n -> " · $n" } ?: ""), color = Color.White, style = MaterialTheme.typography.labelLarge) }
                    (c.summary ?: c.caption)?.let { Text(it, color = Color.White, style = MaterialTheme.typography.bodySmall, maxLines = 3) }
                    TextButton(onClick = { onClose(); nav.item(c.id) }) { Text("Details", color = Color.White) }
                }
            }
        }
    }
}
