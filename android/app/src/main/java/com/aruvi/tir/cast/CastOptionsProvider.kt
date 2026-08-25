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
 *    see Supported Media). MKV files served as video/x-matroska will fail to load
 *    on Default; the sender correctly maps extension but Default's Shaka may reject.
 *  • Media Tracks: "Currently, the Styled Media Receiver and Default Media Receiver
 *    allow you to use only the text tracks with the API. To work with the audio
 *    and video tracks, you must develop a Custom Receiver." (Media Tracks guide,
 *    2024-09-18). Thus publishing AUDIO MediaTracks via MediaInfo.setMediaTracks()
 *    and calling RemoteMediaClient.setActiveTrackIds() – as done in
 *    PlayerViewModel.kt:950 – WILL work for TEXT (subtitles) on Default, but WILL
 *    be ignored/rejected for AUDIO on Default/Styled. The app still publishes
 *    AUDIO tracks for future Custom/Styled compatibility and gracefully handles the
 *    rejection (logs + optimistic UI rollback via onTracksChanged).
 *  • TextTrackStyle: Styled via RemoteMediaClient.setTextTrackStyle() – fontScale
 *    works on Default/Styled (verified) and is pushed in
 *    PlayerViewModel.applySubtitleSizeToCastReceiver(). System CORS headers are
 *    required for any Track (Content-Type, Accept-Encoding, Range; expose
 *    Content-Range/Accept-Ranges/Content-Length) – see CORS note below.
 *  • Fit/Fill/Zoom & zoom/pan: Default Receiver UI cannot be customized at all
 *    (Web Receiver Overview: "you cannot customize any of the UI in the Default
 *    Media Web Receiver"). No Cast API exists for aspect override; TV's physical
 *    remote Overscan/Just Scan/16:9 fixes zoom/crop (Google TV & Chrome Story).
 *    The app keeps controls enabled, persists choice in _uiState and ships
 *    MediaInfo.customData {ar_mode, videoScale} for a future Styled/Custom
 *    receiver (CSS object-fit: contain|cover|fill) – Default ignores it as expected.
 *  • CORS: "For adaptive media streaming, Google Cast requires CORS, but even
 *    simple mp4 media streams require CORS if they include Tracks. ... you must
 *    enable CORS for both your track streams and your media streams ... allow at
 *    least Content-Type, Accept-Encoding, Range" (Media Tracks guide). Backend
 *    FastAPI CORSMiddleware currently allows only web_base_url + localhost and
 *    omits Accept-Encoding – should be widened to "*" or Cast origins for
 *    tracks to succeed, and streaming endpoints should explicitly send
 *    Access-Control-Allow-Origin.
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
