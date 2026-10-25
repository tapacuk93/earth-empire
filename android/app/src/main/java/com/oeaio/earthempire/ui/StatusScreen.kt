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
import androidx.compose.material.icons.automirrored.filled.ArrowBack
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
import androidx.compose.ui.semantics.heading
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

/** Status: the backend's health and activity, refreshed every few seconds. */
class StatusViewModel(val container: AppContainer) : ViewModel() {
    var report by mutableStateOf<StatusReport?>(null); private set
    var error by mutableStateOf<Throwable?>(null); private set
    var refreshing by mutableStateOf(false); private set
    var usingMock by mutableStateOf(false); private set
    val messages = SnackbarHostState()
    private var ticker: Job? = null

    suspend fun refresh() {
        try {
            report = container.monitor.value.status(); error = null; usingMock = container.monitor.value.isMock
        } catch (e: Exception) { Log.w(TAG, "status failed: $e"); error = e }
    }

    fun pull() { viewModelScope.launch { refreshing = true; refresh(); refreshing = false } }

    /** Polls while the screen is visible. */
    fun start() {
        if (ticker?.isActive == true) return
        ticker = viewModelScope.launch { while (isActive) { refresh(); delay(10_000) } }
    }
    fun stop() { ticker?.cancel() }
}

/** Settings: the phrases, the admin token, appearance and where the data comes from. */
class SettingsViewModel(val container: AppContainer) : ViewModel() {
    var phrases by mutableStateOf<List<Phrase>>(emptyList()); private set
    /** The editable texts; saved with [savePhrases]. */
    var draft by mutableStateOf<List<String>>(emptyList())
    var phrasesError by mutableStateOf<Throwable?>(null); private set
    var busy by mutableStateOf(false); private set
    val messages = SnackbarHostState()
    private var loaded = false

    init {
        viewModelScope.launch { container.owner.collect { if (it && !loaded) { loaded = true; loadPhrases() } } }
    }

    fun loadPhrases() {
        viewModelScope.launch {
            try { phrases = container.monitor.value.phrases(); draft = phrases.map { it.text }; phrasesError = null }
            catch (e: Exception) { Log.w(TAG, "phrases failed: $e"); phrasesError = e }
        }
    }

    fun savePhrases() {
        viewModelScope.launch {
            busy = true
            try {
                phrases = container.monitor.value.savePhrases(draft.map { it.trim() }.filter { it.isNotEmpty() }.distinct(), container.settings.adminToken)
                draft = phrases.map { it.text }
                messages.showSnackbar("Phrases saved; stored transcripts are matched again.")
            } catch (e: Exception) { messages.showSnackbar(refusal(e) ?: "Could not save: ${e.message}") } finally { busy = false }
        }
    }

    fun rescan() {
        viewModelScope.launch {
            busy = true
            try { val r = container.monitor.value.rescan(container.settings.adminToken); messages.showSnackbar("Rescanning ${r.videos} stored videos.") }
            catch (e: Exception) { messages.showSnackbar(refusal(e) ?: "Could not rescan: ${e.message}") } finally { busy = false }
        }
    }

    private fun refusal(e: Exception) = if (e is ApiException.Status && (e.code == 401 || e.code == 403)) "The admin token was refused." else null

    fun signOut() { container.signOut() }
    fun setSample(on: Boolean) { container.settings.useSample = on; container.reconfigure(); loadPhrases() }
    fun setApiBase(base: String) { container.settings.apiBase = base; container.reconfigure(); loadPhrases() }
}

private typealias BuildConfig = com.oeaio.earthempire.BuildConfig

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun StatusScreen(vm: StatusViewModel) {
    val nav = LocalNav.current
    val lifecycle = LocalLifecycleOwner.current.lifecycle
    DisposableEffect(lifecycle) {
        val obs = LifecycleEventObserver { _, e -> if (e == Lifecycle.Event.ON_RESUME) vm.start(); if (e == Lifecycle.Event.ON_PAUSE) vm.stop() }
        lifecycle.addObserver(obs)
        if (lifecycle.currentState.isAtLeast(Lifecycle.State.RESUMED)) vm.start()
        onDispose { lifecycle.removeObserver(obs); vm.stop() }
    }
    val list = rememberLazyListState()
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
                if (vm.usingMock) item("mock") { SampleBanner("Sample status (Settings → Data).") }
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
            }
        }
    }
}

