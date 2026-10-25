package com.oeaio.earthempire.ui

import android.util.Log
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.lazy.itemsIndexed
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.text.KeyboardActions
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Delete
import androidx.compose.material.icons.filled.Lock
import androidx.compose.material.icons.filled.Slideshow
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.SegmentedButton
import androidx.compose.material3.SegmentedButtonDefaults
import androidx.compose.material3.SingleChoiceSegmentedButtonRow
import androidx.compose.material3.SnackbarHostState
import androidx.compose.material3.Switch
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.TopAppBar
import androidx.compose.material3.pulltorefresh.PullToRefreshBox
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.unit.dp
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.LifecycleEventObserver
import androidx.lifecycle.ViewModel
import androidx.lifecycle.compose.LocalLifecycleOwner
import androidx.lifecycle.viewModelScope
import com.oeaio.earthempire.AppContainer
import com.oeaio.earthempire.data.ApiException
import com.oeaio.earthempire.data.Dates
import com.oeaio.earthempire.data.Phrase
import com.oeaio.earthempire.data.StatusReport
import com.oeaio.earthempire.data.TAG
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch
import kotlinx.serialization.json.JsonPrimitive

/** Status: the backend's health and activity, refreshed every few seconds, and the settings. */
class StatusViewModel(val container: AppContainer) : ViewModel() {
    var report by mutableStateOf<StatusReport?>(null); private set
    var error by mutableStateOf<Throwable?>(null); private set
    var refreshing by mutableStateOf(false); private set
    var usingMock by mutableStateOf(false); private set

    var phrases by mutableStateOf<List<Phrase>>(emptyList()); private set
    /** The editable texts; saved with [savePhrases]. */
    var draft by mutableStateOf<List<String>>(emptyList())
    var phrasesMock by mutableStateOf(false); private set
    var busy by mutableStateOf(false); private set
    var hasToken by mutableStateOf(container.settings.adminToken.isNotBlank()); private set
    val messages = SnackbarHostState()
    private var ticker: Job? = null

    init { loadPhrases() }

    suspend fun refresh() {
        try {
            report = container.monitor.value.status(); error = null; usingMock = container.monitor.value is com.oeaio.earthempire.data.MockMonitorApi
        } catch (e: Exception) {
            Log.w(TAG, "status failed: $e")
            // Before the status endpoint is deployed, a development build shows the mock.
            if (e is ApiException.NotFound && BuildConfig.DEBUG) {
                report = com.oeaio.earthempire.data.MockMonitorApi(0).status(); usingMock = true; error = null
            } else error = e
        }
    }

    fun pull() { viewModelScope.launch { refreshing = true; refresh(); refreshing = false } }

    /** Polls while the screen is visible. */
    fun start() {
        if (ticker?.isActive == true) return
        ticker = viewModelScope.launch { while (isActive) { refresh(); delay(10_000) } }
    }
    fun stop() { ticker?.cancel() }

    fun loadPhrases() {
        viewModelScope.launch {
            try {
                phrases = container.monitor.value.phrases(); draft = phrases.map { it.text }
                phrasesMock = container.monitor.value.isMock
            } catch (e: Exception) { Log.w(TAG, "phrases failed: $e") }
        }
    }

    fun savePhrases() {
        val token = container.settings.adminToken
        if (token.isBlank()) return
        viewModelScope.launch {
            busy = true
            try {
                phrases = container.monitor.value.savePhrases(draft.map { it.trim() }.filter { it.isNotEmpty() }.distinct(), token)
                draft = phrases.map { it.text }
                messages.showSnackbar("Phrases saved.")
            } catch (e: Exception) { messages.showSnackbar(refusal(e) ?: "Could not save: ${e.message}") } finally { busy = false }
        }
    }

    fun rescan() {
        val token = container.settings.adminToken
        if (token.isBlank()) return
        viewModelScope.launch {
            busy = true
            try { messages.showSnackbar(container.monitor.value.rescan(token).message ?: "Rescanning existing videos.") }
            catch (e: Exception) { messages.showSnackbar(refusal(e) ?: "Could not rescan: ${e.message}") } finally { busy = false }
        }
    }

    private fun refusal(e: Exception) = if (e is ApiException.Status && (e.code == 401 || e.code == 403)) "The admin token was refused." else null

