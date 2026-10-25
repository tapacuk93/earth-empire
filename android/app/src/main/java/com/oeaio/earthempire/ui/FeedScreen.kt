package com.oeaio.earthempire.ui

import android.content.Intent
import android.net.Uri
import androidx.activity.compose.BackHandler
import androidx.compose.animation.AnimatedVisibility
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.interaction.MutableInteractionSource
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxHeight
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.statusBarsPadding
import androidx.compose.foundation.pager.HorizontalPager
import androidx.compose.foundation.pager.VerticalPager
import androidx.compose.foundation.pager.rememberPagerState
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.automirrored.filled.OpenInNew
import androidx.compose.material.icons.automirrored.filled.VolumeOff
import androidx.compose.material.icons.automirrored.filled.VolumeUp
import androidx.compose.material.icons.filled.Add
import androidx.compose.material.icons.filled.CheckCircle
import androidx.compose.material.icons.filled.ExpandLess
import androidx.compose.material.icons.filled.ExpandMore
import androidx.compose.material.icons.filled.Share
import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.semantics.CustomAccessibilityAction
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.customActions
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.font.FontStyle
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import com.oeaio.earthempire.data.Dates
import com.oeaio.earthempire.data.DeepLink
import com.oeaio.earthempire.data.Item
import com.oeaio.earthempire.data.MonitorHit
import com.oeaio.earthempire.data.Section
import com.oeaio.earthempire.data.homeSection
import com.oeaio.earthempire.data.suggestion
import kotlinx.coroutines.launch

/** One page of a vertical feed. */
sealed interface FeedItem {
    val key: String
    /** An archive item, from [startMedia] at [startAt] seconds (a key moment) when given. */
    data class Post(val item: Item, val startMedia: Int = 0, val startAt: Double? = null) : FeedItem { override val key get() = "p:" + item.id }
    data class Hit(val hit: MonitorHit) : FeedItem { override val key get() = "h:" + hit.id }
}

/** The items of the place a feed was opened from, and where in them to start. */
data class FeedContext(val title: String, val entries: List<FeedItem>, val start: Int = 0)

/**
 * The TikTok-like viewer: full screen, one item per page, swiped vertically through its context.
 * Videos play by themselves, muted until a tap; the overlay expands into the AI description and
 * analysis; share; back returns to the same spot of the screen it came from.
 */
@Composable
fun FeedScreen(context: FeedContext, owner: Boolean, onPublish: (MonitorHit, Boolean, Section?) -> Unit, onBack: () -> Unit) {
    BackHandler(onBack = onBack)
    val pager = rememberPagerState(initialPage = context.start.coerceIn(0, (context.entries.size - 1).coerceAtLeast(0))) { context.entries.size }
    var muted by rememberSaveable { mutableStateOf(true) }
    Box(Modifier.fillMaxSize().background(Color.Black).testTag("feed")) {
        VerticalPager(pager, Modifier.fillMaxSize(), key = { context.entries[it].key }, beyondViewportPageCount = 1) { page ->
            val current = pager.currentPage == page && !pager.isScrollInProgress
            when (val e = context.entries[page]) {
                is FeedItem.Post -> PostPage(e, current, muted) { muted = !muted }
                is FeedItem.Hit -> HitPage(e.hit, current, muted, owner, onPublish) { muted = !muted }
            }
        }
        Row(Modifier.fillMaxWidth().statusBarsPadding().padding(4.dp), verticalAlignment = Alignment.CenterVertically) {
            IconButton(onClick = onBack, modifier = Modifier.testTag("feed.back")) { Icon(Icons.AutoMirrored.Filled.ArrowBack, "Back", tint = Color.White) }
            Text(context.title + if (context.entries.size > 1) " · ${pager.currentPage + 1}/${context.entries.size}" else "",
                color = Color.White, style = MaterialTheme.typography.titleSmall, maxLines = 1, overflow = TextOverflow.Ellipsis, modifier = Modifier.weight(1f))
            IconButton(onClick = { muted = !muted }, modifier = Modifier.testTag("feed.mute")) {
                Icon(if (muted) Icons.AutoMirrored.Filled.VolumeOff else Icons.AutoMirrored.Filled.VolumeUp, if (muted) "Unmute" else "Mute", tint = Color.White)
            }
            ShareButton(context.entries.getOrNull(pager.currentPage))
        }
    }
}

