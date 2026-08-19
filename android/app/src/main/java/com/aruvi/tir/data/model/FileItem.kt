package com.aruvi.tir.data.model

import com.google.gson.annotations.SerializedName
import java.text.DecimalFormat
import kotlin.math.log10
import kotlin.math.pow

/**
 * File item from the backend API.
 */
data class FileItem(
    @SerializedName("id") val id: Int,
    @SerializedName("user_id") val userId: Int,
    @SerializedName("folder_id") val folderId: Int?,
    @SerializedName("file_id") val fileId: String,
    @SerializedName("file_unique_id") val fileUniqueId: String,
    @SerializedName("channel_message_id") val channelMessageId: Long,
    @SerializedName("file_name") val fileName: String,
    @SerializedName("file_size") val fileSize: Long,
    @SerializedName("mime_type") val mimeType: String?,
    @SerializedName("file_type") val fileType: String,
    @SerializedName("duration") val duration: Double?,
    @SerializedName("width") val width: Int?,
    @SerializedName("height") val height: Int?,
    @SerializedName("thumbnail_file_id") val thumbnailFileId: String?,
    @SerializedName("public_hash") val publicHash: String?,
    @SerializedName("created_at") val createdAt: String,
    @SerializedName("updated_at") val updatedAt: String,
    // Watch progress (optional, returned in TV browse responses)
    @SerializedName("progress") val watchProgress: Int? = null,
    @SerializedName("progress_updated") val progressUpdated: String? = null
) {
    /**
     * Human-readable file size (e.g., "1.5 GB").
     */
    val formattedSize: String
        get() {
            if (fileSize <= 0) return "0 B"
            val units = arrayOf("B", "KB", "MB", "GB", "TB")
            val digitGroups = (log10(fileSize.toDouble()) / log10(1024.0)).toInt()
            return DecimalFormat("#,##0.#").format(
                fileSize / 1024.0.pow(digitGroups.toDouble())
            ) + " " + units[digitGroups]
        }

    /**
     * Duration in seconds as Int (for calculations).
     */
    val durationSeconds: Int
        get() = duration?.toInt() ?: 0

    /**
     * Human-readable duration (e.g., "1:23:45").
     */
    val formattedDuration: String?
        get() {
            val seconds = durationSeconds
            if (seconds <= 0) return null
            val hours = seconds / 3600
            val minutes = (seconds % 3600) / 60
            val secs = seconds % 60
            return if (hours > 0) {
                String.format("%d:%02d:%02d", hours, minutes, secs)
            } else {
                String.format("%d:%02d", minutes, secs)
            }
        }

    /**
     * Resolution string (e.g., "1920x1080").
     */
    val resolution: String?
        get() = if (width != null && height != null) "${width}x${height}" else null

    /**
     * Check if this is a video file.
     */
    val isVideo: Boolean
        get() = fileType == "video" || mimeType?.startsWith("video/") == true

    /**
     * Check if this is an audio file.
     */
    val isAudio: Boolean
        get() = fileType == "audio" || mimeType?.startsWith("audio/") == true

    /**
     * Check if this is playable media (video or audio).
     */
    val isPlayable: Boolean
        get() = isVideo || isAudio

    /**
     * Watch progress as percentage (0-100).
     */
    val progressPercent: Float
        get() {
            val prog = watchProgress ?: return 0f
            val dur = duration ?: return 0f
            if (dur <= 0.0) return 0f
            return (prog.toFloat() / dur.toFloat() * 100f).coerceIn(0f, 100f)
        }
}

/**
 * Paginated response wrapper for files.
 */
data class PaginatedResponse<T>(
    @SerializedName("files") val items: List<T>,
    @SerializedName("total") val total: Int,
    @SerializedName("page") val page: Int,
    @SerializedName("per_page") val perPage: Int
)
