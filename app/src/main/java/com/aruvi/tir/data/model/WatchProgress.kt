package com.aruvi.tir.data.model

import com.google.gson.annotations.SerializedName

/**
 * Watch progress tracking.
 */
data class WatchProgress(
    @SerializedName("id") val id: Int,
    @SerializedName("user_id") val userId: Int,
    @SerializedName("file_id") val fileId: Int,
    @SerializedName("position") val position: Int, // seconds
    @SerializedName("duration") val duration: Int?,
    @SerializedName("completed") val completed: Boolean,
@SerializedName("updated_at") val updatedAt: String? = null
) {
    /**
     * Human-readable position (e.g., "1:23:45").
     */
    val formattedPosition: String
        get() {
            val seconds = position
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
     * Progress as percentage (0-100).
     */
    val progressPercent: Float
        get() {
            val dur = duration ?: return 0f
            if (dur == 0) return 0f
            return (position.toFloat() / dur.toFloat() * 100f).coerceIn(0f, 100f)
        }
}

/**
 * Request to update watch progress.
 */
data class WatchProgressUpdate(
    @SerializedName("position") val position: Int,
    @SerializedName("duration") val duration: Int?,
    @SerializedName("completed") val completed: Boolean = false
)
