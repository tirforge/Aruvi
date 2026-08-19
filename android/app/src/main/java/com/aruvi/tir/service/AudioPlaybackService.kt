package com.aruvi.tir.service

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.content.Intent
import android.os.Build
import androidx.annotation.OptIn
import androidx.core.app.NotificationCompat
import androidx.media3.common.util.UnstableApi
import androidx.media3.exoplayer.ExoPlayer
import androidx.media3.session.MediaSession
import androidx.media3.session.MediaSessionService
import androidx.media3.session.MediaStyleNotificationHelper
import com.aruvi.tir.R
import dagger.hilt.android.AndroidEntryPoint
import javax.inject.Inject

/**
 * Foreground service for background audio playback.
 *
 * Uses Media3's [MediaSessionService] which automatically:
 * - Shows a media notification with play/pause/seek controls
 * - Handles audio focus
 * - Keeps the service alive while audio is playing
 *
 * The service shares the same singleton [ExoPlayer] instance with
 * [PlayerViewModel], so playback state is always in sync.
 */
@AndroidEntryPoint
class AudioPlaybackService : MediaSessionService() {

    @Inject
    lateinit var exoPlayer: ExoPlayer

    private var mediaSession: MediaSession? = null

    companion object {
        private const val CHANNEL_ID = "audio_playback_channel"
        private const val NOTIFICATION_ID = 1001
    }

    @OptIn(UnstableApi::class)
    override fun onCreate() {
        super.onCreate()
        mediaSession = MediaSession.Builder(this, exoPlayer)
            .build()
    }

    @OptIn(UnstableApi::class)
    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        // Must call startForeground() within 5 seconds of startForegroundService()
        ensureNotificationChannel()
        val notification = buildNotification()
        startForeground(NOTIFICATION_ID, notification)

        return super.onStartCommand(intent, flags, startId)
    }

    private fun ensureNotificationChannel() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            val channel = NotificationChannel(
                CHANNEL_ID,
                "Audio Playback",
                NotificationManager.IMPORTANCE_LOW
            ).apply {
                description = "Background audio playback controls"
                setShowBadge(false)
            }
            val manager = getSystemService(NotificationManager::class.java)
            manager.createNotificationChannel(channel)
        }
    }

    @OptIn(UnstableApi::class)
    private fun buildNotification(): Notification {
        val session = mediaSession
        val builder = NotificationCompat.Builder(this, CHANNEL_ID)
            .setSmallIcon(R.drawable.ic_notification)
            .setContentTitle("Aruvi")
            .setContentText("Playing audio in background")
            .setPriority(NotificationCompat.PRIORITY_LOW)
            .setOngoing(true)

        if (session != null) {
            builder.setStyle(
                MediaStyleNotificationHelper.MediaStyle(session)
            )
        }

        return builder.build()
    }

    override fun onGetSession(controllerInfo: MediaSession.ControllerInfo): MediaSession? {
        return mediaSession
    }

    override fun onTaskRemoved(rootIntent: Intent?) {
        val player = mediaSession?.player
        if (player == null || !player.playWhenReady || player.mediaItemCount == 0) {
            stopSelf()
        }
    }

    override fun onDestroy() {
        mediaSession?.run {
            // Don't release the player — it's a singleton shared with ViewModel
            release()
        }
        mediaSession = null
        super.onDestroy()
    }
}
