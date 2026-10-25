package com.oeaio.earthempire.ui

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.LazyRow
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.lazy.itemsIndexed
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.KeyboardActions
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Close
import androidx.compose.material.icons.filled.GraphicEq
import androidx.compose.material.icons.filled.PlayArrow
import androidx.compose.material.icons.filled.Search
import androidx.compose.material.icons.filled.Slideshow
import androidx.compose.material.icons.outlined.Key
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.ElevatedCard
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.SuggestionChip
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TopAppBar
import androidx.compose.material3.pulltorefresh.PullToRefreshBox
import androidx.compose.runtime.Composable
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.heading
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import com.oeaio.earthempire.data.Dates
import com.oeaio.earthempire.data.Insights
import com.oeaio.earthempire.data.Item
import com.oeaio.earthempire.data.ItemQuery
import com.oeaio.earthempire.data.Section
import kotlinx.coroutines.launch

/**
 * Home: everything published, as infographics - a band of months, a map of places, tag and
 * category bars, then the owner's dedicated sections and the common ones, each a panel with its
 * counts, people, places, key moments and media. Any item opens the vertical feed of its context.
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun HomeScreen(vm: HomeViewModel) {
    val nav = LocalNav.current
    val offline by vm.offline.collectAsState()
    val owner by vm.owner.collectAsState()
    val list = rememberLazyListState()
    var searching by rememberSaveable { mutableStateOf(false) }
    val scope = rememberCoroutineScope()
    fun feed(title: String, items: List<Item>, start: Item? = null) {
        if (items.isEmpty()) return
        nav.feed(FeedContext(title, items.map { FeedItem.Post(it) }, start?.let { s -> items.indexOfFirst { it.id == s.id } }?.coerceAtLeast(0) ?: 0))
    }

    Column(Modifier.fillMaxSize()) {
        TopAppBar(
            title = { Text("Earth Empire", modifier = Modifier.semantics { heading() }) },
            actions = {
                IconButton(onClick = { searching = !searching; if (!searching) vm.search(null) }) { Icon(if (searching) Icons.Filled.Close else Icons.Filled.Search, if (searching) "Close search" else "Search") }
                IconButton(onClick = { feed("Videos", vm.items.filter { it.hasVideo }) }, modifier = Modifier.testTag("home.fullscreen")) {
                    Icon(Icons.Filled.Slideshow, "Watch every video")
                }
                // The owner's discreet way in; the owner has the Settings tab instead.
                if (!owner) IconButton(onClick = nav.settings, modifier = Modifier.testTag("owner.signin")) {
                    Icon(Icons.Outlined.Key, "Owner sign-in", tint = MaterialTheme.colorScheme.onSurfaceVariant.copy(alpha = 0.6f))
                }
            },
        )
        PullToRefreshBox(isRefreshing = vm.refreshing, onRefresh = vm::refresh, modifier = Modifier.fillMaxSize().testTag("home.refresh")) {
            LazyColumn(state = list, contentPadding = PaddingValues(start = 16.dp, end = 16.dp, bottom = 24.dp), verticalArrangement = Arrangement.spacedBy(14.dp),
                modifier = Modifier.fillMaxSize().testTag("home.list")) {
                if (offline) item("offline") { OfflineBanner() }
                vm.error?.let { e -> item("error") { ErrorBanner(e) { vm.refresh() } } }
                if (searching || vm.query != null) item("search") { SearchField(vm.query ?: "", vm::search) }
                if (!vm.loaded) item("loading") { Box(Modifier.fillMaxWidth().padding(32.dp), contentAlignment = Alignment.Center) { CircularProgressIndicator() } }
                if (vm.loaded) item("figures") { Figures(vm) }
                if (vm.months.isNotEmpty()) item("timeline") {
                    ChartCard("Over time", "Items per month; tap a month to watch it") {
                        TimelineBand(vm.months, { m ->
                            val hits = vm.published.filter { h -> Dates.parse(h.publishedAt ?: h.foundAt)?.let { java.time.YearMonth.from(it.atZone(java.time.ZoneOffset.UTC)) } == m.month }
                            nav.feed(FeedContext("${m.month.month.getDisplayName(java.time.format.TextStyle.FULL, java.util.Locale.getDefault())} ${m.month.year}",
                                m.items.map { FeedItem.Post(it) } + hits.map { FeedItem.Hit(it) }))
                        })
                    }
                }
                if (vm.places.isNotEmpty()) item("map") {
                    ChartCard("Places", "${vm.places.size} places; dot size is the number of items") {
                        LocationMap(vm.places, { p -> feed(p.name, p.items) })
                    }
                }
                val tagBars = Insights.tagBars(vm.tags)
                if (tagBars.isNotEmpty()) item("tags") {
                    ChartCard("Tags", "The most common tags from the analysis") {
                        BarChart(tagBars, { b -> scope.launch { feed("#${b.label}", vm.itemsWith(ItemQuery(tag = b.label))) } }, tag = "chart.tags")
                    }
                }
                val catBars = Insights.categoryBars(vm.categories)
                if (catBars.isNotEmpty()) item("categories") {
                    ChartCard("Categories", "Items per category") {
                        BarChart(catBars, { b -> scope.launch { feed(b.label, vm.itemsWith(ItemQuery(category = b.kind))) } }, tag = "chart.categories")
                    }
                }
                Section.entries.forEach { section ->
                    val panels = vm.panels.filter { it.section == section }
                    if (panels.isNotEmpty()) {
                        item("section.${section.wire}") {
                            Text(section.title, style = MaterialTheme.typography.headlineSmall, fontWeight = FontWeight.SemiBold,
                                modifier = Modifier.padding(top = 12.dp).semantics { heading() }.testTag("section.${section.wire}"))
                        }
                        items(panels, key = { "panel.${section.wire}.${it.highlight?.id ?: "hits"}" }) { p -> PanelCard(p) }
                    }
                }
                if (vm.loaded && vm.items.isEmpty() && vm.published.isEmpty() && vm.error == null) item("empty") {
                    Text(if (vm.query != null) "Nothing matches “${vm.query}”." else "Nothing published yet.", color = MaterialTheme.colorScheme.onSurfaceVariant)
                }
            }
        }
    }
}

@Composable
private fun Figures(vm: HomeViewModel) {
    val first = vm.items.mapNotNull { Dates.parse(it.takenAt) }.minOrNull()
    val last = vm.items.mapNotNull { Dates.parse(it.takenAt) }.maxOrNull()
    Column(Modifier.testTag("figures")) {
        Row(Modifier.fillMaxWidth().padding(top = 4.dp), horizontalArrangement = Arrangement.SpaceBetween) {
            Figure("${vm.items.size}", "items")
            Figure("${vm.items.count { it.hasVideo }}", "with video")
            Figure("${vm.places.size}", "places")
            Figure("${vm.published.size}", "detected")
        }
        if (first != null && last != null) Text("${Dates.medium(first)} – ${Dates.medium(last)}" + (vm.query?.let { " · matching “$it”" } ?: ""),
            style = MaterialTheme.typography.labelMedium, color = MaterialTheme.colorScheme.onSurfaceVariant, modifier = Modifier.padding(top = 4.dp))
    }
}

@Composable
private fun ChartCard(title: String, caption: String, content: @Composable () -> Unit) {
    ElevatedCard(Modifier.fillMaxWidth()) {
        Column(Modifier.padding(14.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
            Column {
                Text(title, style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.SemiBold, modifier = Modifier.semantics { heading() })
                Text(caption, style = MaterialTheme.typography.labelMedium, color = MaterialTheme.colorScheme.onSurfaceVariant)
            }
            content()
        }
    }
}

/** A section panel: its counts, media, people, places and key moments. */
@Composable
private fun PanelCard(p: Insights.Panel) {
    val nav = LocalNav.current
    val entries: List<FeedItem> = p.hits.map { FeedItem.Hit(it) } + p.items.map { FeedItem.Post(it) }
    ElevatedCard(Modifier.fillMaxWidth().testTag("panel.${p.highlight?.id ?: "hits.${p.section.wire}"}")) {
        Column(Modifier.padding(vertical = 14.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
            Column(Modifier.padding(horizontal = 14.dp)) {
                Text(p.title, style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.SemiBold, modifier = Modifier.semantics { heading() })
                val span = if (p.first != null && p.last != null) " · ${Dates.medium(p.first!!)} – ${Dates.medium(p.last!!)}" else ""
                Text(listOfNotNull(
                    p.items.size.takeIf { it > 0 }?.let { "$it items" }, p.hits.size.takeIf { it > 0 }?.let { "$it detected" },
                    p.videos.takeIf { it > 0 }?.let { "$it videos" },
                ).joinToString(" · ") + span, style = MaterialTheme.typography.labelMedium, color = MaterialTheme.colorScheme.onSurfaceVariant)
            }
            // The media, inside the panel.
            LazyRow(contentPadding = PaddingValues(horizontal = 14.dp), horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                itemsIndexed(entries, key = { _, e -> e.key }) { i, e ->
                    val (poster, label, video) = when (e) {
                        is FeedItem.Post -> Triple(e.item.poster, e.item.accessibilityLabel, e.item.hasVideo)
                        is FeedItem.Hit -> Triple(e.hit.poster, "Detected: ${e.hit.excerpt.en ?: e.hit.excerpt.text}, ${e.hit.sourceTitle}", e.hit.playable != null)
                    }
                    Box(Modifier.size(width = 92.dp, height = 132.dp).clip(RoundedCornerShape(10.dp))
                        .clickable(role = Role.Button, onClickLabel = "Watch") { nav.feed(FeedContext(p.title, entries, i)) }
                        .semantics(mergeDescendants = true) { contentDescription = label }.testTag("media.${e.key}")) {
                        RemoteImage(poster, null, Modifier.fillMaxSize())
                        if (e is FeedItem.Hit) Surface(color = Color.Black.copy(alpha = 0.6f), modifier = Modifier.align(Alignment.BottomStart).fillMaxWidth()) {
                            Text(e.hit.excerpt.en ?: e.hit.excerpt.text, color = Color.White, style = MaterialTheme.typography.labelSmall, maxLines = 3,
                                overflow = TextOverflow.Ellipsis, modifier = Modifier.padding(4.dp))
                        }
                        if (video) Icon(if (e is FeedItem.Hit) Icons.Filled.GraphicEq else Icons.Filled.PlayArrow, null, tint = Color.White,
                            modifier = Modifier.align(Alignment.TopEnd).padding(4.dp).size(18.dp))
                    }
                }
            }
            val people = p.people.take(8)
            if (people.isNotEmpty()) Column(Modifier.padding(horizontal = 14.dp)) {
                Text("People", style = MaterialTheme.typography.labelMedium, color = MaterialTheme.colorScheme.onSurfaceVariant)
                FlowRow(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                    people.forEach { who ->
                        SuggestionChip(onClick = {}, label = { Text(who.who + if (who.count > 1) " ×${who.count}" else "") },
                            modifier = Modifier.semantics { contentDescription = "${who.who}, named from ${who.basis ?: "the post"}, in ${who.count} items" })
                    }
                }
            }
            val places = p.places.take(5)
            if (places.isNotEmpty()) Text("Places: " + places.joinToString(", ") { "${it.name} (${it.count})" },
                style = MaterialTheme.typography.bodySmall, modifier = Modifier.padding(horizontal = 14.dp))
            val moments = p.moments.take(3)
            if (moments.isNotEmpty()) Column(Modifier.padding(horizontal = 14.dp)) {
                HorizontalDivider(Modifier.padding(bottom = 6.dp))
                Text("Key moments", style = MaterialTheme.typography.labelMedium, color = MaterialTheme.colorScheme.onSurfaceVariant)
                moments.forEach { m ->
                    Row(Modifier.fillMaxWidth().heightIn(min = 40.dp).clickable(role = Role.Button, onClickLabel = "Play from ${Dates.clock(m.at)}") {
                        val i = entries.indexOfFirst { it is FeedItem.Post && it.item.id == m.item.id }
                        val list = entries.toMutableList().also { l -> if (i >= 0) l[i] = FeedItem.Post(m.item, m.media, m.at) }
                        nav.feed(FeedContext(p.title, list, i.coerceAtLeast(0)))
                    }.semantics(mergeDescendants = true) {}, verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                        Text(Dates.clock(m.at), color = MaterialTheme.colorScheme.primary, fontWeight = FontWeight.SemiBold, style = MaterialTheme.typography.labelLarge, modifier = Modifier.width(44.dp))
                        Text(m.text, style = MaterialTheme.typography.bodySmall, maxLines = 2, overflow = TextOverflow.Ellipsis, modifier = Modifier.weight(1f))
                    }
                }
            }
        }
    }
}

@Composable
private fun SearchField(current: String, onSearch: (String) -> Unit) {
    var text by rememberSaveable(current) { mutableStateOf(current) }
    OutlinedTextField(
        value = text, onValueChange = { text = it },
        modifier = Modifier.fillMaxWidth().testTag("search.field"),
        placeholder = { Text("Search captions, places, people…") },
        leadingIcon = { Icon(Icons.Filled.Search, null) },
        trailingIcon = { if (text.isNotEmpty()) IconButton(onClick = { text = ""; onSearch("") }) { Icon(Icons.Filled.Close, "Clear search") } },
        singleLine = true, shape = RoundedCornerShape(24.dp),
        keyboardOptions = KeyboardOptions(imeAction = ImeAction.Search),
        keyboardActions = KeyboardActions(onSearch = { onSearch(text) }),
    )
}

