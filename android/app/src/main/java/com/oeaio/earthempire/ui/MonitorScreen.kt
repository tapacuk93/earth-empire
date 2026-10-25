package com.oeaio.earthempire.ui

import android.util.Log
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.aspectRatio
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.foundation.clickable
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.automirrored.filled.OpenInNew
import androidx.compose.material.icons.filled.Add
import androidx.compose.material.icons.filled.CheckCircle
import androidx.compose.material.icons.filled.PlayArrow
import androidx.compose.material.icons.filled.Slideshow
import androidx.compose.material.icons.filled.Sync
import androidx.compose.material3.Button
import androidx.compose.material3.FilterChip
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.ElevatedCard
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.FilledTonalButton
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.SnackbarHostState
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TopAppBar
import androidx.compose.material3.pulltorefresh.PullToRefreshBox
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.derivedStateOf
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.font.FontStyle
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.oeaio.earthempire.AppContainer
import com.oeaio.earthempire.data.ApiException
import com.oeaio.earthempire.data.Dates
import com.oeaio.earthempire.data.MonitorApi
import com.oeaio.earthempire.data.MonitorHit
import com.oeaio.earthempire.data.Pager
import com.oeaio.earthempire.data.TAG
import com.oeaio.earthempire.data.Section
import com.oeaio.earthempire.data.homeSection
import com.oeaio.earthempire.data.suggestion
import kotlinx.coroutines.launch

/** Detected: the monitor's hits, highest confidence first. */
class MonitorViewModel(private val container: AppContainer) : ViewModel() {
    private var api: MonitorApi = container.monitor.value
    var hits by mutableStateOf<List<MonitorHit>>(emptyList()); private set
    var error by mutableStateOf<Throwable?>(null); private set
    var loading by mutableStateOf(false); private set
    var refreshing by mutableStateOf(false); private set
    var complete by mutableStateOf(false); private set
    var isMock by mutableStateOf(api.isMock); private set
    /** "name", "language" or null for both. */
    var kind by mutableStateOf<String?>(null); private set
    /** Ids being published or unpublished right now. */
    var busy by mutableStateOf<Set<String>>(emptySet()); private set
    val messages = SnackbarHostState()
    private var pager = makePager()
    private var started = false

    private fun makePager() = Pager<MonitorHit>({ it.id }) { c -> val p = api.hits(c, 30, kind); p.hits to p.next }

    init {
        viewModelScope.launch { container.monitor.collect { if (it !== api) { api = it; if (started) refresh() } } }
        viewModelScope.launch { container.owner.collect { if (it && !started) { started = true; refresh() } } }
    }

    fun chooseKind(k: String?) { if (k != kind) { kind = k; refresh() } }

    fun refresh() {
        pager = makePager()
        val p = pager
        viewModelScope.launch {
            refreshing = true; loading = true
            try { p.refresh(); if (p === pager) { hits = sorted(p.items); complete = p.isComplete; error = null } }
            catch (e: Exception) { if (p === pager) { error = e; Log.w(TAG, "monitor failed: $e") } }
            finally { refreshing = false; loading = false; isMock = api.isMock }
        }
    }

    fun loadMore() {
        if (loading || complete || !started) return
        val p = pager
        viewModelScope.launch {
            loading = true
            try { p.loadMore(); if (p === pager) { hits = sorted(p.items); complete = p.isComplete } }
            catch (e: Exception) { error = e }
            finally { loading = false }
        }
    }

    /** The backend sorts by confidence; keep that order across pages. */
    private fun sorted(list: List<MonitorHit>) = list.sortedByDescending { it.confidence }

