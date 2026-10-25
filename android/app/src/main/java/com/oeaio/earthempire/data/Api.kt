package com.oeaio.earthempire.data

import android.util.Log
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.suspendCancellableCoroutine
import kotlinx.coroutines.withContext
import kotlinx.serialization.DeserializationStrategy
import okhttp3.Call
import okhttp3.Callback
import okhttp3.HttpUrl
import okhttp3.HttpUrl.Companion.toHttpUrl
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.Response
import java.io.File
import java.io.IOException
import java.security.MessageDigest
import kotlin.coroutines.resume
import kotlin.coroutines.resumeWithException

const val TAG = "EarthEmpire"

/** The public read API of CONTRACT.md ("The API"). */
interface ArchiveApi {
    suspend fun profile(): Profile
    suspend fun items(query: ItemQuery, before: String?, limit: Int = 30): ItemPage
    suspend fun item(id: String): Item
    suspend fun highlights(): List<Highlight>
    suspend fun categories(): List<Category>
    suspend fun tags(kind: String? = null, limit: Int = 300): List<Tag>
    /** True while answers come from the offline copy because the network failed. */
    val offline: StateFlow<Boolean>
}

sealed class ApiException(message: String) : IOException(message) {
    class Status(val code: Int, val path: String) : ApiException("The archive answered $code for $path.")
    class NotFound(val what: String) : ApiException("$what is not in the archive.")
}

/**
 * Keeps the last good answer to every GET, and each item seen, on disk, so the app opens offline
 * with what it showed last.
 */
class OfflineStore(private val root: File) {
    private val responses = File(root, "responses").apply { mkdirs() }
    private val items = File(root, "items").apply { mkdirs() }

    private fun key(s: String) = MessageDigest.getInstance("SHA-256").digest(s.toByteArray()).joinToString("") { "%02x".format(it) }

    fun store(url: String, body: String) = runCatching { File(responses, key(url) + ".json").writeText(body) }.let { }
    fun load(url: String): String? = File(responses, key(url) + ".json").takeIf { it.exists() }?.readText()

    fun store(item: Item) = runCatching { File(items, key(item.id) + ".json").writeText(ContractJson.encodeToString(Item.serializer(), item)) }.let { }
    fun item(id: String): Item? = runCatching {
        File(items, key(id) + ".json").takeIf { it.exists() }?.readText()?.let { ContractJson.decodeFromString(Item.serializer(), it) }
    }.getOrNull()

    fun clear() { root.deleteRecursively(); responses.mkdirs(); items.mkdirs() }
}

class LiveApi(
    base: String,
    private val client: OkHttpClient,
    private val store: OfflineStore?,
) : ArchiveApi {
    private val base: HttpUrl = base.trimEnd('/').toHttpUrl()
    private val _offline = MutableStateFlow(false)
    override val offline: StateFlow<Boolean> = _offline

    fun url(path: String, query: List<Pair<String, String>> = emptyList()): HttpUrl =
        base.newBuilder().apply {
            path.trim('/').split('/').forEach { addPathSegment(it) }
            query.forEach { (k, v) -> addQueryParameter(k, v) }
        }.build()

    private suspend fun <T> get(path: String, de: DeserializationStrategy<T>, query: List<Pair<String, String>> = emptyList()): T {
        val url = url(path, query)
        val body = try {
            val text = withContext(Dispatchers.IO) {
                client.newCall(Request.Builder().url(url).header("Accept", "application/json").build()).await().use { r ->
                    if (r.code == 404) throw ApiException.NotFound(path)
                    if (!r.isSuccessful) throw ApiException.Status(r.code, path)
                    r.body!!.string()
                }
            }
            store?.store(url.toString(), text)
            _offline.value = false
            text
        } catch (e: ApiException) {
            throw e
        } catch (e: IOException) {
            Log.w(TAG, "GET $url failed: $e")
            val cached = store?.load(url.toString()) ?: throw e
            _offline.value = true
            cached
        }
        return ContractJson.decodeFromString(de, body)
    }

    override suspend fun profile() = get("v1/profile", Profile.serializer())

    override suspend fun items(query: ItemQuery, before: String?, limit: Int): ItemPage {
        val params = query.params() + listOfNotNull(before?.let { "before" to it }, "limit" to limit.toString())
        val page = get("v1/items", ItemPage.serializer(), params)
        store?.let { s -> page.items.forEach(s::store) }
        return page
    }

    override suspend fun item(id: String): Item = try {
        get("v1/items/$id", Item.serializer()).also { store?.store(it) }
    } catch (e: IOException) {
        if (e is ApiException) throw e
        store?.item(id)?.also { _offline.value = true } ?: throw e
    }

    override suspend fun highlights() = get("v1/highlights", HighlightList.serializer()).highlights
    override suspend fun categories() = get("v1/categories", CategoryList.serializer()).categories
    override suspend fun tags(kind: String?, limit: Int) =
        get("v1/tags", TagList.serializer(), listOfNotNull(kind?.let { "kind" to it }, "limit" to limit.toString())).tags
}

