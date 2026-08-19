package com.aruvi.tir.data.model

import com.google.gson.annotations.SerializedName

// ── Request Models ─────────────────────────────────────────────────────

data class GrabSearchRequest(
    @SerializedName("query") val query: String,
    @SerializedName("group_username") val groupUsername: String? = null,
    @SerializedName("bot_username") val botUsername: String? = null,
)

data class GrabSelectRequest(
    @SerializedName("query") val query: String,
    @SerializedName("row") val row: Int,
    @SerializedName("col") val col: Int,
    @SerializedName("msg_id") val msgId: Int? = null,
    @SerializedName("chat_id") val chatId: Int? = null,
    @SerializedName("group_username") val groupUsername: String? = null,
    @SerializedName("bot_username") val botUsername: String? = null,
)

// ── Response Models ────────────────────────────────────────────────────

data class GrabSearchResult(
    @SerializedName("label") val label: String,
    @SerializedName("row") val row: Int,
    @SerializedName("col") val col: Int,
    @SerializedName("msg_id") val msgId: Int,
    @SerializedName("file_name") val fileName: String,
    @SerializedName("file_size") val fileSize: Long,
)

data class GrabSearchResponse(
    @SerializedName("results") val results: List<GrabSearchResult>,
    @SerializedName("group_username") val groupUsername: String,
    @SerializedName("bot_username") val botUsername: String,
    @SerializedName("group_chat_id") val groupChatId: Long? = null,
)

data class GrabSelectResponse(
    @SerializedName("name") val name: String,
    @SerializedName("size") val size: Long,
    @SerializedName("stream_url") val streamUrl: String,
    @SerializedName("id") val id: Int? = null,
    @SerializedName("file_id") val fileId: String? = null,
    @SerializedName("file_unique_id") val fileUniqueId: String? = null,
)
