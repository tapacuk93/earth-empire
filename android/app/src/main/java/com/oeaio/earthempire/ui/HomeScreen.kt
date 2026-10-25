package com.oeaio.earthempire.ui

import androidx.compose.foundation.ExperimentalFoundationApi
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.aspectRatio
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyRow
import androidx.compose.foundation.lazy.grid.GridCells
import androidx.compose.foundation.lazy.grid.GridItemSpan
import androidx.compose.foundation.lazy.grid.LazyGridScope
import androidx.compose.foundation.lazy.grid.LazyVerticalGrid
import androidx.compose.foundation.lazy.grid.itemsIndexed
import androidx.compose.foundation.lazy.grid.rememberLazyGridState
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.KeyboardActions
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Close
import androidx.compose.material.icons.filled.Collections
import androidx.compose.material.icons.filled.PlayArrow
import androidx.compose.material.icons.filled.Repeat
import androidx.compose.material.icons.filled.Search
import androidx.compose.material.icons.filled.Settings
import androidx.compose.material.icons.filled.Slideshow
import androidx.compose.material3.AssistChip
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.FilterChip
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.InputChip
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.SegmentedButton
import androidx.compose.material3.SegmentedButtonDefaults
import androidx.compose.material3.SingleChoiceSegmentedButtonRow
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.TopAppBar
import androidx.compose.material3.pulltorefresh.PullToRefreshBox
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.derivedStateOf
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
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
import androidx.compose.ui.unit.sp
import com.oeaio.earthempire.data.Dates
import com.oeaio.earthempire.data.Item
import com.oeaio.earthempire.data.ItemKind
import com.oeaio.earthempire.data.MonitorHit
import com.oeaio.earthempire.data.Tag
import com.oeaio.earthempire.data.TagIndex
import kotlin.math.ln

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun HomeScreen(vm: HomeViewModel) {
    val nav = LocalNav.current
    val offline by vm.offline.collectAsState()
    val grid = rememberLazyGridState()
    val nearEnd by remember { derivedStateOf { grid.layoutInfo.visibleItemsInfo.lastOrNull()?.index?.let { it >= grid.layoutInfo.totalItemsCount - 6 } ?: false } }
    LaunchedEffect(nearEnd, vm.items.size) { if (nearEnd) vm.loadMore() }

    Column(Modifier.fillMaxSize()) {
        TopAppBar(
            title = { Text("Earth Empire") },
            actions = {
                IconButton(onClick = { homeFeed(vm, nav).let { if (it.isNotEmpty()) nav.feed(it, 0) } }, modifier = Modifier.testTag("home.fullscreen")) {
                    Icon(Icons.Filled.Slideshow, "Fullscreen videos")
                }
                IconButton(onClick = nav.settings) { Icon(Icons.Filled.Settings, "Settings") }
            },
        )
        PullToRefreshBox(isRefreshing = vm.refreshing, onRefresh = vm::refresh, modifier = Modifier.fillMaxSize().testTag("home.refresh")) {
            LazyVerticalGrid(
                columns = GridCells.Adaptive(110.dp), state = grid,
                contentPadding = PaddingValues(bottom = 24.dp),
                horizontalArrangement = Arrangement.spacedBy(2.dp), verticalArrangement = Arrangement.spacedBy(2.dp),
                modifier = Modifier.fillMaxSize().testTag("home.grid"),
            ) {
                full("banners") {
                    Column(Modifier.padding(horizontal = 16.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                        if (offline) OfflineBanner()
                        vm.homeError?.let { if (vm.profile == null) ErrorBanner(it) { vm.refresh() } }
                    }
                }
                if (vm.query.q == null) {
                    full("profile") { ProfileHeader(vm) }
                    full("highlights") { HighlightsRow(vm) }
                    if (vm.published.isNotEmpty()) full("published") { PublishedRow(vm.published) }
                }
                full("search") { SearchField(vm.query.q ?: "", vm::search) }
                full("mode") {
                    SingleChoiceSegmentedButtonRow(Modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = 8.dp).testTag("home.mode")) {
                        listOf("tags" to "Tag cloud", "timeline" to "Chronological").forEachIndexed { i, (v, label) ->
                            SegmentedButton(selected = vm.view == v, onClick = { vm.chooseView(v) }, shape = SegmentedButtonDefaults.itemShape(i, 2)) { Text(label) }
                        }
                    }
                }
                if (vm.view == "tags" && vm.query.q == null) full("cloud") { TagCloud(vm.tags, vm.query.tag, vm::setTag) }
                vm.query.tag?.let { t ->
                    full("tag.selected") {
                        InputChip(selected = true, onClick = { vm.setTag(null) }, label = { Text("#$t") },
                            trailingIcon = { Icon(Icons.Filled.Close, null, Modifier.size(18.dp)) },
                            modifier = Modifier.padding(horizontal = 16.dp).semantics { contentDescription = "Filtered by $t. Clear" }.testTag("tag.selected"))
                    }
                }
                full("filters") { FilterBar(vm) }
                if (vm.view == "timeline") timeline(vm.items) { nav.item(it.id) }
                else itemsIndexed(vm.items, key = { _, it -> it.id }) { _, item -> ItemTile(item) { nav.item(item.id) } }
                full("footer") {
                    Box(Modifier.fillMaxWidth().padding(24.dp), contentAlignment = Alignment.Center) {
                        when {
                            vm.loadingItems -> CircularProgressIndicator(Modifier.size(28.dp))
                            vm.itemsError != null -> ErrorBanner(vm.itemsError!!) { vm.loadMore() }
                            vm.items.isEmpty() && vm.complete -> Text("Nothing here yet.", color = MaterialTheme.colorScheme.onSurfaceVariant)
                            vm.complete -> Text("That is everything.", style = MaterialTheme.typography.labelMedium, color = MaterialTheme.colorScheme.onSurfaceVariant)
                        }
                    }
                }
            }
        }
    }
}