    /** Checks the token with `GET /v1/admin/me` and keeps it only if the backend accepts it. */
    fun setToken(token: String) {
        viewModelScope.launch {
            busy = true
            try {
                val ok = token.isBlank() || container.monitor.value.checkToken(token)
                if (ok) { container.settings.adminToken = token; hasToken = token.isNotBlank() }
                messages.showSnackbar(when { token.isBlank() -> "Admin token removed."; ok -> "Admin token accepted."; else -> "The backend refused this token." })
            } catch (e: Exception) { messages.showSnackbar("Could not check the token: ${e.message}") } finally { busy = false }
        }
    }

    fun setSample(on: Boolean) { container.settings.useSample = on; container.reconfigure(); loadPhrases(); pull() }
    fun setApiBase(base: String) { container.settings.apiBase = base; container.reconfigure(); loadPhrases(); pull() }
}

private typealias BuildConfig = com.oeaio.earthempire.BuildConfig

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun StatusScreen(vm: StatusViewModel, scrollToSettings: Boolean = false) {
    val nav = LocalNav.current
    val lifecycle = LocalLifecycleOwner.current.lifecycle
    DisposableEffect(lifecycle) {
        val obs = LifecycleEventObserver { _, e -> if (e == Lifecycle.Event.ON_RESUME) vm.start(); if (e == Lifecycle.Event.ON_PAUSE) vm.stop() }
        lifecycle.addObserver(obs)
        if (lifecycle.currentState.isAtLeast(Lifecycle.State.RESUMED)) vm.start()
        onDispose { lifecycle.removeObserver(obs); vm.stop() }
    }
    val list = rememberLazyListState()
    LaunchedEffect(scrollToSettings) { if (scrollToSettings) list.animateScrollToItem(list.layoutInfo.totalItemsCount.coerceAtLeast(1) - 1) }
    val scope = rememberCoroutineScope()
    val r = vm.report
    Column(Modifier.fillMaxSize()) {
        TopAppBar(
            title = { Text("Status") },
            actions = {
                IconButton(onClick = {
                    scope.launch {
                        val ids = (r?.activity?.jobs?.mapNotNull { it.item } ?: emptyList()) + (r?.activity?.events?.mapNotNull { it.item } ?: emptyList())
                        val entries = ids.distinct().mapNotNull { id ->
                            runCatching { vm.container.archive.value.item(id) }.getOrNull()?.let { item ->
                                item.allMedia.firstOrNull { it.isVideo }?.let { m -> FeedEntry(item.id, m.url, m.poster, item.summary ?: item.kind.label, detail = { nav.item(item.id) }) }
                            }
                        }
                        if (entries.isNotEmpty()) nav.feed(entries, 0) else vm.messages.showSnackbar("No videos in the recent activity.")
                    }
                }, modifier = Modifier.testTag("status.fullscreen")) { Icon(Icons.Filled.Slideshow, "Fullscreen videos from the activity") }
            },
        )
        PullToRefreshBox(isRefreshing = vm.refreshing, onRefresh = vm::pull, modifier = Modifier.fillMaxSize()) {
            LazyColumn(state = list, contentPadding = PaddingValues(16.dp), verticalArrangement = Arrangement.spacedBy(10.dp), modifier = Modifier.fillMaxSize().testTag("status.list")) {
                if (vm.usingMock) item("mock") { SampleBanner(if (vm.container.settings.useSample) "Sample status (sample data is on in Settings)." else "Sample status: /v1/status is not deployed yet.") }
                vm.error?.let { e -> item("error") { ErrorBanner(e) { vm.pull() } } }
                if (r != null) {
                    item("overall") {
                        Row(verticalAlignment = Alignment.CenterVertically, modifier = Modifier.semantics(mergeDescendants = true) {}.testTag("status.overall")) {
                            Dot(r.overall, 14)
                            Text("  Overall: ${r.overall}", style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.SemiBold)
                            Spacer(Modifier.weight(1f))
                            Dates.parse(r.generatedAt)?.let { Text(Dates.dateTime(it), style = MaterialTheme.typography.labelSmall, color = MaterialTheme.colorScheme.onSurfaceVariant) }
                        }
                    }
                    items(r.components, key = { "c:" + it.id }) { c ->
                        Card(Modifier.fillMaxWidth().semantics(mergeDescendants = true) {}.testTag("component.${c.id}")) {
                            Column(Modifier.padding(12.dp), verticalArrangement = Arrangement.spacedBy(2.dp)) {
                                Row(verticalAlignment = Alignment.CenterVertically) {
                                    Dot(c.state, 10)
                                    Text("  ${c.title}", fontWeight = FontWeight.SemiBold, modifier = Modifier.weight(1f))
                                    Text(c.state, style = MaterialTheme.typography.labelMedium, color = statusColor(c.state))
                                }
                                Dates.parse(c.lastSuccess)?.let { Text("Last success ${Dates.dateTime(it)}", style = MaterialTheme.typography.labelSmall) }
                                c.lastError?.let { e -> Text("Error: ${e.message ?: "?"}" + (Dates.parse(e.at)?.let { " (${Dates.dateTime(it)})" } ?: ""), style = MaterialTheme.typography.labelSmall, color = MaterialTheme.colorScheme.error) }
                                c.details?.takeIf { it.isNotEmpty() }?.let { d ->
                                    Text(d.entries.joinToString(" · ") { (k, v) -> "${k.replace('_', ' ')}: ${(v as? JsonPrimitive)?.content ?: v.toString()}" },
                                        style = MaterialTheme.typography.labelSmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
                                }
                            }
                        }
                    }
                    if (r.activity.jobs.isNotEmpty()) item("jobs.title") { SectionTitle("Working on") }
                    itemsIndexed(r.activity.jobs, key = { i, _ -> "j:$i" }) { _, j ->
                        Column(Modifier.fillMaxWidth().semantics(mergeDescendants = true) {}) {
                            Text("${j.component ?: ""}: ${j.what}", style = MaterialTheme.typography.bodyMedium)
                            j.fraction?.let { f -> LinearProgressIndicator(progress = { f }, modifier = Modifier.fillMaxWidth().padding(vertical = 4.dp)) }
                            Text(listOfNotNull(j.progressText, j.elapsedS?.let { "${Dates.clock(it)} elapsed" }).joinToString(" · "), style = MaterialTheme.typography.labelSmall)
                        }
                    }
                    if (r.activity.events.isNotEmpty()) item("events.title") { SectionTitle("Recent activity") }
                    itemsIndexed(r.activity.events, key = { i, _ -> "e:$i" }) { _, e ->
                        Row(
                            Modifier.fillMaxWidth().heightIn(min = 40.dp)
                                .let { m -> e.item?.let { id -> m.clickable(onClickLabel = "Open item") { nav.item(id) } } ?: m }
                                .semantics(mergeDescendants = true) {},
                            horizontalArrangement = Arrangement.spacedBy(8.dp),
                        ) {
                            Dot(if (e.ok) "ok" else "down", 8, Modifier.padding(top = 6.dp))
                            Column(Modifier.weight(1f)) {
                                Text(e.text, style = MaterialTheme.typography.bodySmall)
                                Text(listOfNotNull(e.component, Dates.parse(e.at)?.let(Dates::dateTime)).joinToString(" · "), style = MaterialTheme.typography.labelSmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
                            }
                        }
                    }
                }
                item { HorizontalDivider(Modifier.padding(vertical = 8.dp)) }
                item { SettingsSection(vm) }
            }
        }
    }
}

@Composable
private fun Dot(state: String, size: Int, modifier: Modifier = Modifier) =
    Box(modifier.size(size.dp).background(statusColor(state), CircleShape).semantics { contentDescription = state })

@Composable
fun SettingsSection(vm: StatusViewModel) {
    val s = vm.container.settings
    val theme by vm.container.theme.collectAsState()
    Column(verticalArrangement = Arrangement.spacedBy(14.dp), modifier = Modifier.testTag("settings")) {
        SectionTitle("Settings")
        PhrasesEditor(vm)
        HorizontalDivider()
        Text("Owner", style = MaterialTheme.typography.titleSmall)
        var token by remember { mutableStateOf("") }
        Text(if (vm.hasToken) "An admin token is saved on this device." else "Enter the owner's admin token once to add finds and edit phrases.",
            style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
        Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            OutlinedTextField(token, { token = it }, label = { Text("Admin token") }, singleLine = true,
                visualTransformation = PasswordVisualTransformation(), modifier = Modifier.weight(1f).testTag("settings.token"),
                keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Password, imeAction = ImeAction.Done),
                keyboardActions = KeyboardActions(onDone = { vm.setToken(token); token = "" }))
            Button(onClick = { vm.setToken(token); token = "" }, enabled = token.isNotBlank() && !vm.busy) { Text("Save") }
        }
        if (vm.hasToken) TextButton(onClick = { vm.setToken("") }) { Text("Forget the admin token") }
        HorizontalDivider()
        Text("Appearance", style = MaterialTheme.typography.titleSmall)
        SingleChoiceSegmentedButtonRow(Modifier.fillMaxWidth().testTag("settings.theme")) {
            listOf("system" to "System", "light" to "Light", "dark" to "Dark").forEachIndexed { i, (v, label) ->
                SegmentedButton(selected = theme == v, onClick = { vm.container.setTheme(v) }, shape = SegmentedButtonDefaults.itemShape(i, 3)) { Text(label) }
            }
        }
        HorizontalDivider()
        Text("Data", style = MaterialTheme.typography.titleSmall)
        var base by remember { mutableStateOf(s.apiBase) }
        OutlinedTextField(base, { base = it }, label = { Text("API address") }, singleLine = true, modifier = Modifier.fillMaxWidth(),
            keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Uri, imeAction = ImeAction.Done),
            keyboardActions = KeyboardActions(onDone = { vm.setApiBase(base) }))
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            OutlinedButton(onClick = { vm.setApiBase(base) }) { Text("Use this address") }
            TextButton(onClick = { base = BuildConfig.API_BASE; vm.setApiBase("") }) { Text("Default") }
        }
        var sample by remember { mutableStateOf(s.useSample) }
        Row(verticalAlignment = Alignment.CenterVertically) {
            Text("Sample data instead of the API", modifier = Modifier.weight(1f))
            Switch(sample, { sample = it; vm.setSample(it) }, modifier = Modifier.testTag("settings.sample"))
        }
        Text("Earth Empire ${BuildConfig.VERSION_NAME} · open source (MIT): github.com/tapacuk93/earth-empire", style = MaterialTheme.typography.labelSmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
    }
}

