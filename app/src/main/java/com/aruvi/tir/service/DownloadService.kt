package com.aruvi.tir.service

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.app.Service
import android.content.Context
import android.content.Intent
import android.os.Build
import android.os.IBinder
import androidx.core.app.NotificationCompat
import com.aruvi.tir.R
import com.aruvi.tir.download.DownloadStatus
import com.aruvi.tir.download.DownloadTask
import com.aruvi.tir.download.FileDownloader
import dagger.hilt.android.AndroidEntryPoint
import kotlinx.coroutines.*
import javax.inject.Inject

/**
 * Foreground service that keeps downloads alive when the app is backgrounded.
 *
 * Observes [FileDownloader.tasks] and shows progress notifications for each download.
 * Automatically stops itself when all downloads are complete/paused/failed.
 */
@AndroidEntryPoint
class DownloadService : Service() {

    @Inject
    lateinit var fileDownloader: FileDownloader

private var serviceScope = CoroutineScope(SupervisorJob() + Dispatchers.Main)
    private var observerJob: Job? = null

    companion object {
        private const val CHANNEL_ID = "download_channel"
        private const val SUMMARY_NOTIFICATION_ID = 2000
        private const val NOTIFICATION_ID_BASE = 2001

        fun start(context: Context) {
            val intent = Intent(context, DownloadService::class.java)
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
                context.startForegroundService(intent)
            } else {
                context.startService(intent)
            }
        }

        fun stop(context: Context) {
            context.stopService(Intent(context, DownloadService::class.java))
        }
    }

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onCreate() {
        super.onCreate()
        ensureNotificationChannel()
    }

override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
    // Must call startForeground immediately
    startForeground(SUMMARY_NOTIFICATION_ID, buildSummaryNotification("Preparing downloads..."))

    // Cancel previous scope and recreate to prevent coroutine leaks on restart
    serviceScope.cancel()
    serviceScope = CoroutineScope(SupervisorJob() + Dispatchers.Main)

    // Start observing download tasks
    observerJob?.cancel()
    observerJob = serviceScope.launch {
        fileDownloader.tasks.collect { tasks ->
            updateNotifications(tasks)
        }
    }

    return START_STICKY
}


    private fun updateNotifications(tasks: Map<Long, DownloadTask>) {
        val notificationManager = getSystemService(NotificationManager::class.java)

        val activeDownloads = tasks.values.filter {
            it.status == DownloadStatus.RUNNING || it.status == DownloadStatus.PENDING
        }
        val pausedDownloads = tasks.values.filter { it.status == DownloadStatus.PAUSED }

        // If no active or paused downloads, stop the service
        if (activeDownloads.isEmpty() && pausedDownloads.isEmpty()) {
            // Show completion notification for any just-completed tasks
            val completed = tasks.values.filter { it.status == DownloadStatus.COMPLETED }
            if (completed.isNotEmpty()) {
                val notification = NotificationCompat.Builder(this, CHANNEL_ID)
                    .setSmallIcon(android.R.drawable.stat_sys_download_done)
                    .setContentTitle("Downloads complete")
                    .setContentText("${completed.size} file(s) downloaded")
                    .setPriority(NotificationCompat.PRIORITY_DEFAULT)
                    .setAutoCancel(true)
                    .build()
                notificationManager.notify(SUMMARY_NOTIFICATION_ID + 999, notification)
            }

            stopForeground(STOP_FOREGROUND_REMOVE)
            stopSelf()
            return
        }

        // Update summary notification
        val summaryText = buildString {
            if (activeDownloads.isNotEmpty()) {
                append("${activeDownloads.size} downloading")
            }
            if (pausedDownloads.isNotEmpty()) {
                if (isNotEmpty()) append(", ")
                append("${pausedDownloads.size} paused")
            }
        }
        notificationManager.notify(SUMMARY_NOTIFICATION_ID, buildSummaryNotification(summaryText))

        // Update individual download notifications
        for (task in activeDownloads) {
            val notifId = (NOTIFICATION_ID_BASE + task.id).toInt()
            val progress = if (task.totalBytes > 0) {
                ((task.downloadedBytes * 100) / task.totalBytes).toInt()
            } else 0

            val speedText = formatSpeed(task.speed)
            val sizeText = "${formatBytes(task.downloadedBytes)} / ${formatBytes(task.totalBytes)}"

            val notification = NotificationCompat.Builder(this, CHANNEL_ID)
                .setSmallIcon(android.R.drawable.stat_sys_download)
                .setContentTitle(task.fileName)
                .setContentText("$speedText • $sizeText")
                .setProgress(100, progress, task.totalBytes <= 0)
                .setOngoing(true)
                .setOnlyAlertOnce(true)
                .setPriority(NotificationCompat.PRIORITY_LOW)
                .build()
            notificationManager.notify(notifId, notification)
        }

        // Show paused notifications
        for (task in pausedDownloads) {
            val notifId = (NOTIFICATION_ID_BASE + task.id).toInt()
            val progress = if (task.totalBytes > 0) {
                ((task.downloadedBytes * 100) / task.totalBytes).toInt()
            } else 0

            val notification = NotificationCompat.Builder(this, CHANNEL_ID)
                .setSmallIcon(android.R.drawable.stat_sys_download)
                .setContentTitle(task.fileName)
                .setContentText("Paused • ${progress}%")
                .setProgress(100, progress, false)
                .setOngoing(true)
                .setOnlyAlertOnce(true)
                .setPriority(NotificationCompat.PRIORITY_LOW)
                .build()
            notificationManager.notify(notifId, notification)
        }

        // Clear notifications for completed/failed/cancelled tasks
        val activeIds = (activeDownloads + pausedDownloads).map { (NOTIFICATION_ID_BASE + it.id).toInt() }.toSet()
        // We can't easily enumerate all existing notifications, so completed ones will auto-clear when service stops
    }

    private fun buildSummaryNotification(text: String): Notification {
        return NotificationCompat.Builder(this, CHANNEL_ID)
            .setSmallIcon(android.R.drawable.stat_sys_download)
            .setContentTitle("Aruvi Downloads")
            .setContentText(text)
            .setPriority(NotificationCompat.PRIORITY_LOW)
            .setOngoing(true)
            .setOnlyAlertOnce(true)
            .build()
    }

    private fun ensureNotificationChannel() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            val channel = NotificationChannel(
                CHANNEL_ID,
                "Downloads",
                NotificationManager.IMPORTANCE_LOW
            ).apply {
                description = "Download progress notifications"
                setShowBadge(false)
            }
            val manager = getSystemService(NotificationManager::class.java)
            manager.createNotificationChannel(channel)
        }
    }

    private fun formatSpeed(bytesPerSec: Long): String {
        return when {
            bytesPerSec >= 1_000_000 -> "%.1f MB/s".format(bytesPerSec / 1_000_000.0)
            bytesPerSec >= 1_000 -> "%.0f KB/s".format(bytesPerSec / 1_000.0)
            else -> "$bytesPerSec B/s"
        }
    }

    private fun formatBytes(bytes: Long): String {
        return when {
            bytes < 0 -> "?"
            bytes >= 1_000_000_000 -> "%.1f GB".format(bytes / 1_000_000_000.0)
            bytes >= 1_000_000 -> "%.1f MB".format(bytes / 1_000_000.0)
            bytes >= 1_000 -> "%.0f KB".format(bytes / 1_000.0)
            else -> "$bytes B"
        }
    }

override fun onDestroy() {
    observerJob?.cancel()
    serviceScope.cancel()
    super.onDestroy()
}
}