@Composable
private fun ShareButton(entry: FeedItem?) {
    val ctx = LocalContext.current
    val url = when (entry) {
        is FeedItem.Post -> DeepLink.webUrl(DeepLink.Item(entry.item.id))
        is FeedItem.Hit -> entry.hit.atUrl ?: entry.hit.video.url
        null -> null
    } ?: return
    IconButton(onClick = {
        ctx.startActivity(Intent.createChooser(Intent(Intent.ACTION_SEND).setType("text/plain").putExtra(Intent.EXTRA_TEXT, url), "Share"))
    }, modifier = Modifier.testTag("feed.share")) { Icon(Icons.Filled.Share, "Share", tint = Color.White) }
}

/** Tapping the media toggles the sound, as on TikTok. */
private fun Modifier.tapToMute(muted: Boolean, toggle: () -> Unit) =
    clickable(MutableInteractionSource(), null, onClickLabel = if (muted) "Unmute" else "Mute", onClick = toggle)

@Composable
private fun PostPage(e: FeedItem.Post, current: Boolean, muted: Boolean, toggleMute: () -> Unit) {
    val item = e.item
    val media = item.allMedia
    val mediaPager = rememberPagerState(initialPage = e.startMedia.coerceIn(0, (media.size - 1).coerceAtLeast(0))) { media.size }
    var seek by remember { mutableStateOf<SeekRequest?>(null) }
    val scope = rememberCoroutineScope()
    Box(Modifier.fillMaxSize().testTag("feed.post.${item.id}")) {
        HorizontalPager(mediaPager, Modifier.fillMaxSize().tapToMute(muted, toggleMute)) { i ->
            val m = media[i]
            val label = "${if (m.isVideo) "Video" else "Photo"} ${i + 1} of ${media.size}" + if (i >= item.media.size) ", original by @${item.repostOf?.author}" else ""
            if (m.isVideo) VideoPlayer(
                m.url, m.poster, Modifier.fillMaxSize(), autoPlay = current && mediaPager.currentPage == i, muted = muted, loop = true, controls = false,
                startAt = if (i == e.startMedia) e.startAt else null, seek = seek?.takeIf { it.media == i }, description = label,
            ) else RemoteImage(m.url, label, Modifier.fillMaxSize(), ContentScale.Fit)
        }
        Overlay(
            title = item.summary ?: item.caption ?: item.kind.label,
            meta = listOfNotNull(Dates.parse(item.takenAt)?.let(Dates::long), item.location?.name, if (media.size > 1) "${mediaPager.currentPage + 1}/${media.size}" else null).joinToString(" · "),
            credit = item.repostOf?.let { "Original by @${it.author}" + (it.authorName?.let { n -> " · $n" } ?: "") },
        ) {
            item.description?.let { Text(it, color = Color.White, style = MaterialTheme.typography.bodyMedium) }
            item.caption?.let { LabeledWhite("Caption", it) }
            item.repostOf?.sourceUrl?.let { OpenLinkWhite("Open the original", it) }
            item.analysis?.let { a ->
                MaterialTheme(colorScheme = MaterialTheme.colorScheme.copy(onSurface = Color.White, onSurfaceVariant = Color.White.copy(alpha = 0.75f),
                    primary = Color(0xFF8FE3CB), primaryContainer = Color.White.copy(alpha = 0.2f), onPrimaryContainer = Color.White, onBackground = Color.White)) {
                    androidx.compose.material3.ProvideTextStyle(MaterialTheme.typography.bodyMedium.copy(color = Color.White)) {
                        AnalysisSection(a, media) { m, t -> scope.launch { mediaPager.animateScrollToPage(m) }; seek = SeekRequest(m, t) }
                    }
                }
            }
            item.sourceUrl?.let { OpenLinkWhite("View on Instagram", it) }
        }
    }
}

