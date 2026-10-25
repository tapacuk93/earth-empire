package com.oeaio.earthempire.ui

import android.content.Context
import android.net.Uri
import androidx.annotation.OptIn
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.LocalInspectionMode
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.viewinterop.AndroidView
import androidx.media3.common.MediaItem
import androidx.media3.common.Player
import androidx.media3.common.util.UnstableApi
import androidx.media3.database.StandaloneDatabaseProvider
import androidx.media3.datasource.DefaultDataSource
import androidx.media3.datasource.cache.CacheDataSource
import androidx.media3.datasource.cache.LeastRecentlyUsedCacheEvictor
import androidx.media3.datasource.cache.SimpleCache
import androidx.media3.datasource.okhttp.OkHttpDataSource
import androidx.media3.exoplayer.ExoPlayer
import androidx.media3.exoplayer.source.DefaultMediaSourceFactory
import androidx.media3.ui.PlayerView
import coil.compose.AsyncImage
import com.oeaio.earthempire.data.MediaUrls
import okhttp3.OkHttpClient
import java.io.File

/** One disk cache for every video, so a watched video plays again offline. */
@OptIn(UnstableApi::class)
object VideoCache {
    @Volatile private var cache: SimpleCache? = null
    var client: OkHttpClient = OkHttpClient()

    fun get(context: Context): SimpleCache = cache ?: synchronized(this) {
        cache ?: SimpleCache(
            File(context.cacheDir, "video"), LeastRecentlyUsedCacheEvictor(300L shl 20), StandaloneDatabaseProvider(context),
        ).also { cache = it }
    }

    fun player(context: Context): ExoPlayer {
        val upstream = DefaultDataSource.Factory(context, OkHttpDataSource.Factory(client))
        val factory = CacheDataSource.Factory().setCache(get(context)).setUpstreamDataSourceFactory(upstream)
            .setFlags(CacheDataSource.FLAG_IGNORE_CACHE_ON_ERROR)
        return ExoPlayer.Builder(context).setMediaSourceFactory(DefaultMediaSourceFactory(factory)).build()
    }
}

/** Seeks requested from outside the player (the event timeline), by media index. */
class SeekRequest(val media: Int, val seconds: Double, val stamp: Long = System.nanoTime())

/**
 * A video: the AI-chosen cover until it plays, then ExoPlayer with its controls. [seek] jumps
 * to a time and plays. In previews and Robolectric there is no player, only the cover.
 */
@OptIn(UnstableApi::class)
@Composable
fun VideoPlayer(
    url: String,
    poster: String?,
    modifier: Modifier = Modifier,
    autoPlay: Boolean = false,
    startAt: Double? = null,
    seek: SeekRequest? = null,
    loop: Boolean = false,
    muted: Boolean = false,
    controls: Boolean = true,
    description: String = "Video",
    onEnded: (() -> Unit)? = null,
) {
    val context = LocalContext.current
    val noPlayer = LocalInspectionMode.current || android.os.Build.FINGERPRINT == "robolectric"
    if (noPlayer) {
        Box(modifier.background(Color.Black).semantics { contentDescription = description }) {
            AsyncImage(MediaUrls.resolve(poster), null, Modifier.fillMaxSize(), contentScale = ContentScale.Fit)
        }
        return
    }
    var ended by remember { mutableStateOf(false) }
    val player = remember(url) {
        VideoCache.player(context).apply {
            setMediaItem(MediaItem.fromUri(Uri.parse(MediaUrls.resolveForPlayer(url))))
            repeatMode = if (loop) Player.REPEAT_MODE_ONE else Player.REPEAT_MODE_OFF
            startAt?.let { seekTo((it * 1000).toLong()) }
            prepare()
            playWhenReady = autoPlay
        }
    }
    DisposableEffect(player) {
        val l = object : Player.Listener {
            override fun onPlaybackStateChanged(state: Int) { if (state == Player.STATE_ENDED) { ended = true; onEnded?.invoke() } }
        }
        player.addListener(l)
        onDispose { player.removeListener(l); player.release() }
    }
    LaunchedEffect(seek?.stamp) {
        seek?.let { player.seekTo((it.seconds * 1000).toLong()); player.play() }
    }
    LaunchedEffect(autoPlay) { player.playWhenReady = autoPlay }
    LaunchedEffect(muted) { player.volume = if (muted) 0f else 1f }
    // The poster (the AI-chosen cover, or a hit's frame) shows through until the first frame, and
    // stays for audio-only clips.
    Box(modifier.background(Color.Black)) {
        AsyncImage(MediaUrls.resolve(poster), null, Modifier.fillMaxSize(), contentScale = ContentScale.Fit)
        AndroidView(
            factory = { ctx ->
                PlayerView(ctx).apply {
                    this.player = player
                    useController = controls
                    setShutterBackgroundColor(android.graphics.Color.TRANSPARENT)
                    setBackgroundColor(android.graphics.Color.TRANSPARENT)
                    setShowBuffering(PlayerView.SHOW_BUFFERING_WHEN_PLAYING)
                    contentDescription = description
                }
            },
            update = { it.useController = controls },
            modifier = Modifier.fillMaxSize(),
        )
    }
}