/** Every video Home shows, for its fullscreen mode: the published finds first, then the archive's. */
fun homeFeed(vm: HomeViewModel, nav: Nav): List<FeedEntry> =
    vm.published.mapNotNull { it.feedEntry(nav) } + vm.items.mapNotNull { item ->
        item.allMedia.firstOrNull { it.isVideo }?.let { m ->
            FeedEntry(item.id, m.url, m.poster, item.summary ?: item.caption ?: item.kind.label,
                Dates.parse(item.takenAt)?.let(Dates::long), null, detail = { nav.item(item.id) })
        }
    }

fun MonitorHit.feedEntry(nav: Nav): FeedEntry? = video.url?.let {
    FeedEntry(id, it, video.poster, video.title ?: source.name ?: "@${source.account}",
        "“$excerpt”" + (translation?.let { t -> "\n$t" } ?: ""), at, detail = { nav.hit(id) })
}

private fun LazyGridScope.full(key: String, content: @Composable () -> Unit) =
    item(key = key, span = { GridItemSpan(maxLineSpan) }) { content() }

private fun LazyGridScope.timeline(items: List<Item>, open: (Item) -> Unit) {
    val months = items.groupBy { Dates.parse(it.takenAt)?.let(Dates::monthTitle) ?: "Undated" }
    months.forEach { (month, list) ->
        full("m:$month") {
            Text(month, style = MaterialTheme.typography.titleSmall, fontWeight = FontWeight.SemiBold,
                modifier = Modifier.padding(start = 16.dp, top = 16.dp, bottom = 4.dp).semantics { heading() })
        }
        list.forEach { item -> full("t:${item.id}") { TimelineRow(item) { open(item) } } }
    }
}

@Composable
private fun TimelineRow(item: Item, onClick: () -> Unit) {
    Row(
        Modifier.fillMaxWidth().clickable(onClickLabel = "Open", role = Role.Button, onClick = onClick).padding(horizontal = 16.dp, vertical = 6.dp)
            .semantics(mergeDescendants = true) {}.testTag("timeline.${item.id}"),
        horizontalArrangement = Arrangement.spacedBy(12.dp), verticalAlignment = Alignment.CenterVertically,
    ) {
        RemoteImage(item.poster, null, Modifier.size(64.dp).clip(RoundedCornerShape(8.dp)))
        Column(Modifier.weight(1f)) {
            Text(Dates.parse(item.takenAt)?.let(Dates::medium) ?: "", style = MaterialTheme.typography.labelMedium, color = MaterialTheme.colorScheme.onSurfaceVariant)
            Text(item.summary ?: item.caption ?: item.kind.label, style = MaterialTheme.typography.bodyMedium, maxLines = 2, overflow = TextOverflow.Ellipsis)
            item.repostOf?.let { Text("Original by @${it.author}", style = MaterialTheme.typography.labelSmall, color = MaterialTheme.colorScheme.primary) }
        }
    }
}