@Composable
private fun HitPage(hit: MonitorHit, current: Boolean, muted: Boolean, owner: Boolean, onPublish: (MonitorHit, Boolean, Section?) -> Unit, toggleMute: () -> Unit) {
    val ctx = LocalContext.current
    Box(Modifier.fillMaxSize().testTag("feed.hit.${hit.id}")) {
        val play = hit.playable
        Box(Modifier.fillMaxSize().tapToMute(muted, toggleMute)) {
            if (play != null) VideoPlayer(play.first, hit.poster, Modifier.fillMaxSize(), autoPlay = current, muted = muted, loop = true, controls = false,
                startAt = play.second, description = "Recording from ${hit.sourceTitle}")
            else RemoteImage(hit.poster, "Frame from ${hit.sourceTitle}", Modifier.fillMaxSize(), ContentScale.Fit)
        }
        ConfidenceBadge(hit, Modifier.align(Alignment.TopEnd).statusBarsPadding().padding(top = 56.dp, end = 12.dp))
        Overlay(
            title = "“${hit.excerpt.text}”",
            meta = listOfNotNull(hit.sourceTitle, hit.platform, Dates.parse(hit.video.postedAt)?.let(Dates::medium), "at ${Dates.clock(hit.start)}").joinToString(" · "),
            credit = hit.excerpt.en,
            actions = {
                if (owner) PublishButton(hit, onPublish, light = true)
                (hit.atUrl ?: hit.video.url)?.let { url ->
                    IconButton(onClick = { runCatching { ctx.startActivity(Intent(Intent.ACTION_VIEW, Uri.parse(url))) } }) {
                        Icon(Icons.AutoMirrored.Filled.OpenInNew, "Open at the moment", tint = Color.White)
                    }
                }
            },
        ) {
            Text(hit.reasonLabel, color = Color.White, fontWeight = FontWeight.SemiBold)
            hit.suggestion?.let { s -> Text("Suggested for ${s.section.title}" + (s.reason?.let { ": $it" } ?: ""), color = Color.White, style = MaterialTheme.typography.bodySmall) }
            hit.notes.forEach { Text("• $it", color = Color.White.copy(alpha = 0.85f), style = MaterialTheme.typography.bodySmall) }
            hit.judge?.reason?.let { LabeledWhite("Judge", it) }
            hit.video.title?.let { LabeledWhite("Video", it) }
        }
    }
}

/**
 * The bottom overlay: title and meta always, the rest when expanded (scrollable, at most two
 * thirds of the screen). Expanding pauses nothing; the media keeps playing behind.
 */
@Composable
private fun androidx.compose.foundation.layout.BoxScope.Overlay(
    title: String, meta: String, credit: String?, actions: @Composable () -> Unit = {}, more: @Composable () -> Unit,
) {
    var open by rememberSaveable { mutableStateOf(false) }
    Column(
        Modifier.align(Alignment.BottomStart).fillMaxWidth()
            .background(Brush.verticalGradient(listOf(Color.Transparent, Color.Black.copy(alpha = if (open) 0.85f else 0.7f))))
            .navigationBarsPadding().padding(16.dp).testTag("feed.overlay"),
        verticalArrangement = Arrangement.spacedBy(6.dp),
    ) {
        Row(verticalAlignment = Alignment.Top) {
            Column(Modifier.weight(1f).clickable(onClickLabel = if (open) "Show less" else "Show the description and analysis") { open = !open }
                .semantics { customActions = listOf(CustomAccessibilityAction(if (open) "Show less" else "Show more") { open = !open; true }) }) {
                Text(title, color = Color.White, style = MaterialTheme.typography.titleMedium, fontStyle = if (title.startsWith("“")) FontStyle.Italic else FontStyle.Normal,
                    maxLines = if (open) 6 else 2, overflow = TextOverflow.Ellipsis)
                credit?.let { Text(it, color = Color.White.copy(alpha = 0.9f), style = MaterialTheme.typography.bodyMedium, maxLines = if (open) 6 else 2) }
                Text(meta, color = Color.White.copy(alpha = 0.75f), style = MaterialTheme.typography.labelMedium)
            }
            actions()
            IconButton(onClick = { open = !open }, modifier = Modifier.testTag("feed.more")) {
                Icon(if (open) Icons.Filled.ExpandMore else Icons.Filled.ExpandLess, if (open) "Show less" else "Show the description and analysis", tint = Color.White)
            }
        }
        AnimatedVisibility(open) {
            Column(Modifier.fillMaxWidth().heightIn(max = 460.dp).verticalScroll(rememberScrollState()).testTag("feed.details"), verticalArrangement = Arrangement.spacedBy(10.dp)) { more() }
        }
    }
}

