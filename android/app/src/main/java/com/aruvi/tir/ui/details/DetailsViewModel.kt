package com.aruvi.tir.ui.details

import android.app.DownloadManager
import android.content.Context
import android.net.Uri
import android.os.Environment
import android.widget.Toast
import androidx.lifecycle.SavedStateHandle
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.aruvi.tir.data.model.FileItem
import com.aruvi.tir.data.model.WatchProgress
import com.aruvi.tir.data.repository.FilesRepository
import com.aruvi.tir.data.repository.SettingsRepository
import dagger.hilt.android.lifecycle.HiltViewModel
import com.aruvi.tir.download.DownloadStatus
import kotlinx.coroutines.Job
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.catch
import kotlinx.coroutines.flow.map
import kotlinx.coroutines.launch
import java.io.File
import javax.inject.Inject

/**
 * Details screen UI state.
 */
data class DetailsUiState(
    val isLoading: Boolean = true,
    val file: FileItem? = null,
    val watchProgress: WatchProgress? = null,
    val serverUrl: String = "",
    val error: String? = null,
    val downloadStarted: Boolean = false,
    val downloadId: Long? = null,
    val downloadStatus: Int? = null,
    val downloadProgress: Int = 0,
    // New fields for enhanced download UI
    val downloadedBytes: Long = 0L,
    val totalBytes: Long = -1L,
    val downloadSpeed: Long = 0L,        // bytes per second
    val localFilePath: String? = null,    // path to downloaded file
    val isFileLocal: Boolean = false      // whether file exists locally
)

/**
 * ViewModel for the file details screen.
 */
