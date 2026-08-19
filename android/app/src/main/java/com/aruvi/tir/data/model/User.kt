package com.aruvi.tir.data.model

import com.google.gson.annotations.SerializedName

/**
 * User data model.
 */
data class User(
    @SerializedName("id") val id: Int,
    @SerializedName("telegram_id") val telegramId: Long,
    @SerializedName("username") val username: String?,
    @SerializedName("first_name") val firstName: String?,
    @SerializedName("last_name") val lastName: String?,
    @SerializedName("created_at") val createdAt: String,
    @SerializedName("last_active") val lastActive: String
) {
    val displayName: String
        get() = when {
            firstName != null && lastName != null -> "$firstName $lastName"
            firstName != null -> firstName
            username != null -> "@$username"
            else -> "User $telegramId"
        }
}
