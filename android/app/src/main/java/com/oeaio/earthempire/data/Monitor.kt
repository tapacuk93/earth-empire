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
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.put
import java.io.IOException

// CONTRACT.md "Monitor": public videos where a name like one of the owner's phrases is heard, or
// Ukrainian/Russian speech where none is expected. Every field the contract marks optional is
// optional here, and unknown fields are ignored.

@Serializable
data class HitSource(
    val id: String = "",
    val name: String? = null,
    val kind: String? = null,               // ministry | …
    val country: String? = null,
    @SerialName("source_kind") val sourceKind: String? = null,
)

@Serializable
data class HitVideo(
    val id: String = "",
    val url: String? = null,                 // the post on its platform (or a media file for ad hoc scans)
    val title: String? = null,
    @SerialName("posted_at") val postedAt: String? = null,
    val duration: Double? = null,
    val thumbnail: String? = null,
)

@Serializable
data class Excerpt(
    val text: String = "",
    val start: Double? = null,
    val end: Double? = null,
    val language: String? = null,
    val en: String? = null,                  // the English translation
)

@Serializable
data class Judge(
    val by: String? = null,
    @SerialName("name_probability") val nameProbability: Double? = null,
    val reason: String? = null,
)

@Serializable
data class MonitorHit(
    val id: String,
    val kind: String = "name",              // name | language
    val phrase: String? = null,
    val matched: String? = null,            // the words as transcribed; "uk" | "ru" for language hits
    val confidence: Double = 0.0,
    @SerialName("confidence_label") val confidenceLabel: String? = null,   // likely | possible | low confidence
    val scores: JsonObject? = null,
    val notes: List<String> = emptyList(),
    val judge: Judge? = null,
    val language: String? = null,
    @SerialName("expected_languages") val expectedLanguages: List<String> = emptyList(),
    val platform: String? = null,
    @SerialName("source_kind") val sourceKind: String? = null,
    val via: String? = null,
    val hop: Int? = null,
    val source: HitSource = HitSource(),
    val account: String? = null,
    val video: HitVideo = HitVideo(),
    val start: Double = 0.0,
    val end: Double? = null,
    @SerialName("at_url") val atUrl: String? = null,
    val excerpt: Excerpt = Excerpt(),
    val clip: String? = null,                // <= 20 s of audio around the hit
    val frame: String? = null,
    val model: String? = null,
    @SerialName("found_at") val foundAt: String? = null,
    @SerialName("published_at") val publishedAt: String? = null,
) {
    /** The contract's label (>= 0.7 likely, >= 0.4 possible, else low confidence). */
    val label: String get() = confidenceLabel ?: when { confidence >= 0.7 -> "likely"; confidence >= 0.4 -> "possible"; else -> "low confidence" }
    val isLowConfidence get() = label == "low confidence"
    val isPublished get() = publishedAt != null
    val poster: String? get() = frame ?: video.thumbnail
    val sourceTitle: String get() = source.name ?: account?.let { "@$it" } ?: platform ?: "Unknown source"

    val reasonLabel: String get() =
        if (kind == "language") "${languageName(matched ?: language)} speech; expected ${expectedLanguages.joinToString("/") { languageName(it) }.ifEmpty { "another language" }}"
        else "Heard “${matched ?: phrase ?: "?"}”" + (phrase?.let { " ≈ $it" } ?: "")

    /**
     * What the app can play: the clip around the hit (audio, from its start), else the video
     * itself when its URL is a media file (from just before the hit). Null when only the
     * platform's page has it ([atUrl]).
     */
    val playable: Pair<String, Double>? get() = when {
        clip != null -> clip to 0.0
        video.url != null && isMediaFile(video.url) -> video.url to (start - 2).coerceAtLeast(0.0)
        else -> null
    }

    companion object {
        fun languageName(code: String?) = when (code?.lowercase()) {
            "uk" -> "Ukrainian"; "ru" -> "Russian"; "en" -> "English"; "de" -> "German"; "fr" -> "French"; "pl" -> "Polish"
            null, "" -> "Unknown"
            else -> code
        }

        fun isMediaFile(url: String): Boolean {
            val path = url.substringBefore('?').lowercase()
            return listOf(".mp4", ".m4a", ".mp3", ".webm", ".mov", ".m3u8", ".ogg", ".wav").any { path.endsWith(it) } || "://media.empire.earth/" in url
        }
    }
}

