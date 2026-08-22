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
        val BOT_NAME = stringPreferencesKey("bot_name")
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
        val url = context.settingsDataStore.data.first()[PreferencesKeys.SERVER_URL]
            ?: BuildConfig.DEFAULT_SERVER_URL.ifBlank { "http://localhost:7680" }
        serverUrlCache.set(url)
        return url
    }

    // In-memory mirror of the persisted URL. OkHttp interceptors run on IO
    // threads and need the CURRENT server synchronously — reading DataStore
    // there (runBlocking per request) would block and race. Updated on every
    // read/write; the atomic makes reads safe from any thread.
    private val serverUrlCache = java.util.concurrent.atomic.AtomicReference(
        BuildConfig.DEFAULT_SERVER_URL.ifBlank { "http://localhost:7680" }
    )

    /**
     * Last-known server URL without any IO — safe to call from an interceptor.
     * Falls back to the build default until the first [getServerUrl] call.
     */
    fun peekServerUrl(): String = serverUrlCache.get()

    /**
     * Normalize a user-entered server URL: add a scheme when missing so it never
     * crashes URL parsing / Retrofit at startup.
     *
     * Scheme-less input keeps http:// for LAN self-hosting targets (private
     * ranges, localhost, raw IPs) where TLS is rare, but defaults to https://
     * for public hostnames — a typo'd public domain must not silently send
     * bearer tokens in cleartext.
     */
    fun normalizeServerUrl(input: String): String {
        val trimmed = input.trim().trimEnd('/')
        if (trimmed.isEmpty()) return trimmed
        if (trimmed.startsWith("http://") || trimmed.startsWith("https://")) {
            return trimmed
        }
        val host = trimmed.substringAfter("://").substringBefore('/').substringBefore(':')
        val isLocal = host == "localhost" || host == "127.0.0.1" || host == "::1" ||
            host.endsWith(".local") || host.endsWith(".lan") || host.endsWith(".internal") ||
            isPrivateIpv4(host)
        return if (isLocal) "http://$trimmed" else "https://$trimmed"
    }

    private fun isPrivateIpv4(host: String): Boolean {
        val parts = host.split('.')
        if (parts.size != 4) return false
        val octets = parts.map { it.toIntOrNull() ?: return false }
        return (octets[0] == 10) ||
            (octets[0] == 172 && octets[1] in 16..31) ||
            (octets[0] == 192 && octets[1] == 168) ||
            (octets[0] == 169 && octets[1] == 254)
    }

    /**
     * Set server URL.
     */
    suspend fun setServerUrl(url: String) {
        val normalized = normalizeServerUrl(url)
        context.settingsDataStore.edit { prefs ->
            prefs[PreferencesKeys.SERVER_URL] = normalized
        }
        serverUrlCache.set(normalized)
    }

    /**
     * Get bot username.
     */
    val botUsername: Flow<String> = context.settingsDataStore.data.map { prefs ->
        prefs[PreferencesKeys.BOT_USERNAME].orEmpty()
    }

    suspend fun setBotUsername(username: String) {
        context.settingsDataStore.edit { prefs ->
            prefs[PreferencesKeys.BOT_USERNAME] = username
        }
    }

    /**
     * Get bot display name.
     */
    val botName: Flow<String> = context.settingsDataStore.data.map { prefs ->
        prefs[PreferencesKeys.BOT_NAME].orEmpty()
    }

    suspend fun setBotName(name: String) {
        context.settingsDataStore.edit { prefs ->
            prefs[PreferencesKeys.BOT_NAME] = name
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
