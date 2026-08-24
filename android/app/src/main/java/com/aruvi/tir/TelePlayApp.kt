package com.aruvi.tir

import android.app.Application
import coil.ImageLoader
import coil.ImageLoaderFactory
import coil.disk.DiskCache
import coil.memory.MemoryCache
import com.google.android.gms.cast.framework.CastContext
import dagger.hilt.android.HiltAndroidApp
import okhttp3.OkHttpClient
import javax.inject.Inject

/**
 * Main Application class for TelePlay.
 * Initializes Hilt and configures Coil image loader.
 */
@HiltAndroidApp
class TelePlayApp : Application(), ImageLoaderFactory {

    @Inject
    lateinit var okHttpClient: OkHttpClient

    override fun onCreate() {
        super.onCreate()
        // Eagerly initialize the GMS CastContext so its MediaRouteProvider is
        // registered before any MediaRouteButton is shown. DefaultCastOptionsProvider
        // is declared in the manifest, so getSharedInstance() bootstraps the default
        // receiver and enables Chromecast discovery. Must run on the main thread
        // (Application.onCreate does) and never crash the app if Cast is unavailable.
        try {
            CastContext.getSharedInstance(this)
        } catch (_: Throwable) {
            // Play Services missing / Cast unavailable — casting simply won't appear.
        }
    }

    override fun newImageLoader(): ImageLoader {
        return ImageLoader.Builder(this)
            .okHttpClient(okHttpClient)
            .memoryCache {
                MemoryCache.Builder(this)
                    .maxSizePercent(0.25)
                    .build()
            }
            .diskCache {
                DiskCache.Builder()
                    .directory(cacheDir.resolve("image_cache"))
                    .maxSizePercent(0.02)
                    .build()
            }
            .crossfade(true)
            .build()
    }
}
