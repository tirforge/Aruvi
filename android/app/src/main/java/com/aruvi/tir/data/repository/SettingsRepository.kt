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

/** A login code this device is polling, persisted across process death. */
data class PendingLoginCode(
    val code: String,
    val expiresAtMs: Long,
    val expiresAtIso: String?
)

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
        val PENDING_LOGIN_CODE = stringPreferencesKey("pending_login_code")
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
     * Normalize a user-entered server URL: add a scheme when missing so it
     * never crashes URL parsing / Retrofit at startup.
     *
     * BOTH http:// and https:// are fully supported (localhost, LAN IPs and
     * HTTP tunnels are the norm for self-hosting; HTTPS users type the
     * scheme or paste the full tunnel URL). Scheme-less input defaults to
     * http:// — guessing https would break plain-HTTP servers and tunnels
     * with a confusing connection error at login.
     */
    fun normalizeServerUrl(input: String): String {
        val trimmed = input.trim().trimEnd('/')
        if (trimmed.isEmpty()) return trimmed
        val withScheme = if (trimmed.startsWith("http://") || trimmed.startsWith("https://")) {
            trimmed
        } else {
            "http://$trimmed"
        }
        // Reject bare schemes / empty hosts (e.g. "http://") so callers never
        // persist an origin-less URL that would send tokens to the wrong host.
        if (withScheme.equals("http://", ignoreCase = true) ||
            withScheme.equals("https://", ignoreCase = true)
        ) {
            return ""
        }
        return withScheme
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

    /**
     * The login code this device is currently polling, or null.
     *
     * Persisted because the login screen is destroyed and recreated whenever
     * the user leaves for Telegram (Activity recreation / process death). The
     * code used to live only in the ViewModel, so returning from Telegram
     * minted a brand-new code and abandoned the one the user had just claimed
     * in the bot — login then never completed.
     */
    suspend fun getPendingLoginCode(): PendingLoginCode? {
        val raw = context.settingsDataStore.data.first()[PreferencesKeys.PENDING_LOGIN_CODE]
            ?: return null
        val parts = raw.split("|")
        if (parts.size < 2) return null
        val code = parts[0].trim()
        val expiresAtMs = parts[1].toLongOrNull() ?: return null
        if (code.isEmpty()) return null
        return PendingLoginCode(code, expiresAtMs, parts.getOrNull(2)?.takeIf { it.isNotBlank() })
    }

    suspend fun setPendingLoginCode(code: String, expiresAtMs: Long, expiresAtIso: String?) {
        context.settingsDataStore.edit { prefs ->
            prefs[PreferencesKeys.PENDING_LOGIN_CODE] =
                "$code|$expiresAtMs|${expiresAtIso.orEmpty()}"
        }
    }

    suspend fun clearPendingLoginCode() {
        context.settingsDataStore.edit { prefs ->
            prefs.remove(PreferencesKeys.PENDING_LOGIN_CODE)
        }
    }
}
