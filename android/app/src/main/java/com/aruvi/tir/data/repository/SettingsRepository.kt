package com.aruvi.tir.data.repository

import android.content.Context
import androidx.datastore.core.DataStore
import androidx.datastore.preferences.core.Preferences
import androidx.datastore.preferences.core.booleanPreferencesKey
import androidx.datastore.preferences.core.edit
import androidx.datastore.preferences.core.stringPreferencesKey
import androidx.datastore.preferences.preferencesDataStore
import com.aruvi.tir.BuildConfig
import dagger.hilt.android.qualifiers.ApplicationContext
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.flow.map
import javax.inject.Inject
import javax.inject.Singleton

private val Context.settingsDataStore: DataStore<Preferences> by preferencesDataStore(name = "settings")

/**
 * Repository for app settings.
 */
@Singleton
class SettingsRepository @Inject constructor(
    @ApplicationContext private val context: Context
) {
    private object PreferencesKeys {
        val SERVER_URL = stringPreferencesKey("server_url")
        val BOT_USERNAME = stringPreferencesKey("bot_username")
        val AUTO_PLAY_NEXT = booleanPreferencesKey("auto_play_next")
        val PREFERRED_QUALITY = stringPreferencesKey("preferred_quality")
    }

    /**
     * Get server URL flow.
     */
    val serverUrl: Flow<String> = context.settingsDataStore.data.map { prefs ->
        prefs[PreferencesKeys.SERVER_URL]
            ?: BuildConfig.DEFAULT_SERVER_URL.ifBlank { "http://localhost:7680" }
    }

    /**
     * Get server URL synchronously.
     */
    suspend fun getServerUrl(): String {
        return context.settingsDataStore.data.first()[PreferencesKeys.SERVER_URL]
            ?: BuildConfig.DEFAULT_SERVER_URL.ifBlank { "http://localhost:7680" }
    }

    /**
     * Set server URL.
     */
    suspend fun setServerUrl(url: String) {
        context.settingsDataStore.edit { prefs ->
            prefs[PreferencesKeys.SERVER_URL] = url.trimEnd('/')
        }
    }

    /**
     * Get bot username.
     */
    val botUsername: Flow<String> = context.settingsDataStore.data.map { prefs ->
        prefs[PreferencesKeys.BOT_USERNAME] ?: "Aaruvi_movie_bot"
    }

    suspend fun setBotUsername(username: String) {
        context.settingsDataStore.edit { prefs ->
            prefs[PreferencesKeys.BOT_USERNAME] = username
        }
    }

    /**
     * Get auto-play next setting.
     */
    val autoPlayNext: Flow<Boolean> = context.settingsDataStore.data.map { prefs ->
        prefs[PreferencesKeys.AUTO_PLAY_NEXT] ?: true
    }

    /**
     * Set auto-play next.
     */
    suspend fun setAutoPlayNext(enabled: Boolean) {
        context.settingsDataStore.edit { prefs ->
            prefs[PreferencesKeys.AUTO_PLAY_NEXT] = enabled
        }
    }

    /**
     * Get preferred quality.
     */
    val preferredQuality: Flow<String> = context.settingsDataStore.data.map { prefs ->
        prefs[PreferencesKeys.PREFERRED_QUALITY] ?: "auto"
    }

    /**
     * Set preferred quality.
     */
    suspend fun setPreferredQuality(quality: String) {
        context.settingsDataStore.edit { prefs ->
            prefs[PreferencesKeys.PREFERRED_QUALITY] = quality
        }
    }
}
