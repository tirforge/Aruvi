package com.aruvi.tir.data.model

import com.google.gson.annotations.SerializedName

/**
 * TV-specific API responses optimized for home screen.
 */

/**
 * TV Browse response - returns all data needed for home screen in one call.
 */
data class TVBrowseResponse(
    @SerializedName("continue_watching") val continueWatching: List<FileItem>,
    @SerializedName("recent") val recentFiles: List<FileItem>,
    @SerializedName("folders") val folders: List<Folder>
)

/**
 * Search result response.
 */
data class SearchResponse(
    @SerializedName("query") val query: String,
    @SerializedName("results") val results: List<FileItem>,
    @SerializedName("total") val total: Int
)

/**
 * Lightweight revision snapshot (/api/tv/revision): three max-timestamps the
 * client compares to decide whether refetching the full browse payload is
 * needed. NULL when a table is empty.
 */
data class TVRevisionResponse(
    @SerializedName("files_created_at") val filesCreatedAt: String?,
    @SerializedName("files_updated_at") val filesUpdatedAt: String?,
    @SerializedName("folders_updated_at") val foldersUpdatedAt: String?
)
