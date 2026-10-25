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
import com.oeaio.earthempire.data.Insights
import com.oeaio.earthempire.data.Item
import com.oeaio.earthempire.data.ItemQuery
import com.oeaio.earthempire.data.MonitorHit
import com.oeaio.earthempire.data.Pager
import com.oeaio.earthempire.data.TAG
import com.oeaio.earthempire.data.Tag
import kotlinx.coroutines.Job
import kotlinx.coroutines.async
import kotlinx.coroutines.coroutineScope
import kotlinx.coroutines.launch

/**
 * Home: everything published, as infographics. Loads the archive (up to [MAX_ITEMS], newest
 * first), the highlights, categories and tags, and the published monitor hits, and derives the
 * charts and section panels from them.
 */
class HomeViewModel(private val container: AppContainer) : ViewModel() {
    private var api: ArchiveApi = container.archive.value

    var highlights by mutableStateOf<List<Highlight>>(emptyList()); private set
    var categories by mutableStateOf<List<Category>>(emptyList()); private set
    var tags by mutableStateOf<List<Tag>>(emptyList()); private set
    var published by mutableStateOf<List<MonitorHit>>(emptyList()); private set
    var items by mutableStateOf<List<Item>>(emptyList()); private set
    var error by mutableStateOf<Throwable?>(null); private set
    var refreshing by mutableStateOf(false); private set
    var loaded by mutableStateOf(false); private set
    /** The search the infographics are narrowed to, or null for everything. */
    var query by mutableStateOf<String?>(null); private set

    var months by mutableStateOf<List<Insights.Month>>(emptyList()); private set
    var places by mutableStateOf<List<Insights.Place>>(emptyList()); private set
    var panels by mutableStateOf<List<Insights.Panel>>(emptyList()); private set

    val offline get() = api.offline
    val owner get() = container.owner
    private var job: Job? = null

    init {
        viewModelScope.launch { container.archive.collect { if (it !== api) { api = it; refresh() } } }
        refresh()
    }

    fun search(text: String?) {
        val q = text?.trim()?.ifEmpty { null }
        if (q == query) return
        query = q
        refresh()
    }

    fun refresh() {
        job?.cancel()
        job = viewModelScope.launch {
            refreshing = true
            try {
                coroutineScope {
                    val h = async { runCatching { api.highlights() } }
                    val c = async { runCatching { api.categories() } }
                    val t = async { runCatching { api.tags(limit = 300) } }
                    val p = async { runCatching { container.monitor.value.published(null, 50).hits } }
                    val all = async { loadItems() }
                    items = all.await()
                    highlights = h.await().getOrElse { highlights }
                    categories = c.await().getOrElse { categories }
                    tags = t.await().getOrElse { tags }
                    published = p.await().onFailure { Log.w(TAG, "published failed: $it") }.getOrElse { published }
                    h.await().exceptionOrNull()?.let { throw it }
                }
                error = null
            } catch (e: kotlinx.coroutines.CancellationException) { throw e
            } catch (e: Exception) { Log.e(TAG, "home failed", e); error = e
            } finally {
                derive(); refreshing = false; loaded = true
            }
        }
    }

    private suspend fun loadItems(): List<Item> {
        val pager = Pager<Item>({ it.id }) { c -> val p = api.items(ItemQuery(q = query), c, 100); p.items to p.next }
        pager.refresh()
        while (pager.items.size < MAX_ITEMS && pager.loadMore()) Unit
        return pager.items
    }

    private fun derive() {
        val hits = if (query == null) published else published.filter { h -> listOfNotNull(h.excerpt.text, h.excerpt.en, h.sourceTitle, h.video.title).any { it.contains(query!!, true) } }
        months = Insights.months(items, hits)
        places = Insights.places(items)
        panels = Insights.panels(items, highlights, hits)
    }

    /** Items with a tag, from the API (the loaded set may not hold them all). */
    suspend fun itemsWith(query: ItemQuery): List<Item> = runCatching { api.items(query, null, 100).items }.getOrElse { items.filter { com.oeaio.earthempire.data.SampleApi.matches(it, query) } }

    companion object { const val MAX_ITEMS = 600 }
}
