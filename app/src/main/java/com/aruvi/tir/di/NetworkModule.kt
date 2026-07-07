package com.aruvi.tir.di

import com.google.gson.Gson
import com.google.gson.GsonBuilder
import com.aruvi.tir.data.api.AuthInterceptor
import com.aruvi.tir.data.api.TelePlayApi
import com.aruvi.tir.data.repository.AuthRepository
import com.aruvi.tir.data.repository.FilesRepository
import com.aruvi.tir.data.repository.FoldersRepository
import com.aruvi.tir.data.repository.SettingsRepository
import dagger.Module
import dagger.Provides
import dagger.hilt.InstallIn
import dagger.hilt.components.SingletonComponent
import kotlinx.coroutines.runBlocking
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
        authInterceptor: AuthInterceptor
    ): FileDownloader {
        // Create a dedicated OkHttpClient for downloads:
        // - NO body logging (Level.BODY buffers entire response into memory, killing large downloads)
        // - Longer read timeout for large files
        // - Auth interceptor for automatic token handling
        val downloadLogging = HttpLoggingInterceptor().apply {
            level = HttpLoggingInterceptor.Level.HEADERS
        }
        val downloadClient = OkHttpClient.Builder()
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
    fun provideOkHttpClient(authInterceptor: AuthInterceptor): OkHttpClient {
        val loggingInterceptor = HttpLoggingInterceptor().apply {
            level = HttpLoggingInterceptor.Level.BODY
        }

        return OkHttpClient.Builder()
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
        val defaultUrl = BuildConfig.DEFAULT_SERVER_URL.ifBlank { "https://movie.aaruvi.space" }
        val serverUrl = try {
            runBlocking { settingsRepository.getServerUrl() }
        } catch (e: Exception) {
            defaultUrl
        }
        val baseUrl = if (serverUrl.endsWith("/")) serverUrl else "$serverUrl/"

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
