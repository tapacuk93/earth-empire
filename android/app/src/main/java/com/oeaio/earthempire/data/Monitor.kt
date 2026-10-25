package com.oeaio.earthempire.data

import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.delay
import kotlinx.coroutines.withContext
import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.doubleOrNull
import okhttp3.HttpUrl
import okhttp3.HttpUrl.Companion.toHttpUrl
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import java.io.IOException

// Monitor, Published and Status: videos from official government and world-organization accounts
// in which a name close to "Тарас" is heard, or Ukrainian/Russian speech where none is expected.
//
// CONTRACT.md does not define these shapes yet; the ones below are the app's proposal (written
// up in android/README.md) and every field is optional, so the final contract can rename or drop
// fields without breaking decoding. Until the endpoints answer, the app uses [MockMonitorApi].

@Serializable
data class MonitorSource(
    val id: String = "",
    val account: String = "",               // the handle, without @
    val name: String? = null,               // "Ministry of …"
    val platform: String? = null,           // youtube | x | facebook | instagram | telegram | web
    val kind: String? = null,               // government | world-organization
    val country: String? = null,
    val url: String? = null,
)

@Serializable
data class MonitorVideo(
    val id: String = "",
    val title: String? = null,
    val url: String? = null,                 // a playable file, re-hosted on media.empire.earth
    @SerialName("source_url") val sourceUrl: String? = null,
    val thumbnail: String? = null,
    val cover: String? = null,
    val duration: Double? = null,
    @SerialName("published_at") val publishedAt: String? = null,
    val language: String? = null,           // the language the account normally speaks
) {
    val poster get() = cover ?: thumbnail
}

@Serializable
data class MonitorHit(
    val id: String,
    val reason: String = "name",            // name | language
    val matched: String? = null,            // what was heard, e.g. "Тарасе"
    val language: String? = null,           // of the excerpt: uk | ru | …
    val excerpt: String = "",               // the words as spoken
    val translation: String? = null,        // into English
    val confidence: Double = 0.0,           // 0…1
    val at: Double = 0.0,                   // seconds into the video
    val to: Double? = null,
    @SerialName("detected_at") val detectedAt: String? = null,
    val status: String = "new",             // new | added
    @SerialName("low_confidence") val lowConfidenceFlag: Boolean? = null,
    val video: MonitorVideo = MonitorVideo(),
    val source: MonitorSource = MonitorSource(),
    val extra: JsonObject? = null,
) {
    /** The backend's flag when it sends one, else below [LOW_CONFIDENCE]. */
    val isLowConfidence get() = lowConfidenceFlag ?: (confidence < LOW_CONFIDENCE)
    val isAdded get() = status == "added"
    val reasonLabel get() = if (reason == "language") "Unexpected ${languageName(language)} speech" else "Name heard: “${matched ?: "Тарас"}”"

    companion object {
        const val LOW_CONFIDENCE = 0.6
        fun languageName(code: String?) = when (code?.lowercase()) {
            "uk", "ukr", "ukrainian" -> "Ukrainian"
            "ru", "rus", "russian" -> "Russian"
            "en" -> "English"
            null, "" -> "Ukrainian/Russian"
            else -> code
        }
    }
}

@Serializable
data class MonitorPage(val hits: List<MonitorHit> = emptyList(), val next: String? = null)

/** A hit the owner added: shown on Home and the site. */
@Serializable
data class PublishedPage(val items: List<MonitorHit> = emptyList(), val next: String? = null)

@Serializable
data class FetchResult(val queued: Int = 0, val message: String? = null)

// CONTRACT.md "Status": GET /v1/status.
@Serializable
data class StatusReport(
    @SerialName("generated_at") val generatedAt: String? = null,
    val overall: String = "unknown",        // ok | degraded | down
    val components: List<ComponentStatus> = emptyList(),
    val activity: StatusActivity = StatusActivity(),
)

@Serializable
data class ComponentStatus(
    val id: String = "",
    val name: String? = null,
    val state: String = "unknown",          // ok | degraded | down | off
    @SerialName("last_success") val lastSuccess: String? = null,
    @SerialName("last_error") val lastError: StatusError? = null,
    val details: JsonObject? = null,
) {
    val title get() = name ?: id
}

@Serializable
data class StatusError(val at: String? = null, val message: String? = null)

