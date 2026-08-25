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
 * ENABLED FEATURES ON DEFAULT RECEIVER (no Custom Receiver needed):
 *  This app now publishes the sender's demuxed TrackGroups as Cast MediaTracks
 *  (TYPE_AUDIO/TYPE_TEXT) when loading via RemoteMediaClient (PlayerViewModel.kt:950).
 *  For MP4/WebM the Default Receiver's Shaka player can then honor
 *  RemoteMediaClient.setActiveTrackIds() – audio switching and muxed VTT subtitles
 *  work on the Default Receiver without a Custom Receiver. Subtitle size is pushed
 *  via RemoteMediaClient.setTextTrackStyle(TextTrackStyle.fontScale).
 *  Fit/Fill/Zoom & zoom/pan are kept enabled: the choice is stored in _uiState,
 *  applied to the local preview, and shipped as MediaInfo.customData
 *  {ar_mode, videoScale}. Default Receiver renders contain (TV picture mode) but
 *  the preference persists after disconnect and a Styled Receiver would apply it
 *  with CSS object-fit without sender changes.
 *
 * REMAINING LIMITATIONS (container, not code):
 *  • MKV (`video/x-matroska`) embedded audio/text cannot be demuxed by the Default
 *    Receiver's Shaka build – MediaTracks will be published but the receiver still
 *    won't decode them. Remux to MP4 on the server or use a Styled Receiver with
 *    Matroska support for those files.
 *  • Side-loaded internet subtitles (SRT → VTT) would need a backend endpoint that
 *    serves WebVTT at a stable URL and sets MediaTrack.contentId – the sender code
 *    already handles contentId when present.
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
