package com.aruvi.tir.download

import android.content.Context
import android.os.Environment
import com.aruvi.tir.service.DownloadService
import kotlinx.coroutines.*
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import okhttp3.OkHttpClient
import okhttp3.Request
import java.io.File
import java.io.RandomAccessFile
import java.util.concurrent.ConcurrentHashMap
import java.util.concurrent.atomic.AtomicLong

/**
 * Status for each download task.
 */
enum class DownloadStatus {
    PENDING,
    RUNNING,
    PAUSED,
    COMPLETED,
    FAILED,
    CANCELLED
}

/**
 * Represents one download task with its current state.
 */
data class DownloadTask(
    val id: Long,
    val fileId: Int,
    val fileName: String,
    val url: String,
    val mimeType: String? = null,
    val status: DownloadStatus = DownloadStatus.PENDING,
    val downloadedBytes: Long = 0L,
    val totalBytes: Long = -1L,
    val speed: Long = 0L, // bytes per second
    val error: String? = null,
    val localPath: String? = null
)

/**
 * Custom file downloader that supports true pause/resume using HTTP Range headers.
 *
 * Uses OkHttp for HTTP requests and RandomAccessFile for writing at specific offsets.
 * Downloads are saved to the device's public Downloads directory.
 */
class FileDownloader(
    private val context: Context,
    private val okHttpClient: OkHttpClient,
    private val scope: CoroutineScope
) {
    private val _tasks = MutableStateFlow<Map<Long, DownloadTask>>(emptyMap())
    val tasks: StateFlow<Map<Long, DownloadTask>> = _tasks.asStateFlow()

    private val activeJobs = ConcurrentHashMap<Long, Job>()
    private val nextId = AtomicLong(1L)

    // Speed tracking
    private val lastBytesMap = ConcurrentHashMap<Long, Long>()
    private val lastTimeMap = ConcurrentHashMap<Long, Long>()

    /**
     * Enqueue a new download. Returns the download task ID.
     */
    fun enqueue(fileId: Int, fileName: String, url: String, mimeType: String? = null): Long {
        val id = nextId.getAndIncrement()
        val downloadsDir = Environment.getExternalStoragePublicDirectory(Environment.DIRECTORY_DOWNLOADS)
        val localPath = File(downloadsDir, fileName).absolutePath

        val task = DownloadTask(
            id = id,
            fileId = fileId,
            fileName = fileName,
            url = url,
            mimeType = mimeType,
            status = DownloadStatus.PENDING,
            localPath = localPath
        )

        updateTask(task)
        startDownload(task)

        // Start foreground service to keep downloads alive in background
        try { DownloadService.start(context) } catch (_: Exception) {}

        return id
    }

    /**
     * Pause a running download.
     */
    fun pause(id: Long) {
        val task = _tasks.value[id] ?: return
        if (task.status != DownloadStatus.RUNNING && task.status != DownloadStatus.PENDING) return

        // Cancel the coroutine job - this stops the download loop
        activeJobs[id]?.cancel()
        activeJobs.remove(id)
        lastBytesMap.remove(id)
        lastTimeMap.remove(id)

        // Update status - the partial file remains on disk
        updateTask(task.copy(status = DownloadStatus.PAUSED, speed = 0L))
    }

    /**
     * Resume a paused download from where it left off.
     */
    fun resume(id: Long) {
        val task = _tasks.value[id] ?: return
        if (task.status != DownloadStatus.PAUSED && task.status != DownloadStatus.FAILED) return

        // Check how many bytes are already on disk
        val file = File(task.localPath ?: return)
        val existingBytes = if (file.exists()) file.length() else 0L

        val updatedTask = task.copy(
            status = DownloadStatus.PENDING,
            downloadedBytes = existingBytes,
            error = null
        )
        updateTask(updatedTask)
        startDownload(updatedTask)

        // Start foreground service to keep downloads alive in background
        try { DownloadService.start(context) } catch (_: Exception) {}
    }

    /**
     * Cancel and remove a download, deleting any partial file.
     */
    fun cancel(id: Long) {
        activeJobs[id]?.cancel()
        activeJobs.remove(id)
        lastBytesMap.remove(id)
        lastTimeMap.remove(id)

        val task = _tasks.value[id]
        task?.localPath?.let { path ->
            val file = File(path)
            if (file.exists() && task.status != DownloadStatus.COMPLETED) {
                file.delete()
            }
        }

        val currentTasks = _tasks.value.toMutableMap()
        currentTasks.remove(id)
        _tasks.value = currentTasks
    }

    /**
     * Delete a completed download's file.
     */
    fun deleteFile(id: Long) {
        val task = _tasks.value[id] ?: return
        task.localPath?.let { path ->
            File(path).delete()
        }
        val currentTasks = _tasks.value.toMutableMap()
        currentTasks.remove(id)
        _tasks.value = currentTasks
    }

    /**
     * Start the actual download coroutine for a task.
     */
    private fun startDownload(task: DownloadTask) {
        val job = scope.launch(Dispatchers.IO) {
            try {
                val file = File(task.localPath ?: return@launch)
                file.parentFile?.mkdirs()

                // Determine how many bytes we already have (for resume)
                val existingBytes = if (file.exists()) file.length() else 0L

                // Build request with Range header if resuming
                val requestBuilder = Request.Builder().url(task.url)
                if (existingBytes > 0) {
                    requestBuilder.addHeader("Range", "bytes=$existingBytes-")
                }

                val response = okHttpClient.newCall(requestBuilder.build()).execute()

                if (!response.isSuccessful && response.code != 206) {
                    updateTask(task.copy(
                        status = DownloadStatus.FAILED,
                        error = "HTTP ${response.code}: ${response.message}"
                    ))
                    return@launch
                }

                val body = response.body ?: run {
                    updateTask(task.copy(
                        status = DownloadStatus.FAILED,
                        error = "Empty response body"
                    ))
                    return@launch
                }

                // Calculate total size
                val contentLength = body.contentLength()
                val totalBytes = if (response.code == 206) {
                    // Partial content - total = existing + remaining
                    existingBytes + contentLength
                } else {
                    // Full response (server didn't support Range, or fresh download)
                    contentLength
                }

                val startOffset = if (response.code == 206) existingBytes else 0L

                updateTask(task.copy(
                    status = DownloadStatus.RUNNING,
                    downloadedBytes = startOffset,
                    totalBytes = totalBytes
                ))

// Write using RandomAccessFile for seek support
val buffer = ByteArray(65536) // 64KB buffer for good throughput
var bytesWritten = startOffset
val inputStream = body.byteStream()

lastBytesMap[task.id] = bytesWritten
lastTimeMap[task.id] = System.currentTimeMillis()
var lastUpdateTime = System.currentTimeMillis()

inputStream.use { stream ->
    RandomAccessFile(file, "rw").use { raf ->
        raf.seek(startOffset)

        while (isActive) {
            val bytesRead = stream.read(buffer)
            if (bytesRead == -1) break

            raf.write(buffer, 0, bytesRead)
            bytesWritten += bytesRead

            // Throttle UI updates to every 500ms to avoid excessive StateFlow emissions
            val now = System.currentTimeMillis()
            if (now - lastUpdateTime >= 500) {
                val lastBytes = lastBytesMap[task.id] ?: bytesWritten
                val lastTime = lastTimeMap[task.id] ?: now
                val timeDelta = (now - lastTime).coerceAtLeast(1)
                val speed = ((bytesWritten - lastBytes) * 1000) / timeDelta

                lastBytesMap[task.id] = bytesWritten
                lastTimeMap[task.id] = now
                lastUpdateTime = now

                updateTask(_tasks.value[task.id]?.copy(
                    status = DownloadStatus.RUNNING,
                    downloadedBytes = bytesWritten,
                    totalBytes = totalBytes,
                    speed = speed
                ) ?: return@launch)
            }
        }
    }
}

response.close()

                // Check if completed or cancelled
                if (isActive) {
                    updateTask(_tasks.value[task.id]?.copy(
                        status = DownloadStatus.COMPLETED,
                        downloadedBytes = bytesWritten,
                        totalBytes = if (totalBytes > 0) totalBytes else bytesWritten,
                        speed = 0L
                    ) ?: return@launch)
                }

            } catch (e: CancellationException) {
                // Paused by user - don't update to FAILED
                throw e
            } catch (e: Exception) {
                updateTask(_tasks.value[task.id]?.copy(
                    status = DownloadStatus.FAILED,
                    error = e.message ?: "Download failed",
                    speed = 0L
                ) ?: return@launch)
            } finally {
                activeJobs.remove(task.id)
                lastBytesMap.remove(task.id)
                lastTimeMap.remove(task.id)
            }
        }

        activeJobs[task.id] = job
    }

private fun updateTask(task: DownloadTask) {
        _tasks.value = _tasks.value + (task.id to task)
}
}
