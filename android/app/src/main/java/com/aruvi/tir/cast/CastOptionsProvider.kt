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
 * VERIFIED BEHAVIOR ON DEFAULT RECEIVER (per
 * https://developers.google.com/cast/docs/media  and
 * https://developers.google.com/cast/docs/android_sender/media_tracks):
 *  • Supported containers on ALL receivers: MP4, WebM, MP2T, MP3, OGG, WAV (no MKV –
 *    see Supported Media). MKV is ESSENTIAL for this library, so backend now
 *    exposes GET /api/stream/{id}/cast which remuxes MKV → fragmented MP4 on
 *    the fly via ffmpeg -c copy (Dockerfile adds ffmpeg, see backend/app/routers/streaming.py:652).
 *    Sender (PlayerViewModel.kt:1020) detects .mkv / video/x-matroska and uses
 *    the /cast URL with video/mp4 hint so Default Receiver's Shaka demuxer can
 *    play it without re-encode when codecs are already H264/AAC/HEVC/VP9/AV1.
 *    HEVC/VP9/AV1 still require capable Cast devices (Ultra/Google TV) but the
 *    container is now playable.
 *  • Media Tracks: "Currently, the Styled Media Receiver and Default Media Receiver
 *    allow you to use only the text tracks with the API. To work with the audio
 *    and video tracks, you must develop a Custom Receiver." Thus TEXT
 *    (subtitles) via MediaTracks + TextTrackStyle.fontScale ARE supported on
 *    Default and are published in PlayerViewModel.kt:1080; AUDIO setActiveTrackIds()
 *    will be ignored on Default/Styled and needs Custom/HLS. MKV-remuxed MP4
 *    now at least plays video; multi-audio MKV will default to first track on
 *    Default until Custom/HLS is added.
 *  • TextTrackStyle: Styled via RemoteMediaClient.setTextTrackStyle() – fontScale
 *    works on Default/Styled (verified) and is pushed in
 *    PlayerViewModel.applySubtitleSizeToCastReceiver(). System CORS headers are
 *    required for any Track (Content-Type, Accept-Encoding, Range; expose
 *    Content-Range/Accept-Ranges/Content-Length) – backend CORSMiddleware now
 *    uses allow_origin_regex=".*" and streaming endpoints send ACAO:*.
 *  • Fit/Fill/Zoom & zoom/pan: Default Receiver UI cannot be customized at all
 *    (Web Receiver Overview: "you cannot customize any of the UI"). No Cast API
 *    for aspect; TV Overscan/Just Scan fixes crop. App keeps controls enabled,
 *    persists choice in _uiState and ships MediaInfo.customData {ar_mode,
 *    videoScale} for future Styled receiver (CSS object-fit) – Default ignores
 *    as expected.
 *  References: /cast/docs/media (containers/codecs), /cast/docs/android_sender/media_tracks,
 *  /cast/docs/web_receiver (Default cannot be customized), /cast/docs/media/messages (CORS).
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
