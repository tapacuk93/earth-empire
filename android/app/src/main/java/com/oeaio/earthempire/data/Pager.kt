package com.oeaio.earthempire.data

/**
 * Cursor paging over `GET /v1/items` (`before` = the previous page's `next`): keeps the pages in
 * order, drops an item a later page repeats, stops at a null cursor, and never asks for the same
 * cursor twice. Not thread-safe; the UI calls it from one coroutine at a time.
 */
class Pager<T>(
    private val idOf: (T) -> String,
    private val fetch: suspend (cursor: String?) -> Pair<List<T>, String?>,
) {
    var items: List<T> = emptyList(); private set
    var next: String? = null; private set
    var started = false; private set
    var error: Throwable? = null; private set
    val isComplete get() = started && next == null
    private val seen = HashSet<String>()
    private val asked = HashSet<String?>()

    /** Loads the first page again, replacing everything. */
    suspend fun refresh() {
        val (page, cursor) = try { fetch(null) } catch (e: Throwable) { error = e; throw e }
        seen.clear(); asked.clear(); asked.add(null)
        items = page.filter { seen.add(idOf(it)) }
        next = cursor
        started = true
        error = null
    }

    /** Loads the next page; false when there is none (or it was already asked for). */
    suspend fun loadMore(): Boolean {
        if (!started) { refresh(); return true }
        val cursor = next ?: return false
        if (!asked.add(cursor)) return false
        val (page, newCursor) = try { fetch(cursor) } catch (e: Throwable) { asked.remove(cursor); error = e; throw e }
        items = items + page.filter { seen.add(idOf(it)) }
        next = newCursor?.takeIf { it != cursor }
        error = null
        return true
    }
}
