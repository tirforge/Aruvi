package com.aruvi.tir.di

import com.google.gson.Gson
import com.google.gson.GsonBuilder
import com.aruvi.tir.data.api.AuthInterceptor
import com.aruvi.tir.data.api.DynamicBaseUrlInterceptor
import com.aruvi.tir.data.api.TelePlayApi
import com.aruvi.tir.data.repository.AuthRepository
import com.aruvi.tir.data.repository.FilesRepository
import com.aruvi.tir.data.repository.FoldersRepository
import com.aruvi.tir.data.repository.SettingsRepository
import dagger.Module
import dagger.Provides
import dagger.hilt.InstallIn
import dagger.hilt.components.SingletonComponent
import okhttp3.HttpUrl.Companion.toHttpUrlOrNull
import okhttp3.OkHttpClient
import okhttp3.logging.HttpLoggingInterceptor
import retrofit2.Retrofit
import retrofit2.converter.gson.GsonConverterFactory
import com.aruvi.tir.BuildConfig
import com.aruvi.tir.download.FileDownloader
import java.util.concurrent.TimeUnit
import javax.inject.Singleton

/**
 * Hilt module for network dependencies.
 */
@Module
@InstallIn(SingletonComponent::class)
object NetworkModule {

    @Provides
    @Singleton
    fun provideFileDownloader(
        @dagger.hilt.android.qualifiers.ApplicationContext context: android.content.Context,
        authInterceptor: AuthInterceptor,
        dynamicBaseUrlInterceptor: DynamicBaseUrlInterceptor
    ): FileDownloader {
        // Create a dedicated OkHttpClient for downloads:
        // - NO body logging (Level.BODY buffers entire response into memory, killing large downloads)
        // - Longer read timeout for large files
        // - Auth interceptor for automatic token handling
        val downloadLogging = HttpLoggingInterceptor().apply {
            level = HttpLoggingInterceptor.Level.HEADERS
            redactHeader("Authorization")
        }
        val downloadClient = OkHttpClient.Builder()
            .addInterceptor(dynamicBaseUrlInterceptor)
            .addInterceptor(authInterceptor)
            .addInterceptor(downloadLogging)
            .connectTimeout(30, TimeUnit.SECONDS)
            .readTimeout(5, TimeUnit.MINUTES)
            .writeTimeout(60, TimeUnit.SECONDS)
            .build()

        val scope = kotlinx.coroutines.CoroutineScope(
            kotlinx.coroutines.SupervisorJob() + kotlinx.coroutines.Dispatchers.IO
        )
        return FileDownloader(context, downloadClient, scope)
    }

    @Provides
    @Singleton
    fun provideGson(): Gson {
        return GsonBuilder()
            .setDateFormat("yyyy-MM-dd'T'HH:mm:ss")
            .create()
    }

    // AuthInterceptor is provided by @Inject constructor


    @Provides
    @Singleton
    fun provideOkHttpClient(
        authInterceptor: AuthInterceptor,
        dynamicBaseUrlInterceptor: DynamicBaseUrlInterceptor
    ): OkHttpClient {
        val loggingInterceptor = HttpLoggingInterceptor().apply {
            // BODY logging writes every JWT, login code and response body to
            // logcat (and buffers full bodies/images into memory — OOM via
            // the shared Coil client). HEADERS is the loudest safe level.
            level = if (BuildConfig.DEBUG) {
                HttpLoggingInterceptor.Level.HEADERS
            } else {
                HttpLoggingInterceptor.Level.NONE
            }
            redactHeader("Authorization")
        }

        return OkHttpClient.Builder()
            // URL rewrite must run before auth so the token attaches to the
            // request that actually goes to the CURRENT server.
            .addInterceptor(dynamicBaseUrlInterceptor)
            .addInterceptor(authInterceptor)
            .addInterceptor(loggingInterceptor)
            .connectTimeout(30, TimeUnit.SECONDS)
            .readTimeout(60, TimeUnit.SECONDS)
            .writeTimeout(60, TimeUnit.SECONDS)
            .build()
    }

    @Provides
    @Singleton
    fun provideRetrofit(
        okHttpClient: OkHttpClient,
        gson: Gson,
        settingsRepository: SettingsRepository
    ): Retrofit {
        // Placeholder only. DynamicBaseUrlInterceptor rewrites to peekServerUrl.
        // Cache is seeded only by getServerUrl or setServerUrl, not by Flow
        // collection. Callers must call getServerUrl before credentialed
        // requests or tokens go to the build default. Never block here.
        val configured = BuildConfig.DEFAULT_SERVER_URL.ifBlank { "http://localhost:7680" }
        val parsed = try {
            configured.trim().toHttpUrlOrNull()
        } catch (_: Exception) {
            null
        }
        val baseUrl = if (parsed != null && parsed.host.isNotBlank()) {
            // Drop userinfo here: the interceptor rewrites only
            // scheme/host/port, so a base with credentials would leak stale
            // userinfo into every rewritten request after a server switch.
            parsed.newBuilder().username("").password("").encodedPath("/").query(null).fragment(null).build().toString()
        } else {
            "http://localhost:7680/"
        }

        return Retrofit.Builder()
            .baseUrl(baseUrl + "api/")
            .client(okHttpClient)
            .addConverterFactory(GsonConverterFactory.create(gson))
            .build()
    }

    @Provides
    @Singleton
    fun provideTelePlayApi(retrofit: Retrofit): TelePlayApi {
        return retrofit.create(TelePlayApi::class.java)
    }

    @Provides
    @Singleton
    fun provideFilesRepository(api: TelePlayApi): FilesRepository {
        return FilesRepository(api)
    }

    @Provides
    @Singleton
    fun provideFoldersRepository(api: TelePlayApi): FoldersRepository {
        return FoldersRepository(api)
    }
}
