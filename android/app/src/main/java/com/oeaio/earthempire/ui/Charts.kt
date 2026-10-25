package com.oeaio.earthempire.ui

import androidx.compose.foundation.Canvas
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.aspectRatio
import androidx.compose.foundation.layout.fillMaxHeight
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyRow
import androidx.compose.foundation.lazy.itemsIndexed
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.AssistChip
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.PathEffect
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import com.oeaio.earthempire.data.Insights
import java.time.format.TextStyle
import java.util.Locale
import kotlin.math.max
import kotlin.math.sqrt

// Home's charts. One hue (the accent) carries magnitude everywhere; labels and values wear the
// text colors, never the bar color; each mark is a button with its value in words, and the
// place chips under the map are its table view.

private val BarShape = RoundedCornerShape(topStart = 4.dp, topEnd = 4.dp)
private val HBarShape = RoundedCornerShape(topEnd = 4.dp, bottomEnd = 4.dp)

/** Items per month as a band of columns, scrolled to the newest; tap a month to watch it. */
@Composable
fun TimelineBand(months: List<Insights.Month>, onMonth: (Insights.Month) -> Unit, modifier: Modifier = Modifier) {
    if (months.isEmpty()) return
    val peak = max(1, months.maxOf { it.count })
    val state = rememberLazyListState()
    LaunchedEffect(months.size) { state.scrollToItem((months.size - 1).coerceAtLeast(0)) }
    val bar = MaterialTheme.colorScheme.primary
    LazyRow(state = state, horizontalArrangement = Arrangement.spacedBy(2.dp), modifier = modifier.fillMaxWidth().height(132.dp).testTag("chart.timeline")) {
        itemsIndexed(months, key = { _, m -> m.month.toString() }) { _, m ->
            val name = m.month.month.getDisplayName(TextStyle.SHORT, Locale.getDefault())
            Column(
                Modifier.width(30.dp).fillMaxHeight()
                    .clickable(enabled = m.count > 0, role = Role.Button, onClickLabel = "Watch") { onMonth(m) }
                    .semantics(mergeDescendants = true) { contentDescription = "$name ${m.month.year}: ${m.items.size} items" + if (m.hits > 0) ", ${m.hits} detected" else "" },
                horizontalAlignment = Alignment.CenterHorizontally, verticalArrangement = Arrangement.Bottom,
            ) {
                if (m.count > 0) Text("${m.count}", style = MaterialTheme.typography.labelSmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
                Box(Modifier.width(18.dp).height((84f * m.count / peak).dp.coerceAtLeast(if (m.count > 0) 3.dp else 1.dp))
                    .clip(BarShape).background(if (m.count > 0) bar else MaterialTheme.colorScheme.outlineVariant))
                Spacer(Modifier.height(4.dp))
                Text(if (m.month.monthValue == 1 || m === months.first()) "${m.month.year % 100}’" else name.take(1),
                    style = MaterialTheme.typography.labelSmall, color = MaterialTheme.colorScheme.onSurfaceVariant, maxLines = 1)
            }
        }
    }
}

/** Horizontal bars, longest first, labels on the left and the count after the bar. */
@Composable
fun BarChart(bars: List<Insights.Bar>, onBar: (Insights.Bar) -> Unit, modifier: Modifier = Modifier, tag: String = "chart.bars") {
    if (bars.isEmpty()) return
    val peak = max(1, bars.maxOf { it.count })
    val bar = MaterialTheme.colorScheme.primary
    Column(modifier.testTag(tag), verticalArrangement = Arrangement.spacedBy(2.dp)) {
        bars.forEach { b ->
            Row(
                Modifier.fillMaxWidth().heightIn(min = 32.dp).clickable(role = Role.Button, onClickLabel = "Watch") { onBar(b) }
                    .semantics(mergeDescendants = true) { contentDescription = "${b.label}: ${b.count}" },
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Text(b.label, style = MaterialTheme.typography.bodySmall, maxLines = 1, overflow = TextOverflow.Ellipsis, modifier = Modifier.width(112.dp))
                Box(Modifier.weight(1f)) {
                    Box(Modifier.fillMaxWidth(b.count.toFloat() / peak).height(14.dp).clip(HBarShape).background(bar))
                }
                Text("${b.count}", style = MaterialTheme.typography.labelMedium, color = MaterialTheme.colorScheme.onSurfaceVariant,
                    modifier = Modifier.width(36.dp).padding(start = 6.dp))
            }
        }
    }
}

/**
 * The places with coordinates on a latitude/longitude grid fitted to them (dot area = items),
 * and every place as a chip below, which is also the map's accessible table.
 */
@Composable
fun LocationMap(places: List<Insights.Place>, onPlace: (Insights.Place) -> Unit, modifier: Modifier = Modifier) {
    if (places.isEmpty()) return
    val located = places.filter { it.lat != null && it.lng != null }
    val dot = MaterialTheme.colorScheme.primary
    val grid = MaterialTheme.colorScheme.outlineVariant
    val ring = MaterialTheme.colorScheme.surface
    Column(modifier.testTag("chart.map"), verticalArrangement = Arrangement.spacedBy(8.dp)) {
        if (located.isNotEmpty()) {
            val minLat = located.minOf { it.lat!! }; val maxLat = located.maxOf { it.lat!! }
            val minLng = located.minOf { it.lng!! }; val maxLng = located.maxOf { it.lng!! }
            // At least 8° each way, so one place is not a lone dot in a void.
            val padLat = max(4.0, (maxLat - minLat) * 0.2); val padLng = max(6.0, (maxLng - minLng) * 0.2)
            val south = minLat - padLat; val north = maxLat + padLat; val west = minLng - padLng; val east = maxLng + padLng
            val peak = located.maxOf { it.count }.toFloat()
            Canvas(
                Modifier.fillMaxWidth().aspectRatio(1.8f).clip(RoundedCornerShape(12.dp)).background(MaterialTheme.colorScheme.surfaceVariant.copy(alpha = 0.5f))
                    .semantics { contentDescription = "Map of ${located.size} places: " + located.joinToString("; ") { "${it.name}, ${it.count}" } },
            ) {
                fun x(lng: Double) = ((lng - west) / (east - west) * size.width).toFloat()
                fun y(lat: Double) = ((north - lat) / (north - south) * size.height).toFloat()
                val dash = PathEffect.dashPathEffect(floatArrayOf(6f, 6f))
                var g = kotlin.math.ceil(west / 5) * 5
                while (g < east) { drawLine(grid, Offset(x(g), 0f), Offset(x(g), size.height), 1f, pathEffect = dash); g += 5 }
                g = kotlin.math.ceil(south / 5) * 5
                while (g < north) { drawLine(grid, Offset(0f, y(g)), Offset(size.width, y(g)), 1f, pathEffect = dash); g += 5 }
                located.sortedByDescending { it.count }.forEach { p ->
                    val r = (8.dp.toPx() + 14.dp.toPx() * sqrt(p.count / peak))
                    val c = Offset(x(p.lng!!), y(p.lat!!))
                    drawCircle(ring, r + 2.dp.toPx(), c)
                    drawCircle(dot.copy(alpha = 0.85f), r, c)
                }
            }
        }
        FlowRow(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
            places.take(16).forEach { p ->
                AssistChip(onClick = { onPlace(p) }, label = { Text("${p.name} · ${p.count}", maxLines = 1) },
                    modifier = Modifier.semantics { contentDescription = "${p.name}: ${p.count} items" }.testTag("place.${p.name}"))
            }
        }
    }
}

/** A small key figure: a number over its label. */
@Composable
fun Figure(value: String, label: String, modifier: Modifier = Modifier) {
    Column(modifier.semantics(mergeDescendants = true) {}) {
        Text(value, style = MaterialTheme.typography.titleLarge, color = MaterialTheme.colorScheme.onSurface)
        Text(label, style = MaterialTheme.typography.labelSmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
    }
}

