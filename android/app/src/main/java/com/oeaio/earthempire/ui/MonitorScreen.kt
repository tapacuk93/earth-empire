package com.oeaio.earthempire.ui

import android.util.Log
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
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
import androidx.compose.material.icons.filled.Add
import androidx.compose.material.icons.filled.CheckCircle
import androidx.compose.material.icons.filled.PlayArrow
import androidx.compose.material.icons.filled.Slideshow
import androidx.compose.material.icons.filled.Sync
import androidx.compose.material3.Button
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
import kotlinx.coroutines.launch

/** Monitor: flagged videos, highest confidence first. */
class MonitorViewModel(private val container: AppContainer) : ViewModel() {
    private var api: MonitorApi = container.monitor.value
    var hits by mutableStateOf<List<MonitorHit>>(emptyList()); private set
    var error by mutableStateOf<Throwable?>(null); private set
    var loading by mutableStateOf(false); private set
    var refreshing by mutableStateOf(false); private set
    var complete by mutableStateOf(false); private set
    var isMock by mutableStateOf(api.isMock); private set
    /** Ids being added right now. */
    var adding by mutableStateOf<Set<String>>(emptySet()); private set
    val messages = SnackbarHostState()
    private var pager = makePager()

    private fun makePager() = Pager<MonitorHit>({ it.id }) { c -> val p = api.hits(c, 30); p.hits to p.next }