@Serializable
data class MonitorPage(val hits: List<MonitorHit> = emptyList(), val next: String? = null)

/** `POST /v1/monitor/fetch` → how many videos were queued. */
@Serializable
data class FetchResult(
    @SerialName("request_id") val requestId: String? = null,
    val n: Int = 0,
    val queued: Int = 0,
    @SerialName("to_discover") val toDiscover: Int = 0,
) {
    val message get() = "Queued $queued video${if (queued == 1) "" else "s"} to scan" + if (toDiscover > 0) "; looking for $toDiscover more." else "."
}

@Serializable
data class RescanResult(val ok: Boolean = true, val videos: Int = 0)

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
data class Phrase(
    val text: String,
    val variants: List<String> = emptyList(),
    val mishearings: List<String> = emptyList(),
    @SerialName("claude_variants") val claudeVariants: List<String> = emptyList(),
    @SerialName("updated_at") val updatedAt: String? = null,
) {
    /** Every generated form, for showing read-only. */
    val allVariants get() = (variants + claudeVariants + mishearings).filter { !it.equals(text, ignoreCase = true) }.distinct()
}

@Serializable
data class PhrasesUpdate(val phrases: List<String>, val rescan: Boolean? = null)

@Serializable
data class PhraseList(val phrases: List<Phrase> = emptyList())

interface MonitorApi {
    /** Hits, highest confidence first; [kind] is "name", "language" or null for both. */
    suspend fun hits(before: String?, limit: Int = 30, kind: String? = null): MonitorPage
    suspend fun hit(id: String): MonitorHit
    /** Queues [n] (max 50) more videos to scan, optionally of one platform or source kind. */
    suspend fun fetchMore(n: Int, platform: String? = null, sourceKind: String? = null): FetchResult
    /** Publishes a hit to Home and the site, or takes it back; owner-only. */
    suspend fun publish(id: String, adminToken: String, publish: Boolean = true): MonitorHit
    /** The published hits, newest first. */
    suspend fun published(before: String?, limit: Int = 30): MonitorPage
    suspend fun status(): StatusReport
    suspend fun phrases(): List<Phrase>
    /** Replaces the list; owner-only. Returns it with the backend's variants. */
    suspend fun savePhrases(texts: List<String>, adminToken: String, rescan: Boolean = true): List<Phrase>
    /** Applies the phrases to every stored transcript again; owner-only. */
    suspend fun rescan(adminToken: String): RescanResult
    /** True when the backend accepts [adminToken] (`GET /v1/admin/me`). */
    suspend fun checkToken(adminToken: String): Boolean
    val isMock: Boolean
}

/**
 * The monitor endpoints are owner-only (the admin token), except `/v1/published` and
 * `/v1/status`; every request carries the saved token when there is one.
 */
class LiveMonitorApi(base: String, private val client: OkHttpClient, private val token: () -> String = { "" }) : MonitorApi {
    private val base: HttpUrl = base.trimEnd('/').toHttpUrl()
    override val isMock = false

    private fun url(path: String, q: List<Pair<String, String?>> = emptyList()) = base.newBuilder().apply {
        path.trim('/').split('/').forEach { addPathSegment(it) }
        q.forEach { (k, v) -> if (v != null) addQueryParameter(k, v) }
    }.build()

