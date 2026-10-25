package com.oeaio.earthempire

import android.content.Context
import android.content.SharedPreferences
import com.oeaio.earthempire.data.ArchiveApi
import com.oeaio.earthempire.data.LiveApi
import com.oeaio.earthempire.data.LiveMonitorApi
import com.oeaio.earthempire.data.MediaUrls
import com.oeaio.earthempire.data.MockMonitorApi
import com.oeaio.earthempire.data.MonitorApi
import com.oeaio.earthempire.data.OfflineStore
import com.oeaio.earthempire.data.SampleApi
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import okhttp3.Cache
import okhttp3.OkHttpClient
import java.io.File
import java.util.concurrent.TimeUnit

/** What the user can change in Settings, kept in the app's private preferences. */
class Settings(private val prefs: SharedPreferences) {
    var apiBase: String
        get() = prefs.getString("api_base", null)?.takeIf { it.startsWith("http") } ?: BuildConfig.API_BASE
        set(v) = prefs.edit().putString("api_base", v.trim().ifEmpty { null }).apply()
    var useSample: Boolean
        get() = prefs.getBoolean("sample", false)
        set(v) = prefs.edit().putBoolean("sample", v).apply()
    /** The owner's admin token for "Add". Private app storage, excluded from backups. */
    var adminToken: String
        get() = prefs.getString("admin_token", "") ?: ""
        set(v) = prefs.edit().putString("admin_token", v.trim()).apply()
    /** "tags" or "timeline". */
    var homeView: String
        get() = prefs.getString("home_view", "tags") ?: "tags"
        set(v) = prefs.edit().putString("home_view", v).apply()
    /** Suggested phrases the owner rejected, lowercase. */
    var rejectedPhrases: Set<String>
        get() = prefs.getStringSet("rejected_phrases", emptySet()) ?: emptySet()
        set(v) = prefs.edit().putStringSet("rejected_phrases", v).apply()
    /** "system", "light" or "dark". */
    var theme: String
        get() = prefs.getString("theme", "system") ?: "system"
        set(v) = prefs.edit().putString("theme", v).apply()
}

/** The app's services, built once; tests build one over the fixture and the mock monitor. */
class AppContainer(
    val settings: Settings,
    val client: OkHttpClient,
    private val makeArchive: (Settings) -> ArchiveApi,
    private val makeMonitor: (Settings) -> MonitorApi,
    val cacheDir: File?,
    val fixtureJson: () -> String?,
) {
    private val _archive = MutableStateFlow(makeArchive(settings))
    val archive: StateFlow<ArchiveApi> = _archive
    private val _monitor = MutableStateFlow(makeMonitor(settings))
    val monitor: StateFlow<MonitorApi> = _monitor
    private val _theme = MutableStateFlow(settings.theme)
    val theme: StateFlow<String> = _theme

    fun setTheme(t: String) { settings.theme = t; _theme.value = t }

    private val _owner = MutableStateFlow(settings.adminToken.isNotBlank())
    /** True once the backend accepted the saved admin token: Detected, Status and Settings appear. */
    val owner: StateFlow<Boolean> = _owner

    /**
     * Checks [token] with `GET /v1/admin/me` and keeps it only if accepted. Returns whether it
     * was; throws when the backend could not be reached.
     */
    suspend fun signIn(token: String): Boolean {
        val t = token.trim()
        if (t.isEmpty() || !monitor.value.checkToken(t)) return false
        settings.adminToken = t
        _owner.value = true
        return true
    }

    fun signOut() { settings.adminToken = ""; _owner.value = false }

    /** At launch: a saved token the backend now refuses is dropped; offline keeps it. */
    suspend fun recheckToken() {
        val t = settings.adminToken
        if (t.isNotBlank() && runCatching { monitor.value.checkToken(t) }.getOrDefault(true) == false) signOut()
    }

    /** After Settings change the API base or sample mode: start over with new clients. */
    fun reconfigure() {
        _archive.value = makeArchive(settings)
        _monitor.value = makeMonitor(settings)
    }

    companion object {
        fun create(context: Context): AppContainer {
            val app = context.applicationContext
            val settings = Settings(app.getSharedPreferences("settings", Context.MODE_PRIVATE))
            val client = OkHttpClient.Builder()
                .cache(Cache(File(app.cacheDir, "http"), 50L shl 20))
                .connectTimeout(15, TimeUnit.SECONDS)
                .readTimeout(30, TimeUnit.SECONDS)
                .build()
            val store = OfflineStore(File(app.filesDir, "offline"))
            val fixture = { runCatching { app.assets.open("fixture/fixture.json").bufferedReader().readText() }.getOrNull() }
            val sampleKeys by lazy {
                val keys = mutableSetOf<String>()
                fun walk(dir: String) {
                    val list = app.assets.list(dir).orEmpty()
                    if (list.isEmpty()) keys += dir.removePrefix("fixture/media/") else list.forEach { walk("$dir/$it") }
                }
                walk("fixture/media"); keys
            }
            return AppContainer(
                settings, client,
                makeArchive = { s ->
                    if (s.useSample) {
                        MediaUrls.sampleKeys = sampleKeys
                        fixture()?.let(SampleApi::decode) ?: LiveApi(s.apiBase, client, store)
                    } else {
                        MediaUrls.sampleKeys = emptySet()
                        LiveApi(s.apiBase, client, store)
                    }
                },
                makeMonitor = { s -> if (s.useSample) MockMonitorApi() else LiveMonitorApi(s.apiBase, client) { s.adminToken } },
                cacheDir = app.cacheDir,
                fixtureJson = fixture,
            )
        }
    }
}
