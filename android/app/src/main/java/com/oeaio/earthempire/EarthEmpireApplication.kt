package com.oeaio.earthempire

import android.app.Application
import coil.ImageLoader
import coil.ImageLoaderFactory
import coil.disk.DiskCache
import coil.memory.MemoryCache

class EarthEmpireApplication : Application(), ImageLoaderFactory {
    val container: AppContainer by lazy { AppContainer.create(this) }

    /** Images from a disk cache, so the archive's pictures show offline. */
    override fun newImageLoader(): ImageLoader = ImageLoader.Builder(this)
        .okHttpClient { container.client }
        .memoryCache { MemoryCache.Builder(this).maxSizePercent(0.2).build() }
        .diskCache { DiskCache.Builder().directory(cacheDir.resolve("images")).maxSizeBytes(200L shl 20).build() }
        .respectCacheHeaders(false)
        .crossfade(true)
        .build()
}