@Composable
private fun ProfileHeader(vm: HomeViewModel) {
    val p = vm.profile
    Column {
    Row(Modifier.fillMaxWidth().padding(16.dp).semantics(mergeDescendants = true) {}.testTag("profile.header"), verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(16.dp)) {
        Avatar(p?.avatar, 76.dp, ring = true, description = p?.let { "${it.username} avatar" })
        Column(Modifier.weight(1f), verticalArrangement = Arrangement.spacedBy(4.dp)) {
            Text(p?.fullName ?: p?.username ?: " ", style = MaterialTheme.typography.titleLarge, fontWeight = FontWeight.Bold, modifier = Modifier.semantics { heading() })
            if (p != null) Text("@${p.username}", style = MaterialTheme.typography.bodyMedium, color = MaterialTheme.colorScheme.onSurfaceVariant)
            Row(horizontalArrangement = Arrangement.spacedBy(16.dp)) {
                Stat(p?.count("posts"), "posts"); Stat(p?.count("followers"), "followers"); Stat(p?.count("following"), "following")
            }
        }
    }
    p?.bio?.takeIf { it.isNotBlank() }?.let { Text(it, style = MaterialTheme.typography.bodyMedium, modifier = Modifier.padding(horizontal = 16.dp)) }
    }
}

