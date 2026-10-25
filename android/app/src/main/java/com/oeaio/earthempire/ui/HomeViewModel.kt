package com.oeaio.earthempire.ui

import android.util.Log
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.oeaio.earthempire.AppContainer
import com.oeaio.earthempire.data.ArchiveApi
import com.oeaio.earthempire.data.Category
import com.oeaio.earthempire.data.Highlight
import com.oeaio.earthempire.data.Item
import com.oeaio.earthempire.data.ItemKind
import com.oeaio.earthempire.data.ItemQuery
import com.oeaio.earthempire.data.MonitorHit
import com.oeaio.earthempire.data.Pager
import com.oeaio.earthempire.data.Profile
import com.oeaio.earthempire.data.TAG
import com.oeaio.earthempire.data.Tag
import kotlinx.coroutines.Job
import kotlinx.coroutines.async
import kotlinx.coroutines.coroutineScope
import kotlinx.coroutines.launch

/** Home: the published finds and the Instagram archive, with its filters. */
class HomeViewModel(private val container: AppContainer) : ViewModel() {
    private var api: ArchiveApi = container.archive.value

    var profile by mutableStateOf<Profile?>(null); private set
    var highlights by mutableStateOf<List<Highlight>>(emptyList()); private set
    var categories by mutableStateOf<List<Category>>(emptyList()); private set
    var tags by mutableStateOf<List<Tag>>(emptyList()); private set
    var published by mutableStateOf<List<MonitorHit>>(emptyList()); private set
    var homeError by mutableStateOf<Throwable?>(null); private set

    var items by mutableStateOf<List<Item>>(emptyList()); private set
    var itemsError by mutableStateOf<Throwable?>(null); private set
    var loadingItems by mutableStateOf(false); private set
    var complete by mutableStateOf(false); private set
    var refreshing by mutableStateOf(false); private set

    var query by mutableStateOf(ItemQuery()); private set
    var view by mutableStateOf(container.settings.homeView); private set

    val offline get() = api.offline

    private var pager = makePager()
    private var pageJob: Job? = null

    init {
        viewModelScope.launch { container.archive.collect { if (it !== api) { api = it; reload() } } }
        refresh()
    }

    private fun makePager() = Pager<Item>({ it.id }) { cursor ->
        val page = api.items(query, cursor, 30); page.items to page.next
    }

    fun chooseView(v: String) {
        view = v; container.settings.homeView = v
        if (v == "timeline" && query.tag != null) applyQuery(query.copy(tag = null))
    }

    fun applyQuery(q: ItemQuery) {
        if (q == query) return
        query = q
        restartItems()
    }

    fun setKind(k: ItemKind?) = applyQuery(query.copy(kind = k))
    fun setCategory(c: String?) = applyQuery(query.copy(category = c))
    fun setTag(t: String?) = applyQuery(query.copy(tag = t).let { if (t != null && view != "tags") { view = "tags"; it } else it })
    fun search(text: String) = applyQuery(query.copy(q = text.trim().ifEmpty { null }))

    private fun reload() { profile = null; highlights = emptyList(); categories = emptyList(); tags = emptyList(); refresh() }

    fun refresh() {
        viewModelScope.launch {
            refreshing = true
            try {
                coroutineScope {
                    val home = async { loadHome() }
                    val pub = async { loadPublished() }
                    restartItems().join()
                    home.await(); pub.await()
                }
            } finally { refreshing = false }
        }
    }

    private suspend fun loadHome() {
        try {
            coroutineScope {
                val p = async { api.profile() }
                val h = async { api.highlights() }
                val c = async { api.categories() }
                profile = p.await(); highlights = h.await(); categories = c.await()
            }
            homeError = null
        } catch (e: Exception) {
            Log.e(TAG, "home failed", e); homeError = e
        }
        try { tags = api.tags(limit = 300) } catch (e: Exception) { Log.w(TAG, "tags failed: $e") }
    }

    private suspend fun loadPublished() {
        published = try { container.monitor.value.published(null, 20).items } catch (e: Exception) { Log.w(TAG, "published failed: $e"); published }
    }

    private fun restartItems(): Job {
        pageJob?.cancel()
        pager = makePager()
        val p = pager
        return viewModelScope.launch {
            loadingItems = true
            try { p.refresh(); if (p === pager) { items = p.items; complete = p.isComplete; itemsError = null } }
            catch (e: Exception) { if (p === pager) { itemsError = e; Log.w(TAG, "items failed: $e") } }
            finally { if (p === pager) loadingItems = false }
        }.also { pageJob = it }
    }

    fun loadMore() {
        if (loadingItems || complete) return
        val p = pager
        pageJob = viewModelScope.launch {
            loadingItems = true
            try { p.loadMore(); if (p === pager) { items = p.items; complete = p.isComplete } }
            catch (e: Exception) { if (p === pager) itemsError = e }
            finally { if (p === pager) loadingItems = false }
        }
    }
}
