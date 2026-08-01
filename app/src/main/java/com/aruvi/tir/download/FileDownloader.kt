package com.aruvi.tir.download

import android.content.ContentValues
import android.content.Context
import android.net.Uri
import android.os.Build
import android.os.Environment
import android.provider.MediaStore
import com.aruvi.tir.service.DownloadService
import kotlinx.coroutines.*
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import okhttp3.OkHttpClient
import okhttp3.Request
import java.io.File
import java.io.IOException
import java.io.RandomAccessFile
import java.util.concurrent.ConcurrentHashMap
import java.util.concurrent.atomic.AtomicLong
import kotlin.coroutines.coroutineContext

/** Transient transport failure - safe to retry with a Range resume from the partial file. */
private class DownloadRetryableException(message: String) : Exception(message)

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
 * Downloads are saved to the device's public Downloads directory via MediaStore on
 * API 29+ (scoped storage) and via the raw public Downloads path on API 28 and below.
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

    // Retry policy for transient network failures (flaky mobile data).
    // Each attempt resumes from the partial file via a Range header.
    private val maxAttempts = 10
    private val retryDelayMs = 5_000L

    /**
     * Enqueue a new download. Returns the download task ID.
     */
    fun enqueue(fileId: Int, fileName: String, url: String, mimeType: String? = null): Long {
        val id = nextId.getAndIncrement()
        val localPath = createDestination(fileName, mimeType)

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
     * Reserve a destination for the download. On API 29+ a MediaStore.Downloads row is
     * created (scoped storage forbids raw writes to public Downloads); below that the
     * legacy raw file path is used.
     */
    private fun createDestination(fileName: String, mimeType: String?): String {
        if (Build.VERSION.SDK_INT >= 29) {
            val values = ContentValues().apply {
                put(MediaStore.Downloads.DISPLAY_NAME, fileName)
                put(MediaStore.Downloads.MIME_TYPE, mimeType)
                put(MediaStore.Downloads.RELATIVE_PATH, Environment.DIRECTORY_DOWNLOADS)
                put(MediaStore.Downloads.IS_PENDING, 1)
            }
            val uri = context.contentResolver.insert(
                MediaStore.Downloads.EXTERNAL_CONTENT_URI, values
            )
            if (uri != null) return uri.toString()
        }
        return legacyPath(fileName)
    }

    private fun legacyPath(fileName: String): String =
        File(Environment.getExternalStoragePublicDirectory(Environment.DIRECTORY_DOWNLOADS), fileName).absolutePath

    private fun isContentUri(task: DownloadTask): Boolean =
        task.localPath?.startsWith("content://") == true

    /** Bytes already on disk for resume support, for either destination kind. */
    private fun existingBytes(task: DownloadTask): Long {
        return try {
            when {
                isContentUri(task) -> {
                    context.contentResolver
                        .openFileDescriptor(Uri.parse(task.localPath), "r")
                        ?.use { it.statSize ?: 0L } ?: 0L
                }
                else -> {
                    val path = task.localPath ?: return 0L
                    val file = File(path)
                    if (file.exists()) file.length() else 0L
                }
            }
        } catch (_: Exception) {
            0L // Stale/phantom MediaStore row or unreadable file - treat as fresh start
        }
    }

    /** Delete the destination row/file, if any. */
    private fun deleteDestination(task: DownloadTask) {
        val path = task.localPath ?: return
        if (isContentUri(task)) {
            context.contentResolver.delete(Uri.parse(path), null, null)
        } else {
            val file = File(path)
            if (file.exists()) file.delete()
        }
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
        val existing = existingBytes(task)

        val updatedTask = task.copy(
            status = DownloadStatus.PENDING,
            downloadedBytes = existing,
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
        if (task != null && task.status != DownloadStatus.COMPLETED) {
            deleteDestination(task)
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
        deleteDestination(task)
        val currentTasks = _tasks.value.toMutableMap()
        currentTasks.remove(id)
        _tasks.value = currentTasks
    }

    /**
     * Start the actual download coroutine for a task. Transient network failures are
     * retried automatically - each attempt resumes from the partial file - so a flaky
     * connection keeps making progress instead of dying after a few MB.
     */
    private fun startDownload(task: DownloadTask) {
        val job = scope.launch(Dispatchers.IO) {
            try {
                var attempt = 0
                while (isActive) {
                    try {
                        attempt++
                        if (downloadAttempt(task)) break
                        // Permanent failure (already reported to the task) or the
                        // task/job is gone - stop trying.
                        return@launch
                    } catch (e: CancellationException) {
                        // Paused/cancelled by user - don't retry or mark FAILED
                        throw e
                    } catch (e: DownloadRetryableException) {
                        if (!isActive || attempt >= maxAttempts) {
                            if (isActive) {
                                updateTask(_tasks.value[task.id]?.copy(
                                    status = DownloadStatus.FAILED,
                                    error = e.message ?: "Download failed",
                                    speed = 0L
                                ) ?: return@launch)
                            }
                            return@launch
                        }
                        // Backoff, then resume from the partial file
                        delay(minOf(retryDelayMs * attempt, 30_000L))
                    } catch (e: Exception) {
                        updateTask(_tasks.value[task.id]?.copy(
                            status = DownloadStatus.FAILED,
                            error = e.message ?: "Download failed",
                            speed = 0L
                        ) ?: return@launch)
                        return@launch
                    }
                }
            } finally {
                activeJobs.remove(task.id)
                lastBytesMap.remove(task.id)
                lastTimeMap.remove(task.id)
            }
        }
        activeJobs[task.id] = job
    }

    /**
     * One download attempt. Returns true when the file is fully downloaded, false on
     * permanent failure (already reported to the task), and throws
     * [DownloadRetryableException] on transient transport errors.
     */
    private suspend fun downloadAttempt(task: DownloadTask): Boolean {
        val contentUri = task.localPath?.takeIf { it.startsWith("content://") }

        // Determine how many bytes we already have (for resume)
        val existing = existingBytes(task)

        // Build request with Range header if resuming
        val requestBuilder = Request.Builder().url(task.url)
        if (existing > 0) {
            requestBuilder.addHeader("Range", "bytes=$existing-")
        }

        try {
            val response = okHttpClient.newCall(requestBuilder.build()).execute()

            if (!response.isSuccessful && response.code != 206) {
                val retryable = response.code == 429 || response.code >= 500
                response.close()
                if (retryable) {
                    throw DownloadRetryableException("HTTP ${response.code}: ${response.message}")
                }
                updateTask(task.copy(
                    status = DownloadStatus.FAILED,
                    error = "HTTP ${response.code}: ${response.message}"
                ))
                return false
            }

            val body = response.body ?: run {
                updateTask(task.copy(
                    status = DownloadStatus.FAILED,
                    error = "Empty response body"
                ))
                return false
            }

            // Calculate total size
            val contentLength = body.contentLength()
            val totalBytes = if (response.code == 206) {
                // Partial content - total = existing + remaining
                existing + contentLength
            } else {
                // Full response (server didn't support Range, or fresh download)
                contentLength
            }

            val startOffset = if (response.code == 206) existing else 0L

            updateTask(task.copy(
                status = DownloadStatus.RUNNING,
                downloadedBytes = startOffset,
                totalBytes = totalBytes
            ))

            // Open d/ Open destination: MediaStore row via content resolver (API 29+),
            // otherwise the raw file. RandomAccessFile supports both paths.
            val output: java.nio.channels.FileChannel = if (contentUri != null) {
                val pfd = context.contentResolver.openFileDescriptor(
                    Uri.parse(contentUri), if (startOffset > 0) "rw" else "w"
                ) ?: return false
                java.io.FileOutputStream(pfd.fileDescriptor).channel
            } else {
                val file = File(task.localPath ?: return false)
                file.parentFile?.mkdirs()
                RandomAccessFile(file, "rw").channel
            }

            // Write using RandomAccessFile for seek support
            val buffer = ByteArray(65536) // 64KB buffer for good throughput
            var bytesWritten = startOffset
            val inputStream = body.byteStream()

            lastBytesMap[task.id] = bytesWritten
            lastTimeMap[task.id] = System.currentTimeMillis()
            var lastUpdateTime = System.currentTimeMillis()

            inputStream.use { stream ->
                output.use { channel ->
                    channel.position(startOffset)

                    while (coroutineContext.isActive) {
                        val bytesRead = stream.read(buffer)
                        if (bytesRead == -1) break

                        channel.write(java.nio.ByteBuffer.wrap(buffer, 0, bytesRead))
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
                            ) ?: return false)
                        }
                    }
                }
            }

            response.close()

            // Check if completed or cancelled
            if (!coroutineContext.isActive) return false

            // Publish the MediaStore entry so it shows up in the Downloads app
            if (contentUri != null) {
                context.contentResolver.update(
                    Uri.parse(contentUri),
                    ContentValues().apply { put(MediaStore.Downloads.IS_PENDING, 0) },
                    null, null
                )
            }
            updateTask(_tasks.value[task.id]?.copy(
                status = DownloadStatus.COMPLETED,
                downloadedBytes = bytesWritten,
                totalBytes = if (totalBytes > 0) totalBytes else bytesWritten,
                speed = 0L
            ) ?: return false)
            return true
        } catch (e: CancellationException) {
            throw e
        } catch (e: IOException) {
            // Transport errors (socket reset, timeout, DNS) - the partial file stays
            // on disk so the next attempt resumes with a Range header.
            throw DownloadRetryableException(e.message ?: "Network error")
        }
    }

    private fun updateTask(task: DownloadTask) {
        _tasks.value = _tasks.value + (task.id to task)
    }
}