suspend fun Call.await(): Response = suspendCancellableCoroutine { cont ->
    enqueue(object : Callback {
        override fun onFailure(call: Call, e: IOException) { if (!cont.isCancelled) cont.resumeWithException(e) }
        override fun onResponse(call: Call, response: Response) = cont.resume(response)
    })
    cont.invokeOnCancellation { runCatching { cancel() } }
}

/**
 * The bundled fixture (`assets/fixture/fixture.json`, the iOS app's), answering like the API, for
 * sample mode, previews and tests. Its media URLs point at media.empire.earth; [MediaUrls] maps
 * them to the bundled files.
 */
class SampleApi(val fixture: Fixture, private val latencyMs: Long = 0) : ArchiveApi {
    override val offline: StateFlow<Boolean> = MutableStateFlow(false)
    private suspend fun wait() { if (latencyMs > 0) delay(latencyMs) }

    override suspend fun profile() = fixture.profile.also { wait() }
    override suspend fun highlights() = fixture.highlights.also { wait() }
    override suspend fun categories() = fixture.categories.also { wait() }
    override suspend fun tags(kind: String?, limit: Int) = TagIndex.cloud(fixture.items).filter { kind == null || it.kind == kind }.take(limit).also { wait() }
    override suspend fun item(id: String): Item { wait(); return fixture.items.firstOrNull { it.id == id } ?: throw ApiException.NotFound(id) }
    override suspend fun items(query: ItemQuery, before: String?, limit: Int): ItemPage { wait(); return page(fixture.items, query, before, limit) }

    companion object {
        fun decode(json: String) = SampleApi(ContractJson.decodeFromString(Fixture.serializer(), json))

        /** Newest first; the cursor is the last item's id. */
        fun page(all: List<Item>, query: ItemQuery, before: String?, limit: Int): ItemPage {
            val sorted = all.filter { matches(it, query) }.sortedByDescending { Dates.parse(it.takenAt) }
            val start = before?.let { c -> sorted.indexOfFirst { it.id == c } + 1 } ?: 0
            val page = sorted.drop(start).take(limit)
            val next = if (start + page.size < sorted.size) page.lastOrNull()?.id else null
            return ItemPage(page, next)
        }

        fun matches(item: Item, q: ItemQuery): Boolean {
            if (q.kind != null && item.kind != q.kind) return false
            if (!q.category.isNullOrEmpty() && q.category !in item.categories) return false
            if (!q.highlight.isNullOrEmpty() && item.highlights.none { it.id == q.highlight }) return false
            if (!q.tag.isNullOrEmpty() && TagIndex.tags(item).none { it.first.equals(q.tag, ignoreCase = true) }) return false
            val text = q.q?.trim()?.lowercase()
            if (!text.isNullOrEmpty()) {
                val hay = listOfNotNull(item.caption, item.summary, item.description, item.location?.name,
                    item.analysis?.what, item.analysis?.context, item.analysis?.speech?.transcript,
                    item.repostOf?.caption, item.repostOf?.author) + item.hashtags + item.highlights.mapNotNull { it.title } +
                    (item.analysis?.keywords ?: emptyList())
                if (hay.none { it.lowercase().contains(text) }) return false
            }
            return true
        }
    }
}

/** Media URLs as the app loads them: in sample mode, the bundled copy of a fixture file. */
object MediaUrls {
    const val HOST = "media.empire.earth"
    @Volatile var sampleKeys: Set<String> = emptySet()

    fun resolve(url: String?): String? {
        url ?: return null
        val marker = "://$HOST/"
        val i = url.indexOf(marker)
        if (i < 0) return url
        val key = url.substring(i + marker.length)
        // The mock monitor's videos are the fixture's, under a prefix no real key has.
        if (key.startsWith("sample/")) return "file:///android_asset/fixture/media/" + key.removePrefix("sample/")
        return if (key in sampleKeys) "file:///android_asset/fixture/media/$key" else url
    }

    /** The same for ExoPlayer, which reads bundled files as `asset:///`. */
    fun resolveForPlayer(url: String): String =
        resolve(url)!!.replace("file:///android_asset/", "asset:///")
}
