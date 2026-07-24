package com.aruvi.tir.data.repository

import android.content.Context
import androidx.datastore.core.DataStore
import androidx.datastore.preferences.core.Preferences
import androidx.datastore.preferences.core.edit
import androidx.datastore.preferences.core.stringPreferencesKey
import androidx.datastore.preferences.preferencesDataStore
import com.aruvi.tir.data.api.TelePlayApi
import com.aruvi.tir.data.model.*
import dagger.hilt.android.qualifiers.ApplicationContext
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.flow.map
import javax.inject.Inject
import javax.inject.Singleton

private val Context.dataStore: DataStore<Preferences> by preferencesDataStore(name = "auth_prefs")

/**
 * Repository for authentication operations.
 */
@Singleton
class AuthRepository @Inject constructor(
    @ApplicationContext private val context: Context,
    private val api: TelePlayApi
) {
    private object PreferencesKeys {
        val ACCESS_TOKEN = stringPreferencesKey("access_token")
        val REFRESH_TOKEN = stringPreferencesKey("refresh_token")
        val USER_ID = stringPreferencesKey("user_id")
        val USER_NAME = stringPreferencesKey("user_name")
    }

    /**
     * Get access token from storage.
     */
    suspend fun getAccessToken(): String? {
        return context.dataStore.data.first()[PreferencesKeys.ACCESS_TOKEN]
    }

    /**
     * Get refresh token from storage.
     */
    suspend fun getRefreshToken(): String? {
        return context.dataStore.data.first()[PreferencesKeys.REFRESH_TOKEN]
    }

    /**
     * Save tokens to secure storage.
     */
    suspend fun saveTokens(accessToken: String, refreshToken: String) {
        context.dataStore.edit { prefs ->
            prefs[PreferencesKeys.ACCESS_TOKEN] = accessToken
            prefs[PreferencesKeys.REFRESH_TOKEN] = refreshToken
        }
    }

    /**
     * Save user info.
     */
    suspend fun saveUser(user: User) {
        context.dataStore.edit { prefs ->
            prefs[PreferencesKeys.USER_ID] = user.id.toString()
            prefs[PreferencesKeys.USER_NAME] = user.displayName
        }
    }

    /**
     * Clear all auth data (logout).
     */
    suspend fun clearAuth() {
        context.dataStore.edit { prefs ->
            prefs.remove(PreferencesKeys.ACCESS_TOKEN)
            prefs.remove(PreferencesKeys.REFRESH_TOKEN)
            prefs.remove(PreferencesKeys.USER_ID)
            prefs.remove(PreferencesKeys.USER_NAME)
        }
    }

    /**
     * Check if user is logged in.
     */
    val isLoggedIn: Flow<Boolean> = context.dataStore.data.map { prefs ->
        !prefs[PreferencesKeys.ACCESS_TOKEN].isNullOrBlank()
    }

    /**
     * Get current user display name.
     */
    val userName: Flow<String?> = context.dataStore.data.map { prefs ->
        prefs[PreferencesKeys.USER_NAME]
    }

    /**
     * Refresh the access token using stored refresh token.
     * Returns the new access token or null if refresh failed.
     */
    suspend fun refreshAccessToken(): String? {
        val refreshToken = getRefreshToken() ?: return null
        
        return try {
            val response = api.refreshToken(RefreshRequest(refreshToken))
            if (response.isSuccessful) {
                val body = response.body()!!
                saveTokens(body.accessToken, body.refreshToken)
                body.accessToken
            } else {
                // Refresh failed, clear auth
                clearAuth()
                null
            }
        } catch (e: Exception) {
            null
        }
    }

    /**
     * Generate a login code for TV auth.
     */
    suspend fun generateLoginCode(): Result<LoginCodeResponse> {
        return try {
            val response = api.generateLoginCode()
            if (response.isSuccessful) {
                Result.success(response.body()!!)
            } else {
                val errorMsg = response.errorBody()?.string() ?: "Unknown error"
                Result.failure(Exception("HTTP ${response.code()}: $errorMsg"))
            }
        } catch (e: Exception) {
            Result.failure(e)
        }
    }

    /**
     * Verify login code and get tokens.
     */
    suspend fun verifyLoginCode(code: String): Result<AuthResponse> {
        return try {
            val response = api.verifyCode(VerifyCodeRequest(code))
        when (response.code()) {
            200 -> {
                val auth = response.body()!!
                saveTokens(auth.accessToken, auth.refreshToken)
                saveUser(auth.user)
                Result.success(auth)
            }
            202 -> Result.failure(Exception("Code not yet confirmed"))
            404 -> Result.failure(Exception("Code not yet confirmed"))
            410 -> Result.failure(Exception("Code expired or already used on another device"))
            429 -> Result.failure(Exception("Too many requests. Please wait a moment."))
            else -> Result.failure(Exception("Verification failed"))
        }
        } catch (e: Exception) {
            Result.failure(e)
        }
    }

    /**
     * Logout user.
     */
    suspend fun logout() {
        try {
            api.logout()
        } catch (e: Exception) {
            // Ignore logout API errors
        }
        clearAuth()
    }

    /**
     * Get bot info for the login screen.
     */
    suspend fun getBotInfo(): Result<BotInfo> {
        return try {
            val response = api.getBotInfo()
            if (response.isSuccessful) {
                Result.success(response.body()!!)
            } else {
                Result.failure(Exception("Failed to fetch bot info"))
            }
        } catch (e: Exception) {
            Result.failure(e)
        }
    }
}