    init {
        viewModelScope.launch { container.monitor.collect { if (it !== api) { api = it; refresh() } } }
        refresh()
    }

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
        if (loading || complete) return
        val p = pager
        viewModelScope.launch {
            loading = true
            try { p.loadMore(); if (p === pager) { hits = sorted(p.items); complete = p.isComplete } }
            catch (e: Exception) { error = e }
            finally { loading = false }
        }
    }

    /** The backend sorts by confidence; keep that order whatever page an item came on. */
    private fun sorted(list: List<MonitorHit>) = list.sortedByDescending { it.confidence }

    fun add(hit: MonitorHit) {
        val token = container.settings.adminToken
        if (token.isBlank()) {
            viewModelScope.launch { messages.showSnackbar("Adding needs the owner's admin token: enter it under Status → Settings.") }
            return
        }
        adding = adding + hit.id
        viewModelScope.launch {
            try {
                val updated = api.add(hit.id, token)
                hits = hits.map { if (it.id == hit.id) updated.copy(status = "added") else it }
                messages.showSnackbar("Added to Home and the site.")
            } catch (e: Exception) {
                val msg = if (e is ApiException.Status && (e.code == 401 || e.code == 403)) "The admin token was refused." else e.message ?: "Could not add."
                messages.showSnackbar(msg)
            } finally { adding = adding - hit.id }
        }
    }

    fun fetchMore(count: Int, source: String?) {
        viewModelScope.launch {
            try {
                val r = api.fetchMore(count, source)
                messages.showSnackbar(r.message ?: "Scanning $count more videos.")
                refresh()
            } catch (e: Exception) { messages.showSnackbar(e.message ?: "Could not ask for more.") }
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
        val entries = vm.hits.mapNotNull { it.feedEntry(nav) }
        if (entries.isNotEmpty()) nav.feed(entries, start?.let { s -> entries.indexOfFirst { it.id == s.id } }?.coerceAtLeast(0) ?: 0)
    }
    Column(Modifier.fillMaxSize()) {
        TopAppBar(
            title = { Text("Monitor") },
            actions = {
                FetchMoreButton(null, vm::fetchMore, compact = true)
                IconButton(onClick = { feed(null) }, modifier = Modifier.testTag("monitor.fullscreen")) { Icon(Icons.Filled.Slideshow, "Fullscreen videos") }
            },
        )
        PullToRefreshBox(isRefreshing = vm.refreshing, onRefresh = vm::refresh, modifier = Modifier.fillMaxSize()) {
            LazyColumn(state = list, contentPadding = PaddingValues(16.dp), verticalArrangement = Arrangement.spacedBy(12.dp), modifier = Modifier.fillMaxSize().testTag("monitor.list")) {
                if (vm.isMock) item("mock") { SampleBanner("Sample data: the monitor endpoints are not live yet.") }
                item("intro") {
                    Text("Videos from official government and world-organization accounts where a name close to “Тарас” is heard, or Ukrainian/Russian speech where none is expected. Highest confidence first.",
                        style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
                }
                vm.error?.let { e -> item("error") { ErrorBanner(e) { vm.refresh() } } }
                items(vm.hits, key = { it.id }) { hit ->
                    HitCard(hit, adding = hit.id in vm.adding, onPlay = { feed(hit) }, onAdd = { vm.add(hit) }, onFetchMore = vm::fetchMore)
                }
                item("footer") {
                    Box(Modifier.fillMaxWidth().padding(8.dp), contentAlignment = Alignment.Center) {
                        when {
                            vm.loading && !vm.refreshing -> CircularProgressIndicator(Modifier.size(28.dp))
                            vm.complete && vm.hits.isEmpty() -> Text("Nothing flagged yet.")
                            vm.complete -> FetchMoreButton(null, vm::fetchMore)
                        }
                    }
                }
            }
        }
    }
}

/** "Fetch N more": asks the backend to scan N more videos (of one account, or of all). */
@Composable
fun FetchMoreButton(source: String?, onFetch: (Int, String?) -> Unit, compact: Boolean = false, label: String = "Fetch more") {
    var open by remember { mutableStateOf(false) }
    Box {
        if (compact) IconButton(onClick = { open = true }, modifier = Modifier.testTag("fetch.more.all")) { Icon(Icons.Filled.Sync, "Fetch more videos") }
        else OutlinedButton(onClick = { open = true }, modifier = Modifier.testTag(if (source == null) "fetch.more.footer" else "fetch.more.$source")) { Text(label) }
        DropdownMenu(open, onDismissRequest = { open = false }) {
            listOf(5, 10, 25, 50).forEach { n ->
                DropdownMenuItem(text = { Text("Fetch $n more") }, onClick = { open = false; onFetch(n, source) })
            }
        }
    }
}

@Composable
fun HitCard(hit: MonitorHit, adding: Boolean, onPlay: () -> Unit, onAdd: () -> Unit, onFetchMore: (Int, String?) -> Unit) {
    ElevatedCard(Modifier.fillMaxWidth().testTag("hit.${hit.id}")) {
        Box(Modifier.clickable(onClickLabel = "Play from ${Dates.clock(hit.at)}", onClick = onPlay)) {
            RemoteImage(hit.video.poster, null, Modifier.fillMaxWidth().aspectRatio(16 / 9f))
            Surface(color = Color.Black.copy(alpha = 0.6f), shape = RoundedCornerShape(12.dp), modifier = Modifier.align(Alignment.BottomStart).padding(8.dp)) {
                Row(Modifier.padding(horizontal = 8.dp, vertical = 2.dp), verticalAlignment = Alignment.CenterVertically) {
                    Icon(Icons.Filled.PlayArrow, null, tint = Color.White, modifier = Modifier.size(18.dp))
                    Text(Dates.clock(hit.at), color = Color.White, style = MaterialTheme.typography.labelLarge)
                }
            }
            ConfidenceBadge(hit, Modifier.align(Alignment.TopEnd).padding(8.dp))
        }
        Column(Modifier.padding(12.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
            Text(hit.source.name ?: "@${hit.source.account}", style = MaterialTheme.typography.titleSmall, fontWeight = FontWeight.SemiBold)
            Text(listOfNotNull("@${hit.source.account}", hit.source.platform, hit.source.kind?.replace('-', ' '), hit.video.title).joinToString(" · "),
                style = MaterialTheme.typography.labelMedium, color = MaterialTheme.colorScheme.onSurfaceVariant, maxLines = 2, overflow = TextOverflow.Ellipsis)
            Text(hit.reasonLabel, style = MaterialTheme.typography.labelLarge, color = MaterialTheme.colorScheme.primary)
            Text("“${hit.excerpt}”", style = MaterialTheme.typography.bodyLarge, fontStyle = FontStyle.Italic, modifier = Modifier.testTag("hit.excerpt"))
            hit.translation?.let { Text(it, style = MaterialTheme.typography.bodyMedium, modifier = Modifier.testTag("hit.translation")) }
            Text(listOfNotNull(
                "at ${Dates.clock(hit.at)}" + (hit.to?.let { "–${Dates.clock(it)}" } ?: ""),
                Dates.parse(hit.video.publishedAt)?.let { "posted ${Dates.medium(it)}" },
                Dates.parse(hit.detectedAt)?.let { "found ${Dates.dateTime(it)}" },
            ).joinToString(" · "), style = MaterialTheme.typography.labelSmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp), verticalAlignment = Alignment.CenterVertically) {
                if (hit.isAdded) {
                    Row(verticalAlignment = Alignment.CenterVertically, modifier = Modifier.semantics(mergeDescendants = true) {}.testTag("hit.added")) {
                        Icon(Icons.Filled.CheckCircle, null, tint = MaterialTheme.colorScheme.primary, modifier = Modifier.size(20.dp))
                        Text(" On Home", color = MaterialTheme.colorScheme.primary, style = MaterialTheme.typography.labelLarge)
                    }
                } else {
                    Button(onClick = onAdd, enabled = !adding, modifier = Modifier.testTag("hit.add")) {
                        if (adding) CircularProgressIndicator(Modifier.size(16.dp), strokeWidth = 2.dp) else Icon(Icons.Filled.Add, null, Modifier.size(18.dp))
                        Text(" Add")
                    }
                }
                FetchMoreButton(hit.source.id.ifEmpty { null }, onFetchMore, label = "Fetch more from @${hit.source.account}")
            }
        }
    }
}

@Composable
fun ConfidenceBadge(hit: MonitorHit, modifier: Modifier = Modifier) {
    val pct = (hit.confidence * 100).toInt()
    val low = hit.isLowConfidence
    Surface(
        color = if (low) Color(0xFFE0A100) else MaterialTheme.colorScheme.primary,
        shape = RoundedCornerShape(12.dp),
        modifier = modifier.semantics { contentDescription = "Confidence $pct percent" + if (low) ", low confidence" else "" }.testTag(if (low) "hit.low" else "hit.confidence"),
    ) {
        Column(Modifier.padding(horizontal = 8.dp, vertical = 4.dp), horizontalAlignment = Alignment.CenterHorizontally) {
            Text("$pct%", color = Color.White, fontWeight = FontWeight.Bold, style = MaterialTheme.typography.labelLarge)
            if (low) Text("Low confidence", color = Color.White, style = MaterialTheme.typography.labelSmall)
            LinearProgressIndicator(progress = { hit.confidence.toFloat() }, color = Color.White, trackColor = Color.White.copy(alpha = 0.3f),
                modifier = Modifier.size(56.dp, 3.dp).clip(RoundedCornerShape(2.dp)))
        }
    }
}

/** One hit, from a link (`/monitor/<id>`): the video from the moment it was heard. */
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
        TopAppBar(title = { Text("Found video") }, navigationIcon = { IconButton(onClick = nav.back) { Icon(Icons.AutoMirrored.Filled.ArrowBack, "Back") } })
        val h = vm.hits.firstOrNull { it.id == id } ?: hit
        when {
            h != null -> Column(Modifier.verticalScroll(rememberScrollState())) {
                h.video.url?.let { VideoPlayer(it, h.video.poster, Modifier.fillMaxWidth().aspectRatio(16 / 9f), startAt = h.at, description = "Video from ${h.source.name ?: h.source.account}") }
                Box(Modifier.padding(16.dp)) { HitCard(h, h.id in vm.adding, onPlay = { h.feedEntry(nav)?.let { nav.feed(listOf(it), 0) } }, onAdd = { vm.add(h) }, onFetchMore = vm::fetchMore) }
                h.video.sourceUrl?.let { Box(Modifier.padding(horizontal = 16.dp)) { OpenLink("Open the original", it) } }
            }
            error != null -> Box(Modifier.padding(16.dp)) { ErrorBanner(error!!) { scope.launch { load() } } }
            else -> Box(Modifier.fillMaxSize(), contentAlignment = Alignment.Center) { CircularProgressIndicator() }
        }
    }
}