    /** "+": publishes the hit to Home and the site (or takes it back). */
    fun publish(hit: MonitorHit, publish: Boolean = true, section: Section? = null) {
        val token = container.settings.adminToken
        busy = busy + hit.id
        viewModelScope.launch {
            try {
                val updated = api.publish(hit.id, token, publish, section)
                hits = hits.map { if (it.id == hit.id) updated else it }
                messages.showSnackbar(if (publish) "Published to Home and the site, in ${(section ?: updated.homeSection).title}." else "Removed from Home.")
            } catch (e: Exception) {
                messages.showSnackbar(if (e is ApiException.Status && (e.code == 401 || e.code == 403)) "The admin token was refused." else e.message ?: "Could not publish.")
            } finally { busy = busy - hit.id }
        }
    }

    /** "Fetch N more": queues N more videos to scan (of one platform, or of all). */
    fun fetchMore(n: Int, platform: String?) {
        viewModelScope.launch {
            try { messages.showSnackbar(api.fetchMore(n, platform).message) }
            catch (e: Exception) {
                messages.showSnackbar(if (e is ApiException.Status && e.code == 429) "The scan queue is full; try later." else e.message ?: "Could not ask for more.")
            }
        }
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun MonitorScreen(vm: MonitorViewModel) {
    val nav = LocalNav.current
    val list = rememberLazyListState()
    val nearEnd by remember { derivedStateOf { list.layoutInfo.visibleItemsInfo.lastOrNull()?.index?.let { it >= list.layoutInfo.totalItemsCount - 3 } ?: false } }
    LaunchedEffect(nearEnd, vm.hits.size) { if (nearEnd) vm.loadMore() }
    val feed = { start: MonitorHit? ->
        if (vm.hits.isNotEmpty()) nav.feed(FeedContext("Detected", vm.hits.map { FeedItem.Hit(it) }, start?.let { s -> vm.hits.indexOfFirst { it.id == s.id } }?.coerceAtLeast(0) ?: 0))
    }
    Column(Modifier.fillMaxSize()) {
        TopAppBar(
            title = { Text("Detected") },
            actions = {
                FetchMoreButton(null, vm::fetchMore, compact = true)
                IconButton(onClick = { feed(null) }, modifier = Modifier.testTag("monitor.fullscreen")) { Icon(Icons.Filled.Slideshow, "Fullscreen") }
            },
        )
        PullToRefreshBox(isRefreshing = vm.refreshing, onRefresh = vm::refresh, modifier = Modifier.fillMaxSize()) {
            LazyColumn(state = list, contentPadding = PaddingValues(16.dp), verticalArrangement = Arrangement.spacedBy(12.dp), modifier = Modifier.fillMaxSize().testTag("monitor.list")) {
                if (vm.isMock) item("mock") { SampleBanner("Sample data (Settings → Data).") }
                item("kinds") {
                    Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                        listOf(null to "All", "name" to "Names", "language" to "Languages").forEach { (k, label) ->
                            FilterChip(selected = vm.kind == k, onClick = { vm.chooseKind(k) }, label = { Text(label) }, modifier = Modifier.testTag("kind.${k ?: "all"}"))
                        }
                    }
                }
                vm.error?.let { e -> item("error") { ErrorBanner(e) { vm.refresh() } } }
                items(vm.hits, key = { it.id }) { hit ->
                    HitCard(hit, busy = hit.id in vm.busy, onPlay = { feed(hit) }, onPublish = vm::publish, onFetchMore = vm::fetchMore)
                }
                item("footer") {
                    Box(Modifier.fillMaxWidth().padding(8.dp), contentAlignment = Alignment.Center) {
                        when {
                            vm.loading && !vm.refreshing -> CircularProgressIndicator(Modifier.size(28.dp))
                            vm.complete && vm.hits.isEmpty() -> Text("Nothing detected yet.")
                            vm.complete -> FetchMoreButton(null, vm::fetchMore)
                        }
                    }
                }
            }
        }
    }
}

/** "Fetch N more": asks the backend to scan N more videos (of one platform, or of all). */
@Composable
fun FetchMoreButton(platform: String?, onFetch: (Int, String?) -> Unit, compact: Boolean = false, label: String = "Fetch more") {
    var open by remember { mutableStateOf(false) }
    Box {
        if (compact) IconButton(onClick = { open = true }, modifier = Modifier.testTag("fetch.more.all")) { Icon(Icons.Filled.Sync, "Fetch more videos") }
        else OutlinedButton(onClick = { open = true }, modifier = Modifier.testTag("fetch.more")) { Text(label, maxLines = 1, overflow = TextOverflow.Ellipsis) }
        DropdownMenu(open, onDismissRequest = { open = false }) {
            listOf(5, 10, 25, 50).forEach { n ->
                DropdownMenuItem(text = { Text("Fetch $n more" + (platform?.let { " from $it" } ?: "")) }, onClick = { open = false; onFetch(n, platform) })
            }
        }
    }
}

@Composable
fun HitCard(hit: MonitorHit, busy: Boolean, onPlay: () -> Unit, onPublish: (MonitorHit, Boolean, Section?) -> Unit, onFetchMore: (Int, String?) -> Unit) {
    val context = androidx.compose.ui.platform.LocalContext.current
    ElevatedCard(Modifier.fillMaxWidth().testTag("hit.${hit.id}")) {
        Box(Modifier.clickable(onClickLabel = "Play from ${Dates.clock(hit.start)}", onClick = onPlay)) {
            RemoteImage(hit.poster, null, Modifier.fillMaxWidth().aspectRatio(16 / 9f))
            Surface(color = Color.Black.copy(alpha = 0.6f), shape = RoundedCornerShape(12.dp), modifier = Modifier.align(Alignment.BottomStart).padding(8.dp)) {
                Row(Modifier.padding(horizontal = 8.dp, vertical = 2.dp), verticalAlignment = Alignment.CenterVertically) {
                    Icon(Icons.Filled.PlayArrow, null, tint = Color.White, modifier = Modifier.size(18.dp))
                    Text(Dates.clock(hit.start), color = Color.White, style = MaterialTheme.typography.labelLarge)
                }
            }
            ConfidenceBadge(hit, Modifier.align(Alignment.TopEnd).padding(8.dp))
        }
        Column(Modifier.padding(12.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
            Text(hit.sourceTitle, style = MaterialTheme.typography.titleSmall, fontWeight = FontWeight.SemiBold)
            Text(listOfNotNull(hit.account?.let { "@$it" }, hit.platform, hit.sourceKind?.replace('_', ' '), hit.video.title).joinToString(" · "),
                style = MaterialTheme.typography.labelMedium, color = MaterialTheme.colorScheme.onSurfaceVariant, maxLines = 2, overflow = TextOverflow.Ellipsis)
            Text(hit.reasonLabel, style = MaterialTheme.typography.labelLarge, color = MaterialTheme.colorScheme.primary)
            Text("“${hit.excerpt.text}”", style = MaterialTheme.typography.bodyLarge, fontStyle = FontStyle.Italic, modifier = Modifier.testTag("hit.excerpt"))
            hit.excerpt.en?.let { Text(it, style = MaterialTheme.typography.bodyMedium, modifier = Modifier.testTag("hit.translation")) }
            if (hit.notes.isNotEmpty()) Text(hit.notes.joinToString("; "), style = MaterialTheme.typography.labelSmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
            hit.suggestion?.let { sg ->
                Text("Suggested: ${sg.section.title}" + (sg.reason?.let { " - $it" } ?: ""), style = MaterialTheme.typography.labelMedium,
                    color = MaterialTheme.colorScheme.tertiary, modifier = Modifier.testTag("hit.suggestion"))
            }
            hit.judge?.reason?.let { Text("Judge: $it", style = MaterialTheme.typography.labelSmall, color = MaterialTheme.colorScheme.onSurfaceVariant) }
            Text(listOfNotNull(
                "at ${Dates.clock(hit.start)}" + (hit.end?.let { "–${Dates.clock(it)}" } ?: ""),
                Dates.parse(hit.video.postedAt)?.let { "posted ${Dates.medium(it)}" },
                Dates.parse(hit.foundAt)?.let { "found ${Dates.dateTime(it)}" },
            ).joinToString(" · "), style = MaterialTheme.typography.labelSmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp), verticalAlignment = Alignment.CenterVertically) {
                PublishButton(hit, onPublish, busy = busy)
                if (hit.isPublished) Text("In ${hit.homeSection.title}", style = MaterialTheme.typography.labelMedium, color = MaterialTheme.colorScheme.primary)
                (hit.atUrl ?: hit.video.url)?.let { url ->
                    IconButton(onClick = { runCatching { context.startActivity(android.content.Intent(android.content.Intent.ACTION_VIEW, android.net.Uri.parse(url))) } }) {
                        Icon(Icons.AutoMirrored.Filled.OpenInNew, "Open at the moment on ${hit.platform ?: "the platform"}")
                    }
                }
                Spacer(Modifier.weight(1f))
                FetchMoreButton(hit.platform, onFetchMore, label = "Fetch more")
            }
        }
    }
}

@Composable
fun ConfidenceBadge(hit: MonitorHit, modifier: Modifier = Modifier) {
    val pct = (hit.confidence * 100).toInt()
    val low = hit.isLowConfidence
    Surface(
        color = if (low) Color(0xFFB26A00) else MaterialTheme.colorScheme.primary,
        shape = RoundedCornerShape(12.dp),
        modifier = modifier.semantics { contentDescription = "Confidence $pct percent, ${hit.label}" }.testTag(if (low) "hit.low" else "hit.confidence"),
    ) {
        Column(Modifier.padding(horizontal = 8.dp, vertical = 4.dp), horizontalAlignment = Alignment.CenterHorizontally) {
            Text("$pct%", color = Color.White, fontWeight = FontWeight.Bold, style = MaterialTheme.typography.labelLarge)
            Text(hit.label, color = Color.White, style = MaterialTheme.typography.labelSmall)
            LinearProgressIndicator(progress = { hit.confidence.toFloat() }, color = Color.White, trackColor = Color.White.copy(alpha = 0.3f),
                modifier = Modifier.size(56.dp, 3.dp).clip(RoundedCornerShape(2.dp)))
        }
    }
}

/** One hit, from a link (`/monitor/<id>`). */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun HitScreen(id: String, api: MonitorApi, vm: MonitorViewModel) {
    val nav = LocalNav.current
    var hit by remember(id) { mutableStateOf<MonitorHit?>(null) }
    var error by remember(id) { mutableStateOf<Throwable?>(null) }
    val scope = rememberCoroutineScope()
    suspend fun load() { try { hit = api.hit(id); error = null } catch (e: Exception) { error = e } }
    LaunchedEffect(id, api) { load() }
    Column(Modifier.fillMaxSize()) {
        TopAppBar(title = { Text("Detected") }, navigationIcon = { IconButton(onClick = nav.back) { Icon(Icons.AutoMirrored.Filled.ArrowBack, "Back") } })
        val h = vm.hits.firstOrNull { it.id == id } ?: hit
        when {
            h != null -> Column(Modifier.verticalScroll(rememberScrollState())) {
                h.playable?.let { (url, at) -> VideoPlayer(url, h.poster, Modifier.fillMaxWidth().aspectRatio(16 / 9f), startAt = at, description = "Recording from ${h.sourceTitle}") }
                Box(Modifier.padding(16.dp)) { HitCard(h, h.id in vm.busy, onPlay = { nav.feed(FeedContext("Detected", listOf(FeedItem.Hit(h)))) }, onPublish = vm::publish, onFetchMore = vm::fetchMore) }
            }
            error != null -> Box(Modifier.padding(16.dp)) { ErrorBanner(error!!) { scope.launch { load() } } }
            else -> Box(Modifier.fillMaxSize(), contentAlignment = Alignment.Center) { CircularProgressIndicator() }
        }
    }
}
