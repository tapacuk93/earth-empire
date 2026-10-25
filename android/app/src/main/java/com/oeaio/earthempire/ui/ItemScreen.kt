package com.oeaio.earthempire.ui

import android.content.Intent
import android.net.Uri
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.aspectRatio
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.pager.HorizontalPager
import androidx.compose.foundation.pager.rememberPagerState
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.automirrored.filled.OpenInNew
import androidx.compose.material.icons.filled.Fullscreen
import androidx.compose.material.icons.filled.Repeat
import androidx.compose.material.icons.filled.Share
import androidx.compose.material3.AssistChip
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedCard
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.TopAppBar
import androidx.compose.material3.pulltorefresh.PullToRefreshBox
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
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.heading
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import com.oeaio.earthempire.data.ArchiveApi
import com.oeaio.earthempire.data.Analysis
import com.oeaio.earthempire.data.Dates
import com.oeaio.earthempire.data.DeepLink
import com.oeaio.earthempire.data.Item
import com.oeaio.earthempire.data.Media
import com.oeaio.earthempire.data.Repost
import kotlinx.coroutines.launch

/** The original of a repost, credited to its author. */
@Composable
fun RepostCard(repost: Repost) {
    OutlinedCard(Modifier.fillMaxWidth().semantics(mergeDescendants = true) { contentDescription = "Repost. Original by @${repost.author}" }.testTag("repost.card")) {
        Column(Modifier.padding(12.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
            Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                Icon(Icons.Filled.Repeat, null, tint = MaterialTheme.colorScheme.primary, modifier = Modifier.size(18.dp))
                Text("Original by @${repost.author}", fontWeight = FontWeight.SemiBold)
                repost.authorName?.let { Text("· $it", color = MaterialTheme.colorScheme.onSurfaceVariant) }
            }
            Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                repost.media.firstOrNull()?.let { RemoteImage(it.poster, null, Modifier.size(72.dp).clip(RoundedCornerShape(8.dp))) }
                Column(Modifier.weight(1f)) {
                    repost.caption?.let { Text(it, style = MaterialTheme.typography.bodyMedium, maxLines = 4) }
                    Dates.parse(repost.takenAt)?.let { Text(Dates.long(it), style = MaterialTheme.typography.labelSmall, color = MaterialTheme.colorScheme.onSurfaceVariant) }
                }
            }
            repost.sourceUrl?.let { OpenLink("Open the original", it) }
        }
    }
}

@Composable
fun OpenLink(label: String, url: String) {
    val context = LocalContext.current
    TextButton(onClick = { runCatching { context.startActivity(Intent(Intent.ACTION_VIEW, Uri.parse(url))) } }) {
        Icon(Icons.AutoMirrored.Filled.OpenInNew, null, Modifier.size(18.dp)); Text("  $label")
    }
}

/**
 * Claude's analysis: what happens, the people with the basis for each name, when and where, the
 * moments of the video (tap to seek), the transcript and the rest.
 */
@Composable
fun AnalysisSection(a: Analysis, media: List<Media>, onSeek: (media: Int, seconds: Double) -> Unit) {
    Column(verticalArrangement = Arrangement.spacedBy(12.dp), modifier = Modifier.testTag("analysis")) {
        SectionTitle("About this")
        a.what?.let { LabeledText("What", it) }
        if (a.people.isNotEmpty()) {
            Text("People", style = MaterialTheme.typography.labelMedium, color = MaterialTheme.colorScheme.onSurfaceVariant)
            a.people.forEach { p ->
                Row(horizontalArrangement = Arrangement.spacedBy(10.dp), modifier = Modifier.semantics(mergeDescendants = true) {}.testTag("person")) {
                    Box(Modifier.size(32.dp).clip(CircleShape).background(MaterialTheme.colorScheme.primaryContainer), contentAlignment = Alignment.Center) {
                        Text((p.who?.trimStart('@')?.firstOrNull() ?: '?').uppercase(), color = MaterialTheme.colorScheme.onPrimaryContainer)
                    }
                    Column(Modifier.weight(1f)) {
                        Text(p.who ?: "Unnamed person", fontWeight = FontWeight.SemiBold)
                        p.role?.let { Text(it, style = MaterialTheme.typography.labelMedium) }
                        p.description?.let { Text(it, style = MaterialTheme.typography.bodySmall) }
                        p.basis?.let { Text(if (p.who != null) "Named from: $it" else "Described from: $it", style = MaterialTheme.typography.labelSmall, color = MaterialTheme.colorScheme.primary) }
                    }
                }
            }
        }
        a.`when`?.let { w ->
            val text = listOfNotNull(w.date, w.timeOfDay, w.season, w.occasion).joinToString(" · ")
            if (text.isNotEmpty()) LabeledText("When", text, basis = w.basis)
        }
        a.where?.let { w ->
            val text = listOfNotNull(w.place, w.kind, w.country).joinToString(" · ")
            if (text.isNotEmpty()) LabeledText("Where", text, basis = w.basis)
        }
        if (a.events.isNotEmpty()) {
            Text("Moments", style = MaterialTheme.typography.labelMedium, color = MaterialTheme.colorScheme.onSurfaceVariant)
            a.events.sortedWith(compareBy({ it.media }, { it.at })).forEach { e ->
                val playable = media.getOrNull(e.media)?.isVideo == true
                Row(
                    Modifier.fillMaxWidth().heightIn(min = 48.dp)
                        .let { if (playable) it.clickable(onClickLabel = "Play from ${Dates.clock(e.at)}", role = Role.Button) { onSeek(e.media, e.at) } else it }
                        .semantics(mergeDescendants = true) {}.testTag("event"),
                    horizontalArrangement = Arrangement.spacedBy(10.dp), verticalAlignment = Alignment.CenterVertically,
                ) {
                    Text(Dates.clock(e.at), color = if (playable) MaterialTheme.colorScheme.primary else MaterialTheme.colorScheme.onSurfaceVariant,
                        fontWeight = FontWeight.SemiBold, style = MaterialTheme.typography.labelLarge)
                    Text(e.text, style = MaterialTheme.typography.bodySmall, modifier = Modifier.weight(1f))
                }
            }
        }
        a.speech?.transcript?.takeIf { it.isNotBlank() }?.let { t ->
            var expanded by rememberSaveable { mutableStateOf(false) }
            Column(Modifier.testTag("transcript")) {
                Text("Transcript" + (a.speech.language?.let { " ($it)" } ?: ""), style = MaterialTheme.typography.labelMedium, color = MaterialTheme.colorScheme.onSurfaceVariant)
                Text(t, style = MaterialTheme.typography.bodySmall, maxLines = if (expanded) Int.MAX_VALUE else 6)
                if (t.length > 300) TextButton(onClick = { expanded = !expanded }) { Text(if (expanded) "Less" else "More") }
            }
        }
        a.context?.let { LabeledText("Context", it) }
        if (a.onScreenText.isNotEmpty()) LabeledText("On screen", a.onScreenText.joinToString(" · "))
        val things = a.objects + a.animals + a.brands
        if (things.isNotEmpty()) LabeledText("Seen", things.joinToString(", "))
        listOfNotNull(a.mood?.let { "Mood: $it" }, a.music?.let { "Music: $it" }).takeIf { it.isNotEmpty() }?.let {
            Text(it.joinToString(" · "), style = MaterialTheme.typography.bodySmall)
        }
        a.model?.let { Text("Analyzed by $it", style = MaterialTheme.typography.labelSmall, color = MaterialTheme.colorScheme.onSurfaceVariant) }
    }
}
