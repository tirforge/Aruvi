package com.aruvi.tir.data.model

import com.google.gson.annotations.SerializedName

/**
 * Request model for updating a file (rename, move).
 */
data class FileUpdate(
    @SerializedName("file_name") val fileName: String? = null,
    @SerializedName("folder_id") val folderId: Int? = null
)

/**
 * Request model for creating a folder.
 */
data class FolderCreate(
    @SerializedName("name") val name: String,
    @SerializedName("parent_id") val parentId: Int? = null
)

/**
 * Request model for updating a folder (rename, move).
 */
data class FolderUpdate(
    @SerializedName("name") val name: String? = null,
    @SerializedName("parent_id") val parentId: Int? = null
)
