package com.aruvi.tir.data.model

import com.google.gson.annotations.SerializedName

/**
 * Authentication models.
 */

// Login code request (TV generates a code, user enters it in Telegram bot)
data class LoginCodeResponse(
    @SerializedName("code") val code: String,
    @SerializedName("expires_at") val expiresAt: String
)

// Verify login code
data class VerifyCodeRequest(
    @SerializedName("code") val code: String
)

// Auth response with tokens
data class AuthResponse(
    @SerializedName("access_token") val accessToken: String,
    @SerializedName("refresh_token") val refreshToken: String,
    @SerializedName("token_type") val tokenType: String,
    @SerializedName("expires_in") val expiresIn: Int,
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
    @SerializedName("expires_in") val expiresIn: Int
)

data class BotInfo(
    @SerializedName("username") val username: String,
    @SerializedName("name") val name: String?,
    @SerializedName("server_version") val serverVersion: String
)