@Serializable
data class StatusActivity(val jobs: List<StatusJob> = emptyList(), val events: List<StatusEvent> = emptyList())

@Serializable
data class StatusJob(
    val component: String? = null,
    val what: String = "",
    val item: String? = null,
    val progress: JsonElement? = null,      // a fraction, a count or a text
    @SerialName("started_at") val startedAt: String? = null,
    @SerialName("elapsed_s") val elapsedS: Double? = null,
) {
    /** 0…1 when the progress is a fraction, else null (shown as text). */
    val fraction: Float? get() = (progress as? JsonPrimitive)?.doubleOrNull?.takeIf { it in 0.0..1.0 }?.toFloat()
    val progressText: String? get() = (progress as? JsonPrimitive)?.let { p -> if (p.isString) p.content else p.doubleOrNull?.takeIf { it > 1 }?.let { "%.0f".format(it) } }
}

@Serializable
data class StatusEvent(
    val at: String? = null,
    val component: String? = null,
    val kind: String? = null,
    val text: String = "",
    val item: String? = null,
    val ok: Boolean = true,
)

/** CONTRACT.md "Monitor": the phrases the monitor listens for, with generated variants. */
@Serializable
data class Phrase(val text: String, val variants: List<String> = emptyList())

@Serializable
data class PhraseList(val phrases: List<Phrase> = emptyList())

interface MonitorApi {
    /** Hits, highest confidence first. */
    suspend fun hits(before: String?, limit: Int = 30): MonitorPage
    suspend fun hit(id: String): MonitorHit
    /** Asks the backend to scan [count] more videos (of [source], or of every account). */
    suspend fun fetchMore(count: Int, source: String?): FetchResult
    /** Publishes a hit to Home and the site; owner-only. */
    suspend fun add(id: String, adminToken: String): MonitorHit
    suspend fun published(before: String?, limit: Int = 30): PublishedPage
    suspend fun status(): StatusReport
    suspend fun phrases(): List<Phrase>
    /** Replaces the list; owner-only. Returns it with the backend's variants. */
    suspend fun savePhrases(texts: List<String>, adminToken: String): List<Phrase>
    /** Applies the list to every stored transcript; owner-only. */
    suspend fun rescan(adminToken: String): FetchResult
    /** True when the backend accepts [adminToken] (`GET /v1/admin/me`). */
    suspend fun checkToken(adminToken: String): Boolean
    val isMock: Boolean
}

class LiveMonitorApi(base: String, private val client: OkHttpClient) : MonitorApi {
    private val base: HttpUrl = base.trimEnd('/').toHttpUrl()
    override val isMock = false

    private fun url(path: String, q: List<Pair<String, String?>> = emptyList()) = base.newBuilder().apply {
        path.trim('/').split('/').forEach { addPathSegment(it) }
        q.forEach { (k, v) -> if (v != null) addQueryParameter(k, v) }
    }.build()

    private suspend fun call(req: Request): String = withContext(Dispatchers.IO) {
        client.newCall(req).await().use { r ->
            if (r.code == 404) throw ApiException.NotFound(req.url.encodedPath)
            if (!r.isSuccessful) throw ApiException.Status(r.code, req.url.encodedPath)
            r.body?.string() ?: ""
        }
    }

    private fun post(url: HttpUrl, json: String, token: String? = null) = Request.Builder().url(url)
        .post(json.toRequestBody("application/json".toMediaType()))
        .apply { token?.let { header("Authorization", "Bearer $it") } }.build()

    override suspend fun hits(before: String?, limit: Int) =
        ContractJson.decodeFromString(MonitorPage.serializer(), call(Request.Builder().url(url("v1/monitor", listOf("before" to before, "limit" to "$limit"))).build()))

    override suspend fun hit(id: String) =
        ContractJson.decodeFromString(MonitorHit.serializer(), call(Request.Builder().url(url("v1/monitor/$id")).build()))

    override suspend fun fetchMore(count: Int, source: String?) =
        ContractJson.decodeFromString(FetchResult.serializer(), call(post(url("v1/monitor/fetch"),
            """{"count":$count${source?.let { ",\"source\":" + ContractJson.encodeToString(kotlinx.serialization.serializer<String>(), it) } ?: ""}}""")))

