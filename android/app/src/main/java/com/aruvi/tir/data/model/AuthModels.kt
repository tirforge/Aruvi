package com.aruvi.tir.data.model

import com.google.gson.annotations.SerializedName

/**
 * Authentication models.
 */

// Login code request (TV generates a code, user enters it in Telegram bot)
data class LoginCodeResponse(
    @SerializedName("code") val code: String,
    @SerializedName("expires_at") val expiresAt: String,
    @SerializedName("bot_username") val botUsername: String? = null,
    @SerializedName("bot_name") val botName: String? = null
)

// Verify login code. wait>0 asks the server to long-poll (hold the request
// until the code is claimed or wait seconds elapse) so login completes
// ~300ms after the user taps Start in the bot.
data class VerifyCodeRequest(
    @SerializedName("code") val code: String,
    @SerializedName("wait") val wait: Int = 0
)

// Auth response with tokens
data class AuthResponse(
    @SerializedName("access_token") val accessToken: String,
    @SerializedName("refresh_token") val refreshToken: String,
    @SerializedName("token_type") val tokenType: String,
    @SerializedName("expires_in") val expiresIn: Int? = null,
    @SerializedName("user") val user: User
)

// Token refresh request
data class RefreshRequest(
    @SerializedName("refresh_token") val refreshToken: String
)

// Token refresh response
data class RefreshResponse(
    @SerializedName("access_token") val accessToken: String,
    @SerializedName("refresh_token") val refreshToken: String,
    @SerializedName("token_type") val tokenType: String,
    @SerializedName("expires_in") val expiresIn: Int? = null
)

data class BotInfo(
    @SerializedName("username") val username: String,
    @SerializedName("name") val name: String?,
    @SerializedName("server_version") val serverVersion: String
)