    private suspend fun call(request: Request): String = withContext(Dispatchers.IO) {
        val t = token()
        val req = if (request.header("Authorization") == null && t.isNotBlank()) request.newBuilder().header("Authorization", "Bearer $t").build() else request
        client.newCall(req).await().use { r ->
            if (r.code == 404) throw ApiException.NotFound(req.url.encodedPath)
            if (!r.isSuccessful) throw ApiException.Status(r.code, req.url.encodedPath)
            r.body?.string() ?: ""
        }
    }

    private fun get(url: HttpUrl) = Request.Builder().url(url).build()
    private fun send(method: String, url: HttpUrl, json: String, token: String? = null) = Request.Builder().url(url)
        .method(method, json.toRequestBody("application/json".toMediaType()))
        .apply { token?.let { header("Authorization", "Bearer $it") } }.build()

    private fun <T> decode(de: kotlinx.serialization.DeserializationStrategy<T>, s: String) = ContractJson.decodeFromString(de, s)

    override suspend fun hits(before: String?, limit: Int, kind: String?) =
        decode(MonitorPage.serializer(), call(get(url("v1/monitor/hits", listOf("kind" to kind, "sort" to "confidence", "before" to before, "limit" to "$limit")))))

    override suspend fun hit(id: String) = decode(MonitorHit.serializer(), call(get(url("v1/monitor/hits/$id"))))

    override suspend fun fetchMore(n: Int, platform: String?, sourceKind: String?): FetchResult {
        val body = buildJsonObject {
            put("n", n.coerceIn(1, 50))
            platform?.let { put("platform", it) }
            sourceKind?.let { put("source_kind", it) }
        }.toString()
        return decode(FetchResult.serializer(), call(send("POST", url("v1/monitor/fetch"), body)))
    }

    override suspend fun publish(id: String, adminToken: String, publish: Boolean) =
        decode(MonitorHit.serializer(), call(send("POST", url("v1/monitor/hits/$id/" + if (publish) "publish" else "unpublish"), "{}", adminToken)))

    override suspend fun published(before: String?, limit: Int) =
        decode(MonitorPage.serializer(), call(get(url("v1/published", listOf("before" to before, "limit" to "$limit")))))

    override suspend fun status() =
        decode(StatusReport.serializer(), call(Request.Builder().url(url("v1/status")).header("Cache-Control", "no-cache").build()))

    override suspend fun phrases() = decode(PhraseList.serializer(), call(get(url("v1/monitor/phrases")))).phrases

    override suspend fun savePhrases(texts: List<String>, adminToken: String, rescan: Boolean): List<Phrase> {
        val body = ContractJson.encodeToString(PhrasesUpdate.serializer(), PhrasesUpdate(texts, rescan.takeIf { it }))
        return decode(PhraseList.serializer(), call(send("PUT", url("v1/monitor/phrases"), body, adminToken))).phrases
    }

    override suspend fun rescan(adminToken: String) =
        decode(RescanResult.serializer(), call(send("POST", url("v1/monitor/rescan"), "{}", adminToken)))

    override suspend fun checkToken(adminToken: String): Boolean = try {
        call(Request.Builder().url(url("v1/admin/me")).header("Authorization", "Bearer $adminToken").build()); true
    } catch (e: ApiException.Status) { if (e.code == 401 || e.code == 403) false else throw e }
}

/**
 * Made-up hits from made-up accounts, clearly labelled as samples, for sample mode, previews and
 * tests. Their media are the fixture's.
 */
class MockMonitorApi(private val latencyMs: Long = 250, private val clock: () -> Long = System::currentTimeMillis) : MonitorApi {
    override val isMock = true
    private val hits = seed().toMutableList()
    private var extra = 0

    private suspend fun wait() { if (latencyMs > 0) delay(latencyMs) }