    override suspend fun add(id: String, adminToken: String) =
        ContractJson.decodeFromString(MonitorHit.serializer(), call(post(url("v1/monitor/$id/add"), "{}", adminToken)))

    override suspend fun published(before: String?, limit: Int) =
        ContractJson.decodeFromString(PublishedPage.serializer(), call(Request.Builder().url(url("v1/published", listOf("before" to before, "limit" to "$limit"))).build()))

    override suspend fun status() =
        ContractJson.decodeFromString(StatusReport.serializer(), call(Request.Builder().url(url("v1/status")).header("Cache-Control", "no-cache").build()))

    override suspend fun phrases() =
        ContractJson.decodeFromString(PhraseList.serializer(), call(Request.Builder().url(url("v1/monitor/phrases")).build())).phrases

    override suspend fun savePhrases(texts: List<String>, adminToken: String): List<Phrase> {
        val body = ContractJson.encodeToString(PhraseList.serializer(), PhraseList(texts.map { Phrase(it) }))
        val req = Request.Builder().url(url("v1/monitor/phrases")).put(body.toRequestBody("application/json".toMediaType()))
            .header("Authorization", "Bearer $adminToken").build()
        return ContractJson.decodeFromString(PhraseList.serializer(), call(req)).phrases
    }

    override suspend fun rescan(adminToken: String) =
        ContractJson.decodeFromString(FetchResult.serializer(), call(post(url("v1/monitor/rescan"), "{}", adminToken)))

    override suspend fun checkToken(adminToken: String): Boolean = try {
        call(Request.Builder().url(url("v1/admin/me")).header("Authorization", "Bearer $adminToken").build()); true
    } catch (e: ApiException.Status) { if (e.code == 401 || e.code == 403) false else throw e }
}

/** Tries the live endpoints and falls back to the mock while they do not exist (404). */
class FallbackMonitorApi(private val live: MonitorApi, private val mock: MonitorApi) : MonitorApi {
    @Volatile private var useMock = false
    override val isMock get() = useMock

    private suspend fun <T> pick(block: suspend (MonitorApi) -> T): T {
        if (useMock) return block(mock)
        return try { block(live) } catch (e: ApiException.NotFound) { useMock = true; block(mock) }
    }

    override suspend fun hits(before: String?, limit: Int) = pick { it.hits(before, limit) }
    override suspend fun hit(id: String) = pick { it.hit(id) }
    override suspend fun fetchMore(count: Int, source: String?) = pick { it.fetchMore(count, source) }
    override suspend fun add(id: String, adminToken: String) = pick { it.add(id, adminToken) }
    override suspend fun published(before: String?, limit: Int) = pick { it.published(before, limit) }
    // Status is a contract endpoint already: never replaced by the mock.
    override suspend fun status() = live.status()
    override suspend fun phrases() = pick { it.phrases() }
    override suspend fun savePhrases(texts: List<String>, adminToken: String) = pick { it.savePhrases(texts, adminToken) }
    override suspend fun rescan(adminToken: String) = pick { it.rescan(adminToken) }
    override suspend fun checkToken(adminToken: String) = live.checkToken(adminToken)
}

/**
 * Made-up hits from made-up accounts, clearly labelled as samples, for building the screens
 * before the backend serves them. The videos are the fixture's.
 */
class MockMonitorApi(private val latencyMs: Long = 250, private val clock: () -> Long = System::currentTimeMillis) : MonitorApi {
    override val isMock = true
    private val hits = seed().toMutableList()
    private var extra = 0

    private suspend fun wait() { if (latencyMs > 0) delay(latencyMs) }

    private fun sorted() = hits.sortedWith(compareByDescending<MonitorHit> { it.confidence }.thenBy { it.id })

    override suspend fun hits(before: String?, limit: Int): MonitorPage {
        wait()
        val all = sorted()
        val start = before?.let { c -> all.indexOfFirst { it.id == c } + 1 } ?: 0
        val page = all.drop(start).take(limit)
        return MonitorPage(page, if (start + page.size < all.size) page.lastOrNull()?.id else null)
    }

    override suspend fun hit(id: String): MonitorHit { wait(); return hits.firstOrNull { it.id == id } ?: throw ApiException.NotFound(id) }