@Composable
private fun LabeledWhite(label: String, text: String) {
    Column {
        Text(label, color = Color.White.copy(alpha = 0.7f), style = MaterialTheme.typography.labelMedium)
        Text(text, color = Color.White, style = MaterialTheme.typography.bodyMedium)
    }
}

@Composable
private fun OpenLinkWhite(label: String, url: String) {
    val ctx = LocalContext.current
    TextButton(onClick = { runCatching { ctx.startActivity(Intent(Intent.ACTION_VIEW, Uri.parse(url))) } }) {
        Icon(Icons.AutoMirrored.Filled.OpenInNew, null, Modifier.size(18.dp), tint = Color.White); Text("  $label", color = Color.White)
    }
}

/**
 * "+": publishes a hit to Home in a section the owner picks, the monitor's suggestion first; on a
 * published hit it takes it back.
 */
@Composable
fun PublishButton(hit: MonitorHit, onPublish: (MonitorHit, Boolean, Section?) -> Unit, light: Boolean = false, busy: Boolean = false) {
    var open by remember { mutableStateOf(false) }
    val tint = if (light) Color.White else MaterialTheme.colorScheme.primary
    Box {
        if (hit.isPublished) {
            IconButton(onClick = { open = true }, enabled = !busy, modifier = Modifier.testTag("hit.published")) {
                Icon(Icons.Filled.CheckCircle, "Published in ${hit.homeSection.title}. Change", tint = tint)
            }
        } else {
            Surface(shape = RoundedCornerShape(50), color = if (light) Color.White.copy(alpha = 0.2f) else MaterialTheme.colorScheme.primary,
                modifier = Modifier.size(44.dp).clickable(enabled = !busy, onClickLabel = "Publish to Home") { open = true }.testTag("hit.add")
                    .semantics { contentDescription = "Publish to Home" + (hit.suggestion?.let { ", suggested ${it.section.title}" } ?: "") }) {
                Box(contentAlignment = Alignment.Center) { Icon(Icons.Filled.Add, null, tint = if (light) Color.White else MaterialTheme.colorScheme.onPrimary) }
            }
        }
        DropdownMenu(open, onDismissRequest = { open = false }) {
            val suggested = hit.suggestion?.section ?: Section.Common
            (listOf(suggested) + Section.entries.filter { it != suggested }).forEach { s ->
                DropdownMenuItem(
                    text = { Text((if (hit.isPublished && hit.homeSection == s) "✓ " else "") + "Publish in ${s.title}" + if (s == suggested && hit.suggestion != null) " (suggested)" else "") },
                    onClick = { open = false; onPublish(hit, true, s) }, modifier = Modifier.testTag("publish.${s.wire}"),
                )
            }
            if (hit.isPublished) DropdownMenuItem(text = { Text("Remove from Home") }, onClick = { open = false; onPublish(hit, false, null) }, modifier = Modifier.testTag("publish.remove"))
        }
    }
}

