package com.aruvi.tir.cast

import android.content.Context
import com.google.android.gms.cast.CastMediaControlIntent
import com.google.android.gms.cast.framework.media.CastMediaOptions
import com.google.android.gms.cast.framework.CastOptions
import com.google.android.gms.cast.framework.OptionsProvider
import com.google.android.gms.cast.framework.SessionProvider
import com.google.android.gms.cast.framework.media.NotificationOptions

/**
 * Provides Cast options to the GMS Cast framework (declared in the manifest as
 * OPTIONS_PROVIDER_CLASS_NAME). Uses the Default Media Receiver so the Chromecast
 * can play our proxied stream URLs, and enables the media notification + lock-screen
 * controls so playback can be controlled even after the app is backgrounded/closed.
 *
 * LIMITATIONS of DEFAULT_MEDIA_RECEIVER_APPLICATION_ID (root cause for missing controls):
 *  • Audio track switching: Default Receiver only enumerates audio renditions that are
 *    signaled via HLS/DASH manifests or side-loaded MediaTracks. Embedded audio inside
 *    MKV (`video/x-matroska`) – the most common library format – is NOT demuxed, so
 *    `CastPlayer.currentTracks` is empty and the Audio sheet shows "No tracks". Fix
 *    requires either (a) a Custom/Stylized Receiver with an MKV-aware demuxer, or
 *    (b) server-side HLS transcoding with alternate audio renditions, or (c) MP4 source.
 *  • Subtitles: Same – embedded SSA/ASS/PGS inside MKV are invisible. Only
 *    side-loaded WebVTT/TTML via `MediaTrack` + external URL are rendered. Embedded
 *    subs would need a Custom Receiver or server-extracted WebVTT.
 *  • Fit/Fill/Zoom + Custom Zoom/Pan: These are local `PlayerView.resizeMode` /
 *    `graphicsLayer` transforms. While casting, video decodes on the Chromecast;
 *    the Cast protocol exposes no aspect-override API for the Default Receiver,
 *    so mutating `toggleResizeMode` / `videoScale` has no TV effect.
 *  • Subtitle size: Local `SubtitleView.setFractionalTextSize()` does not affect the
 *    receiver. Size must be pushed via `RemoteMediaClient.setTextTrackStyle(TextTrackStyle.fontScale)`.
 *    PlayerViewModel now does this in `setSubtitleSize()` + after each `castToDevice()` load.
 *
 * If any of these features must work over Cast, replace the receiver ID below with
 * your Custom Receiver app ID and implement the corresponding CSS / message handling.
 */
class CastOptionsProvider : OptionsProvider {
    override fun getCastOptions(context: Context): CastOptions {
        val notificationOptions = NotificationOptions.Builder()
            .setTargetActivityClassName("com.aruvi.tir.ui.mobile.MobileMainActivity")
            .build()
        val mediaOptions = CastMediaOptions.Builder()
            .setNotificationOptions(notificationOptions)
            .build()
        return CastOptions.Builder()
            .setReceiverApplicationId(CastMediaControlIntent.DEFAULT_MEDIA_RECEIVER_APPLICATION_ID)
            .setCastMediaOptions(mediaOptions)
            .build()
    }

    override fun getAdditionalSessionProviders(context: Context): List<SessionProvider>? = null
}