    private fun page(all: List<MonitorHit>, before: String?, limit: Int): MonitorPage {
        val start = before?.let { c -> all.indexOfFirst { it.id == c } + 1 } ?: 0
        val page = all.drop(start).take(limit)
        return MonitorPage(page, if (start + page.size < all.size) page.lastOrNull()?.id else null)
    }

    override suspend fun hits(before: String?, limit: Int, kind: String?): MonitorPage {
        wait()
        return page(hits.filter { kind == null || it.kind == kind }.sortedWith(compareByDescending<MonitorHit> { it.confidence }.thenBy { it.id }), before, limit)
    }

    override suspend fun hit(id: String): MonitorHit { wait(); return hits.firstOrNull { it.id == id } ?: throw ApiException.NotFound(id) }

    override suspend fun fetchMore(n: Int, platform: String?, sourceKind: String?): FetchResult {
        wait()
        // Pretend about one video in five has a hit.
        repeat((n / 5).coerceAtLeast(1)) {
            extra++
            val base = seed()[extra % 3]
            hits += base.copy(
                id = "mock_more_$extra", confidence = 0.3 + (extra % 6) * 0.1, confidenceLabel = null, publishedAt = null,
                foundAt = java.time.Instant.ofEpochMilli(clock()).toString(), video = base.video.copy(id = "mock_v_more_$extra", title = "Sample briefing #$extra"),
                platform = platform ?: base.platform,
            )
        }
        return FetchResult("mock", n, n, 0)
    }

    override suspend fun publish(id: String, adminToken: String, publish: Boolean): MonitorHit {
        wait()
        if (adminToken.isBlank()) throw ApiException.Status(401, "v1/monitor/hits/$id/publish")
        val i = hits.indexOfFirst { it.id == id }.takeIf { it >= 0 } ?: throw ApiException.NotFound(id)
        hits[i] = hits[i].copy(publishedAt = if (publish) java.time.Instant.ofEpochMilli(clock()).toString() else null)
        return hits[i]
    }

