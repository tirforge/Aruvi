package com.aruvi.tir.di

import android.content.Context
import androidx.annotation.OptIn
import androidx.media3.common.util.UnstableApi
import androidx.media3.datasource.DefaultDataSource
import androidx.media3.datasource.okhttp.OkHttpDataSource
import androidx.media3.exoplayer.DefaultRenderersFactory
import androidx.media3.exoplayer.ExoPlayer
import androidx.media3.exoplayer.DefaultLoadControl
import com.aruvi.tir.data.api.AuthInterceptor
import dagger.Module
import dagger.Provides
import dagger.hilt.InstallIn
import dagger.hilt.android.qualifiers.ApplicationContext
import dagger.hilt.components.SingletonComponent
import okhttp3.OkHttpClient
import java.util.concurrent.TimeUnit
import javax.inject.Singleton

/**
 * Hilt module for media player dependencies.
 */
@Module
@InstallIn(SingletonComponent::class)
object PlayerModule {

    /**
     * Provide RenderersFactory for ExoPlayer.
     * 
     * EXTENSION_RENDERER_MODE_ON means:
     * - Extension decoders will be used if available
     * - Standard ExoPlayer supports HEVC, VP9, Opus, AAC, MP3, and most common formats
     */
    @OptIn(UnstableApi::class)
    @Provides
    @Singleton
    fun provideRenderersFactory(
        @ApplicationContext context: Context
    ): DefaultRenderersFactory {
        return DefaultRenderersFactory(context)
            .setExtensionRendererMode(DefaultRenderersFactory.EXTENSION_RENDERER_MODE_ON)
    }

    /**
     * Provide HTTP data source factory using OkHttp with AuthInterceptor.
     * Uses its own OkHttpClient (no body-level logging — that would OOM on large streams).
     */
    @OptIn(UnstableApi::class)
    @Provides
    @Singleton
    fun provideDataSourceFactory(
        @ApplicationContext context: Context,
        authInterceptor: AuthInterceptor
    ): DefaultDataSource.Factory {
        val streamingClient = OkHttpClient.Builder()
            .addInterceptor(authInterceptor)
            .connectTimeout(30, TimeUnit.SECONDS)
            .readTimeout(60, TimeUnit.SECONDS)
            .build()
        val httpFactory = OkHttpDataSource.Factory(streamingClient)
        return DefaultDataSource.Factory(context, httpFactory)
    }

    /**
     * Provide ExoPlayer instance.
     */
    @OptIn(UnstableApi::class)
    @Provides
    @Singleton
    fun provideExoPlayer(
        @ApplicationContext context: Context,
        renderersFactory: DefaultRenderersFactory
    ): ExoPlayer {
        // Increase buffer sizes for smoother streaming
        val loadControl = DefaultLoadControl.Builder()
            .setBufferDurationsMs(
                32_000, // min buffer
                64_000, // max buffer
                10_000, // buffer for playback
                10_000  // buffer for rebuffering
            )
            .build()

        return ExoPlayer.Builder(context, renderersFactory)
            .setLoadControl(loadControl)
            .setSeekBackIncrementMs(10_000)
            .setSeekForwardIncrementMs(10_000)
            .setHandleAudioBecomingNoisy(true)
            .build()
    }
}