@Composable
private fun Dot(state: String, size: Int, modifier: Modifier = Modifier) =
    Box(modifier.size(size.dp).background(statusColor(state), CircleShape).semantics { contentDescription = state })

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun SettingsScreen(vm: SettingsViewModel) {
    val s = vm.container.settings
    val theme by vm.container.theme.collectAsState()
    Column(Modifier.fillMaxSize()) {
        TopAppBar(title = { Text("Settings") })
        LazyColumn(contentPadding = PaddingValues(16.dp), verticalArrangement = Arrangement.spacedBy(14.dp), modifier = Modifier.fillMaxSize().testTag("settings")) {
            item { PhrasesEditor(vm) }
            item { HorizontalDivider() }
            item {
                Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                    Text("Owner", style = MaterialTheme.typography.titleSmall, modifier = Modifier.semantics { heading() })
                    Text("The admin token is saved on this device, never shown, and not backed up.", style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
                    OutlinedButton(onClick = vm::signOut, modifier = Modifier.testTag("settings.signout")) { Text("Forget the admin token") }
                }
            }
            item { HorizontalDivider() }
            item {
                Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                    Text("Appearance", style = MaterialTheme.typography.titleSmall, modifier = Modifier.semantics { heading() })
                    SingleChoiceSegmentedButtonRow(Modifier.fillMaxWidth().testTag("settings.theme")) {
                        listOf("system" to "System", "light" to "Light", "dark" to "Dark").forEachIndexed { i, (v, label) ->
                            SegmentedButton(selected = theme == v, onClick = { vm.container.setTheme(v) }, shape = SegmentedButtonDefaults.itemShape(i, 3)) { Text(label) }
                        }
                    }
                }
            }
            item { HorizontalDivider() }
            item {
                Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                    Text("Data", style = MaterialTheme.typography.titleSmall, modifier = Modifier.semantics { heading() })
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
        }
    }
}

/** The phrases the monitor listens for, each with its generated variants (read-only). */
@Composable
private fun PhrasesEditor(vm: SettingsViewModel) {
    Column(verticalArrangement = Arrangement.spacedBy(8.dp), modifier = Modifier.testTag("phrases")) {
        Text("Phrases to listen for", style = MaterialTheme.typography.titleSmall, modifier = Modifier.semantics { heading() })
        Text("Any grammatical form, transliteration or likely mishearing matches; the variants below are generated.",
            style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
        vm.phrasesError?.let { ErrorBanner(it) { vm.loadPhrases() } }
        vm.draft.forEachIndexed { i, text ->
            val variants = vm.phrases.firstOrNull { it.text == text }?.allVariants.orEmpty()
            Column(Modifier.testTag("phrase.$i")) {
                Row(verticalAlignment = Alignment.CenterVertically) {
                    OutlinedTextField(text, { v -> vm.draft = vm.draft.toMutableList().also { it[i] = v } }, singleLine = true,
                        modifier = Modifier.weight(1f), label = { Text("Phrase ${i + 1}") })
                    IconButton(onClick = { vm.draft = vm.draft.toMutableList().also { it.removeAt(i) } }) { Icon(Icons.Filled.Delete, "Remove $text") }
                }
                if (variants.isNotEmpty()) {
                    var all by remember { mutableStateOf(false) }
                    Text("Variants: " + variants.take(if (all) variants.size else 12).joinToString(", ") + if (!all && variants.size > 12) "…" else "",
                        style = MaterialTheme.typography.labelSmall, color = MaterialTheme.colorScheme.onSurfaceVariant,
                        modifier = Modifier.semantics { contentDescription = "${variants.size} variants of $text" }.testTag("phrase.variants"))
                    if (variants.size > 12) TextButton(onClick = { all = !all }) { Text(if (all) "Fewer" else "All ${variants.size} variants") }
                } else if (text.isNotBlank() && vm.phrases.none { it.text == text }) {
                    Text("Variants appear after saving.", style = MaterialTheme.typography.labelSmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
                }
            }
        }
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
    }
}

/**
 * The discreet way in for the owner: the admin token, checked with `GET /v1/admin/me` before it
 * is kept. Detected, Status and Settings appear once it is accepted.
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun OwnerSignInScreen(container: AppContainer, onDone: () -> Unit) {
    var token by remember { mutableStateOf("") }
    var checking by remember { mutableStateOf(false) }
    var problem by remember { mutableStateOf<String?>(null) }
    val scope = rememberCoroutineScope()
    fun submit() {
        checking = true; problem = null
        scope.launch {
            try { if (container.signIn(token)) onDone() else problem = "The backend refused this token." }
            catch (e: Exception) { problem = "Could not check the token: ${e.message}" }
            finally { checking = false }
        }
    }
    Column(Modifier.fillMaxSize()) {
        TopAppBar(title = { Text("Owner") }, navigationIcon = {
            IconButton(onClick = onDone) { Icon(Icons.AutoMirrored.Filled.ArrowBack, "Back") }
        })
        Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
            Text("Enter the admin token to see Detected, Status and Settings.", style = MaterialTheme.typography.bodyMedium)
            OutlinedTextField(token, { token = it }, label = { Text("Admin token") }, singleLine = true,
                visualTransformation = PasswordVisualTransformation(), isError = problem != null,
                supportingText = problem?.let { { Text(it) } }, modifier = Modifier.fillMaxWidth().testTag("owner.token"),
                keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Password, imeAction = ImeAction.Done),
                keyboardActions = KeyboardActions(onDone = { if (token.isNotBlank()) submit() }))
            Button(onClick = ::submit, enabled = token.isNotBlank() && !checking, modifier = Modifier.testTag("owner.submit")) { Text(if (checking) "Checking…" else "Continue") }
        }
    }
}