    override suspend fun published(before: String?, limit: Int): MonitorPage {
        wait()
        return page(hits.filter { it.isPublished }.sortedByDescending { it.publishedAt }, before, limit)
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

    override suspend fun savePhrases(texts: List<String>, adminToken: String, rescan: Boolean): List<Phrase> {
        wait()
        if (adminToken.isBlank()) throw ApiException.Status(401, "v1/monitor/phrases")
        phraseList = texts.map { it.trim() }.filter { it.isNotEmpty() }.distinct().map { Phrase(it, variants(it)) }
        return phraseList
    }

    override suspend fun rescan(adminToken: String): RescanResult {
        wait()
        if (adminToken.isBlank()) throw ApiException.Status(401, "v1/monitor/rescan")
        return RescanResult(true, hits.size)
    }

    override suspend fun checkToken(adminToken: String) = adminToken.isNotBlank()

    /** A rough stand-in for the backend's generated forms: Ukrainian case endings and a transliteration. */
    private fun variants(text: String): List<String> {
        val words = text.split(" ")
        val forms = listOf("а", "у", "ові", "ом", "е").map { end -> words.joinToString(" ") { it + end } }
        val latin = text.map { translit[it] ?: it.toString() }.joinToString("")
        return (listOf(text) + forms + latin + latin.replaceFirstChar { it.uppercase() }).distinct()
    }

    companion object {
        private val translit = mapOf('а' to "a", 'б' to "b", 'в' to "v", 'г' to "h", 'д' to "d", 'е' to "e", 'и' to "y", 'і' to "i",
            'к' to "k", 'л' to "l", 'м' to "m", 'н' to "n", 'о' to "o", 'п' to "p", 'р' to "r", 'с' to "s", 'т' to "t", 'у' to "u")

        private const val M = "https://media.empire.earth/sample/items/"
        private val ministry = HitSource("mock_ministry", "Sample Ministry of Foreign Affairs (mock)", "ministry", "UA", "official")
        private val agency = HitSource("mock_agency", "Sample UN Agency (mock)", "organization", null, "official")
        private val city = HitSource("mock_city", "Sample City Hall (mock)", "city", "PL", "followed")

        private fun video(id: String, title: String, item: String, duration: Double, posted: String) =
            HitVideo(id, "${M}$item/0.mp4", title, posted, duration, "${M}$item/0.thumb.jpg")

        fun seed() = listOf(
            MonitorHit("mock_1", "name", "тарас", "Тарасе", 0.91, notes = listOf("a form of 'тарас' (vocative)"), language = "uk", expectedLanguages = listOf("uk"),
                platform = "youtube", sourceKind = "official", source = ministry, account = "sample_ministry",
                video = video("mock_v1", "Sample press briefing", "ig_3400000000000000012", 184.0, "2026-10-20T09:00:00Z"),
                start = 102.0, end = 102.6, atUrl = "https://example.org/watch?v=1&t=100",
                excerpt = Excerpt("Дякую, Тарасе, за питання.", 100.5, 104.0, "uk", "Thank you, Taras, for the question."),
                frame = "${M}ig_3400000000000000012/0.cover.jpg", model = "sample", foundAt = "2026-10-24T10:00:00Z"),
            MonitorHit("mock_2", "language", null, "uk", 0.78, notes = listOf("16 s of speech identified as uk; this source normally speaks en"),
                language = "uk", expectedLanguages = listOf("en"), platform = "x", sourceKind = "official", source = agency, account = "sample_un_agency",
                video = video("mock_v2", "Sample conference panel", "ig_3400000000000000006", 3120.0, "2026-10-18T14:00:00Z"),
                start = 1410.0, end = 1426.0, excerpt = Excerpt("Ми продовжимо роботу разом із партнерами.", 1410.0, 1416.0, "uk", "We will continue working together with our partners."),
                foundAt = "2026-10-23T18:30:00Z"),
            MonitorHit("mock_3", "name", "тарас маслов", "Тараса Маслова", 0.64, notes = listOf("both words match"), language = "ru", expectedLanguages = listOf("ru"),
                platform = "telegram", sourceKind = "followed", source = city, account = "sample_city_hall",
                video = video("mock_v3", "Sample weekly address", "ig_3400000000000000012", 184.0, "2026-10-17T08:00:00Z"),
                start = 61.0, end = 62.2, excerpt = Excerpt("…как сказал Тараса Маслова на прошлой неделе…", 58.0, 64.0, "ru", "…as Taras Maslov said last week…"),
                foundAt = "2026-10-22T08:15:00Z", publishedAt = "2026-10-22T09:00:00Z"),
            MonitorHit("mock_4", "name", "маслов", "Maslov", 0.41, notes = listOf("may be a common surname"), language = "en", expectedLanguages = listOf("en"),
                platform = "youtube", sourceKind = "recommended", via = "mock_1", hop = 1, source = agency, account = "sample_un_agency",
                video = video("mock_v4", "Sample plenary session", "ig_3400000000000000006", 3120.0, "2026-10-16T12:00:00Z"),
                start = 33.0, end = 33.5, excerpt = Excerpt("…the delegation of Mr Maslov…", 31.0, 36.0, "en", null), foundAt = "2026-10-21T12:00:00Z"),
            MonitorHit("mock_5", "language", null, "ru", 0.33, notes = listOf("4 s only; may be a song"), language = "ru", expectedLanguages = listOf("pl"),
                platform = "facebook", sourceKind = "followed", source = city, account = "sample_city_hall",
                video = video("mock_v5", "Sample town hall", "ig_3400000000000000012", 184.0, "2026-10-15T16:00:00Z"),
                start = 87.0, end = 91.0, excerpt = Excerpt("Спасибо всем, кто пришёл.", 87.0, 91.0, "ru", "Thanks to everyone who came."), foundAt = "2026-10-20T16:45:00Z"),
        )
    }
}