@Composable
private fun Stat(n: Long?, label: String) {
    Column(Modifier.semantics(mergeDescendants = true) {}) {
        Text(n?.let(Dates::compact) ?: "–", fontWeight = FontWeight.Bold)
        Text(label, style = MaterialTheme.typography.labelSmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
    }
}

@Composable
private fun HighlightsRow(vm: HomeViewModel) {
    val nav = LocalNav.current
    if (vm.highlights.isEmpty()) return
    LazyRow(contentPadding = PaddingValues(horizontal = 16.dp, vertical = 8.dp), horizontalArrangement = Arrangement.spacedBy(14.dp), modifier = Modifier.testTag("highlights.row")) {
        items(vm.highlights, key = { it.id }) { h ->
            Column(
                Modifier.width(76.dp).clickable(onClickLabel = "Watch", role = Role.Button) { nav.story(h.id, null) }
                    .semantics(mergeDescendants = true) { contentDescription = "Highlight ${h.title}, ${h.itemIds.size} stories" }.testTag("highlight.${h.id}"),
                horizontalAlignment = Alignment.CenterHorizontally,
            ) {
                Avatar(h.cover, 64.dp, ring = true)
                Spacer(Modifier.height(4.dp))
                Text(h.title, style = MaterialTheme.typography.labelMedium, maxLines = 1, overflow = TextOverflow.Ellipsis)
            }
        }
    }
}

/** The monitor finds the owner added, shown first on Home and on the site. */
@Composable
private fun PublishedRow(hits: List<MonitorHit>) {
    val nav = LocalNav.current
    Column(Modifier.padding(vertical = 8.dp)) {
        SectionTitle("Found and published", Modifier.padding(horizontal = 16.dp))
        LazyRow(contentPadding = PaddingValues(horizontal = 16.dp, vertical = 8.dp), horizontalArrangement = Arrangement.spacedBy(10.dp), modifier = Modifier.testTag("published.row")) {
            items(hits, key = { it.id }) { hit ->
                Surface(
                    shape = RoundedCornerShape(12.dp), tonalElevation = 2.dp,
                    modifier = Modifier.width(220.dp).clickable(onClickLabel = "Play") {
                        val entries = hits.mapNotNull { it.feedEntry(nav) }
                        nav.feed(entries, entries.indexOfFirst { it.id == hit.id }.coerceAtLeast(0))
                    }.semantics(mergeDescendants = true) {},
                ) {
                    Column {
                        Box {
                            RemoteImage(hit.video.poster, null, Modifier.fillMaxWidth().aspectRatio(16 / 9f))
                            Icon(Icons.Filled.PlayArrow, null, tint = Color.White, modifier = Modifier.align(Alignment.Center).size(36.dp))
                        }
                        Column(Modifier.padding(8.dp)) {
                            Text(hit.source.name ?: "@${hit.source.account}", style = MaterialTheme.typography.labelMedium, maxLines = 1, overflow = TextOverflow.Ellipsis)
                            Text("“${hit.translation ?: hit.excerpt}”", style = MaterialTheme.typography.bodySmall, maxLines = 2, overflow = TextOverflow.Ellipsis)
                        }
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
        modifier = Modifier.fillMaxWidth().padding(horizontal = 16.dp).testTag("search.field"),
        placeholder = { Text("Search captions, places, people…") },
        leadingIcon = { Icon(Icons.Filled.Search, null) },
        trailingIcon = { if (text.isNotEmpty()) IconButton(onClick = { text = ""; onSearch("") }) { Icon(Icons.Filled.Close, "Clear search") } },
        singleLine = true, shape = RoundedCornerShape(24.dp),
        keyboardOptions = KeyboardOptions(imeAction = ImeAction.Search),
        keyboardActions = KeyboardActions(onSearch = { onSearch(text) }),
    )
}

@Composable
private fun FilterBar(vm: HomeViewModel) {
    val nav = LocalNav.current
    LazyRow(contentPadding = PaddingValues(horizontal = 16.dp), horizontalArrangement = Arrangement.spacedBy(8.dp), modifier = Modifier.padding(vertical = 4.dp).testTag("filters")) {
        items(ItemKind.filters, key = { "k" + it.wire }) { k ->
            FilterChip(selected = vm.query.kind == k, onClick = { vm.setKind(if (vm.query.kind == k) null else k) }, label = { Text(k.label + "s") },
                modifier = Modifier.testTag("filter.kind.${k.wire}"))
        }
        items(vm.categories, key = { "c" + it.slug }) { c ->
            FilterChip(selected = vm.query.category == c.slug, onClick = { vm.setCategory(if (vm.query.category == c.slug) null else c.slug) },
                label = { Text("${c.name} · ${c.count}") }, modifier = Modifier.testTag("filter.category.${c.slug}"))
        }
        if (vm.categories.isNotEmpty()) item("all") { AssistChip(onClick = nav.categories, label = { Text("All categories") }) }
    }
}

@Composable
fun ItemTile(item: Item, onClick: () -> Unit) {
    Box(
        Modifier.aspectRatio(1f).clickable(onClickLabel = "Open", role = Role.Button, onClick = onClick)
            .semantics(mergeDescendants = true) { contentDescription = item.accessibilityLabel }.testTag("tile.${item.id}"),
    ) {
        RemoteImage(item.poster, null, Modifier.fillMaxSize())
        val icon = when {
            item.isRepost -> Icons.Filled.Repeat
            item.kind == ItemKind.Carousel -> Icons.Filled.Collections
            item.hasVideo -> Icons.Filled.PlayArrow
            else -> null
        }
        icon?.let { Icon(it, null, tint = Color.White, modifier = Modifier.align(Alignment.TopEnd).padding(6.dp).size(20.dp)) }
    }
}

/** Tags sized by how many items have them (log scale), alphabetical; tap filters, tap again clears. */
@Composable
fun TagCloud(tags: List<Tag>, selected: String?, onSelect: (String?) -> Unit, max: Int = 60) {
    var showAll by rememberSaveable { mutableStateOf(false) }
    val unique = remember(tags) { TagIndex.dedupe(tags) }
    val shown = unique.take(if (showAll) 300 else max).sortedBy { it.tag }
    Column(Modifier.padding(horizontal = 16.dp).testTag("tag.cloud")) {
        if (tags.isEmpty()) {
            Text("Tags appear once items are analyzed.", style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
            return@Column
        }
        val lo = shown.minOf { it.count }.toDouble(); val hi = shown.maxOf { it.count }.toDouble()
        FlowRow(horizontalArrangement = Arrangement.spacedBy(6.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
            shown.forEach { t ->
                val w = tagWeight(t.count, lo, hi)
                val isSel = selected.equals(t.tag, ignoreCase = true)
                val color = tagColor(t.kind)
                Surface(
                    shape = RoundedCornerShape(50), color = if (isSel) color else color.copy(alpha = 0.12f),
                    modifier = Modifier.clickable(role = Role.Button) { onSelect(if (isSel) null else t.tag) }
                        .semantics { contentDescription = "${t.tag}, ${t.kind}, ${t.count} items" + if (isSel) ", selected" else "" }
                        .testTag("tag.${t.tag}"),
                ) {
                    Text(t.tag, fontSize = (12 + 10 * w).sp, fontWeight = if (w > 0.6) FontWeight.SemiBold else FontWeight.Normal,
                        color = if (isSel) Color.White else MaterialTheme.colorScheme.onSurface,
                        modifier = Modifier.padding(horizontal = 10.dp, vertical = 4.dp))
                }
            }
        }
        if (unique.size > max) TextButton(onClick = { showAll = !showAll }) { Text(if (showAll) "Fewer tags" else "More tags") }
    }
}

/** 0…1 on a log scale, so a few very common tags do not shrink the rest to nothing. */
fun tagWeight(count: Int, lo: Double, hi: Double): Double =
    if (hi <= lo) 0.5 else (ln(count.toDouble()) - ln(lo)) / (ln(hi) - ln(lo))