    override suspend fun fetchMore(count: Int, source: String?): FetchResult {
        wait()
        // Pretend the scan found a hit in about one video of five.
        val found = (count / 5).coerceAtLeast(1)
        repeat(found) {
            extra++
            val src = sources.firstOrNull { it.id == source } ?: sources[extra % sources.size]
            hits += MonitorHit(
                id = "mock_more_$extra", reason = if (extra % 2 == 0) "language" else "name", matched = "Тараса",
                language = if (extra % 3 == 0) "ru" else "uk",
                excerpt = "… і тоді Тараса запросили виступити …", translation = "… and then Taras was invited to speak …",
                confidence = 0.35 + (extra % 5) * 0.1, at = 30.0 + extra * 7, detectedAt = java.time.Instant.ofEpochMilli(clock()).toString(),
                video = videos[extra % videos.size].copy(id = "mock_v_more_$extra", title = "Sample briefing #$extra"), source = src,
            )
        }
        return FetchResult(count, "Scanning $count more videos (sample)")
    }

    override suspend fun add(id: String, adminToken: String): MonitorHit {
        wait()
        if (adminToken.isBlank()) throw ApiException.Status(401, "v1/monitor/$id/add")
        val i = hits.indexOfFirst { it.id == id }.takeIf { it >= 0 } ?: throw ApiException.NotFound(id)
        hits[i] = hits[i].copy(status = "added")
        return hits[i]
    }

    override suspend fun published(before: String?, limit: Int): PublishedPage {
        wait()
        val all = hits.filter { it.isAdded }.sortedByDescending { it.detectedAt }
        val start = before?.let { c -> all.indexOfFirst { it.id == c } + 1 } ?: 0
        val page = all.drop(start).take(limit)
        return PublishedPage(page, if (start + page.size < all.size) page.lastOrNull()?.id else null)
    }

    override suspend fun status(): StatusReport {
        wait()
        val now = java.time.Instant.ofEpochMilli(clock())
        fun ago(sec: Long) = now.minusSeconds(sec).toString()
        val tick = (clock() / 5000) % 12
        fun d(vararg kv: Pair<String, Any>) = JsonObject(kv.associate { (k, v) -> k to if (v is Number) JsonPrimitive(v) else JsonPrimitive(v.toString()) })
        return StatusReport(
            generatedAt = now.toString(), overall = "degraded",
            components = listOf(
                ComponentStatus("api", "API", "ok", ago(5), details = d("requests_1m" to 31)),
                ComponentStatus("db", "Database", "ok", ago(5), details = d("size_mb" to 12)),
                ComponentStatus("collector", "Collector", "ok", ago(1800), details = d("last_run_new" to 0)),
                ComponentStatus("monitor", "Monitor", "ok", ago(20), details = d("queue" to 12 - tick, "hits_today" to 3)),
                ComponentStatus("analyzer", "Analyzer", "off", ago(3600), details = d("today" to "20 of 20")),
                ComponentStatus("x_poster", "X poster", "degraded", ago(7200), StatusError(ago(900), "429 Too Many Requests")),
                ComponentStatus("facebook_poster", "Facebook poster", "down", ago(172800), StatusError(ago(86400), "Session logged out; waiting for the owner")),
                ComponentStatus("disk", "Disk", "ok", details = d("free_gb" to 15)),
            ),
            activity = StatusActivity(
                jobs = listOf(StatusJob("monitor", "Transcribing sample briefing", null, JsonPrimitive((tick + 1) / 12.0), ago(40), 40.0)),
                events = listOf(
                    StatusEvent(ago(20), "monitor", "hit", "Heard “Тарасе” at 1:42 (confidence 0.91)"),
                    StatusEvent(ago(300), "monitor", "scan", "Scanned 12 videos from @sample_un_agency"),
                    StatusEvent(ago(900), "x_poster", "error", "429 Too Many Requests; backing off", ok = false),
                    StatusEvent(ago(1800), "collector", "run", "Run finished: 0 new items, 1 updated", "ig_3400000000000000012"),
                ),
            ),
        )
    }

    private var phraseList = listOf("тарас", "тарас маслов", "маслов").map { Phrase(it, variants(it)) }

    override suspend fun phrases(): List<Phrase> { wait(); return phraseList }