/** The phrases the monitor listens for; read-only without the admin token. */
@Composable
private fun PhrasesEditor(vm: StatusViewModel) {
    val editable = vm.hasToken
    Column(verticalArrangement = Arrangement.spacedBy(8.dp), modifier = Modifier.testTag("phrases")) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Text("Phrases to listen for", style = MaterialTheme.typography.titleSmall, modifier = Modifier.weight(1f))
            if (!editable) Icon(Icons.Filled.Lock, "Read-only: needs the admin token", Modifier.size(18.dp), tint = MaterialTheme.colorScheme.onSurfaceVariant)
        }
        if (vm.phrasesMock) Text("Sample list: the phrases endpoint is not live yet.", style = MaterialTheme.typography.labelSmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
        vm.draft.forEachIndexed { i, text ->
            val variants = vm.phrases.firstOrNull { it.text == text }?.variants.orEmpty()
            Column(Modifier.testTag("phrase.$i")) {
                if (editable) {
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        OutlinedTextField(text, { v -> vm.draft = vm.draft.toMutableList().also { it[i] = v } }, singleLine = true,
                            modifier = Modifier.weight(1f), label = { Text("Phrase ${i + 1}") })
                        IconButton(onClick = { vm.draft = vm.draft.toMutableList().also { it.removeAt(i) } }) { Icon(Icons.Filled.Delete, "Remove $text") }
                    }
                } else Text(text, style = MaterialTheme.typography.bodyLarge, fontWeight = FontWeight.SemiBold)
                if (variants.isNotEmpty()) Text("Also: " + variants.joinToString(", "), style = MaterialTheme.typography.labelSmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant, modifier = Modifier.semantics { contentDescription = "Variants of $text: ${variants.joinToString(", ")}" })
            }
        }
        if (editable) {
            var added by remember { mutableStateOf("") }
            Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                OutlinedTextField(added, { added = it }, singleLine = true, label = { Text("New phrase") }, modifier = Modifier.weight(1f).testTag("phrase.new"),
                    keyboardOptions = KeyboardOptions(imeAction = ImeAction.Done),
                    keyboardActions = KeyboardActions(onDone = { if (added.isNotBlank()) { vm.draft = vm.draft + added.trim(); added = "" } }))
                OutlinedButton(onClick = { vm.draft = vm.draft + added.trim(); added = "" }, enabled = added.isNotBlank()) { Text("Add") }
            }
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                Button(onClick = vm::savePhrases, enabled = !vm.busy && vm.draft != vm.phrases.map { it.text }, modifier = Modifier.testTag("phrases.save")) { Text("Save") }
                OutlinedButton(onClick = vm::rescan, enabled = !vm.busy, modifier = Modifier.testTag("phrases.rescan")) { Text("Rescan existing videos") }
            }
        } else {
            Text("Enter the admin token below to edit.", style = MaterialTheme.typography.labelSmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
        }
    }
}
