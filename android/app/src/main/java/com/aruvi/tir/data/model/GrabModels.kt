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
    // REQUIRED by the backend: without a name the delivered file cannot be
    // verified, and positional-only matching can grab the WRONG movie when
    // the menu page/depth guess is off.
    @SerializedName("file_name") val fileName: String,
    @SerializedName("depth") val depth: Int? = null,
)

// ── Response Models ────────────────────────────────────────────────────

data class GrabSearchResult(
    @SerializedName("label") val label: String,
    @SerializedName("row") val row: Int,
    @SerializedName("col") val col: Int,
    @SerializedName("msg_id") val msgId: Int,
    @SerializedName("file_name") val fileName: String,
    @SerializedName("file_size") val fileSize: Long,
    // Page depth + owning group — without these, a page-2 selection is
    // matched positionally against page 1 and the wrong file is grabbed.
    @SerializedName("depth") val depth: Int = 0,
    @SerializedName("group_username") val groupUsername: String? = null,
    @SerializedName("chat_id") val chatId: Long? = null,
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