    override suspend fun savePhrases(texts: List<String>, adminToken: String): List<Phrase> {
        wait()
        if (adminToken.isBlank()) throw ApiException.Status(401, "v1/monitor/phrases")
        phraseList = texts.map { it.trim() }.filter { it.isNotEmpty() }.distinct().map { Phrase(it, variants(it)) }
        return phraseList
    }

    override suspend fun rescan(adminToken: String): FetchResult {
        wait()
        if (adminToken.isBlank()) throw ApiException.Status(401, "v1/monitor/rescan")
        return FetchResult(0, "Rescanning stored transcripts (sample)")
    }

    override suspend fun checkToken(adminToken: String) = adminToken.isNotBlank()

    /** A rough stand-in for the backend's generated forms: Ukrainian case endings and a transliteration. */
    private fun variants(text: String): List<String> {
        val words = text.split(" ")
        val forms = listOf("а", "у", "ові", "ом", "е").map { end -> words.joinToString(" ") { it + end } }
        val latin = text.map { translit[it] ?: it.toString() }.joinToString("")
        return (forms + latin + latin.replaceFirstChar { it.uppercase() }).distinct()
    }

    companion object {
        private val translit = mapOf('а' to "a", 'б' to "b", 'в' to "v", 'г' to "h", 'д' to "d", 'е' to "e", 'и' to "y", 'і' to "i",
            'к' to "k", 'л' to "l", 'м' to "m", 'н' to "n", 'о' to "o", 'п' to "p", 'р' to "r", 'с' to "s", 'т' to "t", 'у' to "u")

        val sources = listOf(
            MonitorSource("src_mock_1", "sample_ministry", "Sample Ministry of Foreign Affairs (mock)", "youtube", "government", "UA"),
            MonitorSource("src_mock_2", "sample_un_agency", "Sample UN Agency (mock)", "x", "world-organization", null),
            MonitorSource("src_mock_3", "sample_city_hall", "Sample City Hall (mock)", "facebook", "government", "PL"),
        )
        val videos = listOf(
            MonitorVideo("mock_v1", "Sample press briefing", "https://media.empire.earth/sample/items/ig_3400000000000000012/0.mp4", "https://example.org/video/1",
                "https://media.empire.earth/sample/items/ig_3400000000000000012/0.thumb.jpg", "https://media.empire.earth/sample/items/ig_3400000000000000012/0.cover.jpg", 184.0, "2026-10-20T09:00:00Z", "en"),
            MonitorVideo("mock_v2", "Sample conference panel", "https://media.empire.earth/sample/items/ig_3400000000000000006/0.mp4", "https://example.org/video/2",
                "https://media.empire.earth/sample/items/ig_3400000000000000006/0.thumb.jpg", null, 3120.0, "2026-10-18T14:00:00Z", "en"),
        )

        fun seed() = listOf(
            MonitorHit("mock_1", "name", "Тарасе", "uk", "Дякую, Тарасе, за питання.", "Thank you, Taras, for the question.", 0.91, 102.0, 105.5,
                "2026-10-24T10:00:00Z", video = videos[0], source = sources[0]),
            MonitorHit("mock_2", "language", null, "uk", "Ми продовжимо роботу разом із партнерами.", "We will continue working together with our partners.", 0.78, 1410.0, 1416.0,
                "2026-10-23T18:30:00Z", video = videos[1], source = sources[1]),
            MonitorHit("mock_3", "name", "Тарас", "ru", "…как сказал Тарас на прошлой неделе…", "…as Taras said last week…", 0.64, 61.0, 63.0,
                "2026-10-22T08:15:00Z", status = "added", video = videos[0].copy(id = "mock_v3", title = "Sample weekly address"), source = sources[2]),
            MonitorHit("mock_4", "name", "Тарасов", "en", "…the delegation of Mr Tarasov…", null, 0.41, 33.0, 35.0,
                "2026-10-21T12:00:00Z", video = videos[1].copy(id = "mock_v4", title = "Sample plenary session"), source = sources[1]),
            MonitorHit("mock_5", "language", null, "ru", "Спасибо всем, кто пришёл.", "Thanks to everyone who came.", 0.33, 870.0, 872.0,
                "2026-10-20T16:45:00Z", video = videos[0].copy(id = "mock_v5", title = "Sample town hall"), source = sources[2]),
        )
    }
}