@HiltViewModel
class DetailsViewModel @Inject constructor(
    savedStateHandle: SavedStateHandle,
    private val filesRepository: FilesRepository,
    private val settingsRepository: SettingsRepository,
    private val fileDownloader: com.aruvi.tir.download.FileDownloader
) : ViewModel() {

    private val fileId: Int = savedStateHandle.get<Int>("fileId") ?: 0

    private val _uiState = MutableStateFlow(DetailsUiState())
    val uiState: StateFlow<DetailsUiState> = _uiState.asStateFlow()

    private var downloadJob: Job? = null

    init {
        loadFileDetails()
    }

    /**
     * Load file details and watch progress.
     */
    fun loadFileDetails() {
        viewModelScope.launch {
            _uiState.value = _uiState.value.copy(isLoading = true, error = null)

            val serverUrl = settingsRepository.getServerUrl()
            _uiState.value = _uiState.value.copy(serverUrl = serverUrl)

            // Load file details
            val fileResult = filesRepository.getFile(fileId)
            fileResult.fold(
                onSuccess = { file ->
                    _uiState.value = _uiState.value.copy(
                        isLoading = false,
                        file = file
                    )
                    // Check if file is already downloaded locally
                    checkLocalFile(file.fileName)
                    // Load watch progress
                    loadWatchProgress()
                },
                onFailure = { e ->
                    _uiState.value = _uiState.value.copy(
                        isLoading = false,
                        error = e.message ?: "Failed to load file details"
                    )
                }
            )
        }
    }

    /**
     * Load watch progress for the file.
     */
    private suspend fun loadWatchProgress() {
        val progressResult = filesRepository.getWatchProgress(fileId)
        progressResult.fold(
            onSuccess = { progress ->
                _uiState.value = _uiState.value.copy(watchProgress = progress)
            },
            onFailure = {
                // Ignore - no progress saved yet
            }
        )
    }

    /**
     * Check if the file already exists in local Downloads folder.
     */
    private fun checkLocalFile(fileName: String) {
        val downloadsDir = Environment.getExternalStoragePublicDirectory(
            Environment.DIRECTORY_DOWNLOADS
        )
        val localFile = File(downloadsDir, fileName)
        if (localFile.exists() && localFile.length() > 0) {
            _uiState.value = _uiState.value.copy(
                isFileLocal = true,
                localFilePath = localFile.absolutePath,
                downloadStatus = DownloadManager.STATUS_SUCCESSFUL
            )
        }
    }

    /**
     * Get the resume position in milliseconds, or 0 to start from beginning.
     */
    fun getResumePositionMs(): Long {
        return (_uiState.value.watchProgress?.position ?: 0) * 1000L
    }

    /**
     * Get thumbnail URL.
     */
    fun getThumbnailUrl(): String {
        return "${_uiState.value.serverUrl}/api/stream/$fileId/thumbnail"
    }

    /**
     * Get stream URL.
     */
    fun getStreamUrl(): String {
        return "${_uiState.value.serverUrl}/api/stream/$fileId"
    }

    /**
     * Get local file URI for offline playback.
     */
    fun getLocalFileUri(): Uri? {
        val path = _uiState.value.localFilePath ?: return null
        if (path.startsWith("content://")) return Uri.parse(path)
        val file = File(path)
        return if (file.exists()) Uri.fromFile(file) else null
    }

    /**
     * Delete the locally downloaded file.
     */
    fun deleteLocalFile(context: Context) {
        val path = _uiState.value.localFilePath ?: return
        val file = File(path)

        viewModelScope.launch {
            try {
                val deleted = if (path.startsWith("content://")) {
                    context.contentResolver.delete(Uri.parse(path), null, null) > 0
                } else {
                    file.exists() && file.delete()
                }
                if (deleted) {
                    _uiState.value = _uiState.value.copy(
                        isFileLocal = false,
                        localFilePath = null,
                        downloadStatus = null,
                        downloadStarted = false,
                        downloadId = null,
                        downloadProgress = 0,
                        downloadedBytes = 0L,
                        totalBytes = -1L,
                        downloadSpeed = 0L
                    )
                    Toast.makeText(context, "File deleted", Toast.LENGTH_SHORT).show()
                } else {
                    Toast.makeText(context, "Could not delete file", Toast.LENGTH_SHORT).show()
                }
            } catch (e: Exception) {
                Toast.makeText(context, "Error: ${e.message}", Toast.LENGTH_SHORT).show()
            }
        }
    }

    /**
     * Format bytes to human-readable string.
     */
    fun formatBytes(bytes: Long): String {
        if (bytes <= 0) return "0 B"
        val units = arrayOf("B", "KB", "MB", "GB", "TB")
        val digitGroups = (Math.log(bytes.toDouble()) / Math.log(1024.0)).toInt()
        val index = digitGroups.coerceIn(0, units.size - 1)
        return "%.1f %s".format(bytes / Math.pow(1024.0, index.toDouble()), units[index])
    }

    /**
     * Download file using the custom FileDownloader (supports pause/resume).
     */
    fun startDownload(context: Context) {
        val file = _uiState.value.file ?: return
        val serverUrl = _uiState.value.serverUrl
        if (serverUrl.isBlank()) return

        // Prevent multiple downloads
        if (_uiState.value.downloadStarted) return

        viewModelScope.launch {
            try {
                val url = "$serverUrl/api/stream/$fileId"
                val taskId = fileDownloader.enqueue(fileId, file.fileName, url, file.mimeType)

                _uiState.value = _uiState.value.copy(
                    downloadStarted = true,
                    downloadId = taskId
                )

                downloadJob?.cancel()
                downloadJob = viewModelScope.launch {
                    fileDownloader.tasks
                        .map { tasks -> tasks[taskId] }
                        .catch { emit(null) }
                        .collect { task ->
                            if (task != null) {
                                val progress = if (task.totalBytes > 0)
                                    (task.downloadedBytes * 100 / task.totalBytes).toInt()
                                else 0
                                _uiState.value = _uiState.value.copy(
                                    downloadStatus = when (task.status) {
                                        DownloadStatus.RUNNING -> DownloadManager.STATUS_RUNNING
                                        DownloadStatus.PENDING -> DownloadManager.STATUS_PENDING
                                        DownloadStatus.PAUSED -> DownloadManager.STATUS_PAUSED
                                        DownloadStatus.COMPLETED -> DownloadManager.STATUS_SUCCESSFUL
                                        DownloadStatus.FAILED -> DownloadManager.STATUS_FAILED
                                        DownloadStatus.CANCELLED -> null
                                    },
                                    downloadProgress = progress,
                                    downloadedBytes = task.downloadedBytes,
                                    totalBytes = task.totalBytes,
                                    downloadSpeed = task.speed,
                                    isFileLocal = task.status == DownloadStatus.COMPLETED,
                                    localFilePath = if (task.status == DownloadStatus.COMPLETED) task.localPath else _uiState.value.localFilePath
                                )
                            }
                        }
                }

                Toast.makeText(
                    context,
                    "⬇ Downloading: ${file.fileName}",
                    Toast.LENGTH_SHORT
                ).show()

            } catch (e: Exception) {
                Toast.makeText(
                    context,
                    "Download failed: ${e.message}",
                    Toast.LENGTH_LONG
                ).show()
                _uiState.value = _uiState.value.copy(
                    downloadStarted = false,
                    error = e.message
                )
            }
        }
    }
}
