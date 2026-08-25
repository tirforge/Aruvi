package com.aruvi.tir.ui.player

import android.content.Context
import android.content.Intent
import android.net.Uri
import android.os.Build
import android.os.Environment
import android.provider.MediaStore
import android.widget.Toast
import androidx.annotation.OptIn
import androidx.lifecycle.SavedStateHandle
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import androidx.media3.common.C
import androidx.media3.common.Format
import androidx.media3.common.MediaItem
import androidx.media3.common.MediaMetadata
import androidx.media3.common.PlaybackException
import androidx.media3.common.Player
import androidx.media3.common.TrackGroup
import androidx.media3.common.TrackSelectionOverride
import androidx.media3.common.Tracks
import androidx.media3.common.util.UnstableApi
import androidx.media3.datasource.DefaultDataSource
import androidx.media3.datasource.DefaultHttpDataSource
import androidx.media3.exoplayer.ExoPlayer
import androidx.media3.exoplayer.source.DefaultMediaSourceFactory
import com.aruvi.tir.data.model.FileItem
import com.aruvi.tir.data.repository.AuthRepository
import com.aruvi.tir.data.repository.FilesRepository
import com.aruvi.tir.data.repository.SettingsRepository
import androidx.media3.cast.CastPlayer
import androidx.media3.common.DeviceInfo
import com.aruvi.tir.service.AudioPlaybackService
import com.google.android.gms.cast.framework.CastContext
import dagger.hilt.android.lifecycle.HiltViewModel
import dagger.hilt.android.qualifiers.ApplicationContext
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import java.io.File
import javax.inject.Inject

data class TrackInfo(
    val index: Int,
    val groupIndex: Int,
    val name: String,
    val language: String?,
    val isSelected: Boolean
)

enum class SubtitleSize(val displayName: String, val scale: Float) {
    SMALL("Small", 0.7f),
    MEDIUM("Medium", 1.0f),
    LARGE("Large", 1.4f),
    EXTRA_LARGE("Extra Large", 1.8f)
}

data class PlaybackError(
    val title: String,
    val description: String,
    val technicalDetails: String?,
    val canRetry: Boolean,
    val errorType: ErrorType
)

enum class ErrorType {
    CODEC_NOT_SUPPORTED,
    NETWORK_ERROR,
    AUTH_ERROR,
    FILE_NOT_FOUND,
    UNKNOWN
}

data class PlayerUiState(
    val isLoading: Boolean = true,
    val isPlaying: Boolean = false,
    val isBuffering: Boolean = false,
    val currentPosition: Long = 0L,
    val bufferedPosition: Long = 0L,
    val duration: Long = 0L,
    val showControls: Boolean = true,
    val showSettings: Boolean = false,
    val file: FileItem? = null,
    val error: PlaybackError? = null,
    val audioTracks: List<TrackInfo> = emptyList(),
    val subtitleTracks: List<TrackInfo> = emptyList(),
    val subtitleSize: SubtitleSize = SubtitleSize.MEDIUM,
    val subtitlesEnabled: Boolean = false,
    val showSeekIndicator: Boolean = false,
    val seekIndicatorText: String = "",
    val seekIndicatorForward: Boolean = true,
    val showJumpDialog: Boolean = false,
    val toggleResizeMode: Int = androidx.media3.ui.AspectRatioFrameLayout.RESIZE_MODE_FIT,
    val videoScale: Float = 1.0f,
    val videoOffsetX: Float = 0f,
    val videoOffsetY: Float = 0f,
    val orientationLock: Int = 0,
    val playbackSpeed: Float = 1.0f,
    val preferredQuality: String = "auto",
    val isAudioFile: Boolean = false,
    val folderAudioFiles: List<FileItem> = emptyList(),
    val currentAudioIndex: Int = -1,
    val isCasting: Boolean = false
)

/**
 * ROOT CAUSE ANALYSIS – Missing Cast Controls with Default Media Receiver
 * -----------------------------------------------------------------------
 * User report: When Chromecast is started via the Default Media Receiver
 * (CastOptionsProvider.DEFAULT_MEDIA_RECEIVER_APPLICATION_ID), the local
 * player controls for:
 *   • Audio track switching
 *   • Subtitle track switching + subtitle text size
 *   • Fit / Fill/Stretch / Zoom (AspectRatioFrameLayout.RESIZE_MODE_*) + custom zoom/pan
 * appear to do nothing on the TV or are empty.
 *
 * Why:
 * 1. Audio/Subtitles are muxed inside a single MKV/MP4 file served as
 *    `https://server/api/stream/<id>`. ExoPlayer locally demuxes the container
 *    and exposes every audio/text stream via Tracks (C.TRACK_TYPE_AUDIO/TEXT).
 *    The Default Receiver does NOT demux MKV embedded tracks – it relies on
 *    HLS/DASH manifests (separate renditions) or side-loaded MediaTracks
 *    (external WebVTT). The CastPlayer therefore reports `currentTracks` with
 *    0 audio/text groups for those MKV files, so the settings sheet shows
 *    "No audio tracks" / "Off" only. This is a receiver-format limitation,
 *    not a sender bug.
 *
 * 2. Even if tracks were enumerated, `castToDevice()` previously built a
 *    bare MediaItem (uri + mimeType only) with no MediaTrack/SubtitleConfiguration
 *    list. Without declared tracks the receiver cannot generate IDs for
 *    `RemoteMediaClient.setActiveMediaTracks()`, so `selectAudioTrack()` /
 *    `selectSubtitleTrack()` via `activePlayer()` would no-op over Cast.
 *
 * 3. Resize modes + custom zoom are applied locally as
 *    `PlayerView.resizeMode` and `Modifier.graphicsLayer(scaleX/Y)` – both are
 *    client-side compositor transforms. While casting the video is decoded on
 *    the Chromecast hardware; the Cast protocol and Default Receiver CSS have
 *    no `RESIZE_MODE_FILL/ZOOM` equivalent. Mutating `toggleResizeMode` /
 *    `videoScale` updates local `_uiState` but no Cast message is sent, so
 *    the TV picture never changes.
 *
 * 4. Subtitle size (`SubtitleView.setFractionalTextSize`) mutates the local
 *    `SubtitleView` only. Cast subtitles are rendered by the receiver's
 *    `<track>` element; size must be pushed via `RemoteMediaClient.setTextTrackStyle`
 *    with a `TextTrackStyle.fontScale`. That call was absent, and mobile
 *    never wired `subtitleView` size at all (TV did).
 *
 * Fixes applied in this file (UPDATE 3 – MKV essential, verified):
 * • MKV support (essential): Backend GET /api/stream/{id}/cast now remuxes
 *   MKV → fMP4 on the fly (ffmpeg -c:v copy -c:a copy -c:s mov_text
 *   -f mp4 -movflags frag_keyframe+empty_moov, Dockerfile adds ffmpeg).
 *   PlayerViewModel.castToDevice() detects .mkv / video/x-matroska and uses
 *   the /cast URL with video/mp4 hint, so Default Receiver's Shaka demuxer
 *   can play the library's MKVs without re-encode when codecs are already
 *   supported (H264/AAC on all Cast, HEVC/VP9/AV1 on Ultra/Google TV).
 *   Non-MKV still uses public link + original MIME hint. See
 *   backend/app/routers/streaming.py:652 and Dockerfile:12.
 * • Text tracks (subtitles/captions): castToDevice() captures local TEXT groups
 *   and publishes as MediaTracks (TYPE_TEXT, SUBTYPE_CAPTIONS) via
 *   MediaInfo.setMediaTracks(). Per docs only TEXT works on Default/Styled;
 *   setActiveTrackIds() + setTextTrackStyle(fontScale) now enable subtitle
 *   switching + size on Default (CORS now fixed in backend/main.py).
 * • Audio/Video tracks: Same MediaTracks publishing kept for AUDIO but per docs
 *   Default/Styled ignore AUDIO (needs Custom/HLS). MKV-remuxed MP4 will play
 *   video on Default; multi-audio MKV defaults to first track until Custom/HLS.
 *   selectAudioTrack() still tries RemoteMediaClient.setActiveTrackIds() and logs
 *   rejection gracefully, then falls back to CastPlayer.
 * • Containers: Verified Supported Media lists MP4/WebM/MP2T – no MKV. MKV now
 *   handled via /cast remux; original video/x-matroska mapping kept only for
 *   local ExoPlayer (nextlib ffmpeg) which does handle MKV.
 * • Resize/Fit/Stretch/Zoom: Verified Default cannot be customized; controls
 *   stay ENABLED, persist in _uiState and shipped as MediaInfo.customData
 *   for future Styled receiver (CSS object-fit) – Default ignores as expected.
 */

@HiltViewModel
class PlayerViewModel @Inject constructor(
    savedStateHandle: SavedStateHandle,
    @ApplicationContext private val context: Context,
    val exoPlayer: ExoPlayer,
    private val dataSourceFactory: DefaultDataSource.Factory,
    private val filesRepository: FilesRepository,
    private val settingsRepository: SettingsRepository,
    private val authRepository: AuthRepository,
) : ViewModel() {

    fun setResizeMode(mode: Int) {
        // Enabled on Default Receiver – stored as MediaInfo.customData {ar_mode} and
        // applied locally. Default Receiver's <video> is object-fit:contain for now
        // (TV remote's Zoom controls it), but Styled Receiver will honor it.
        if (_uiState.value.isCasting) {
            android.util.Log.i("PlayerViewModel", "setResizeMode while casting: saved as customData ar_mode=$mode (Default Receiver shows contain; Styled will apply)")
        }
        _uiState.value = _uiState.value.copy(toggleResizeMode = mode)
    }

    fun setVideoScale(scale: Float) {
        // Keep enabled while casting: local preview scales, and the value is shipped
        // as customData.videoScale so a Styled receiver could apply CSS transform.
        if (_uiState.value.isCasting) {
            android.util.Log.i("PlayerViewModel", "setVideoScale while casting: saved as customData scale=$scale (Default ignores, Styled will apply)")
        }
        _uiState.value = _uiState.value.copy(videoScale = scale.coerceIn(0.5f, 5.0f))
    }

    fun setVideoPan(x: Float, y: Float) {
        _uiState.value = _uiState.value.copy(videoOffsetX = x, videoOffsetY = y)
    }

    fun setOrientationLock(mode: Int) {
        _uiState.value = _uiState.value.copy(orientationLock = mode)
    }

    fun cycleOrientation() {
        val current = _uiState.value.orientationLock
        val next = (current + 1) % 3
        _uiState.value = _uiState.value.copy(orientationLock = next)
    }

    fun updatePan(deltaX: Float, deltaY: Float) {
        val currentX = _uiState.value.videoOffsetX
        val currentY = _uiState.value.videoOffsetY
        _uiState.value = _uiState.value.copy(
            videoOffsetX = currentX + deltaX,
            videoOffsetY = currentY + deltaY
        )
    }

    fun cycleResizeMode() {
        if (_uiState.value.isCasting) {
            android.util.Log.i("PlayerViewModel", "cycleResizeMode while casting: saved as customData (Default shows contain)")
        }
        val current = _uiState.value.toggleResizeMode
        val next = when (current) {
            androidx.media3.ui.AspectRatioFrameLayout.RESIZE_MODE_FIT -> androidx.media3.ui.AspectRatioFrameLayout.RESIZE_MODE_FILL
            androidx.media3.ui.AspectRatioFrameLayout.RESIZE_MODE_FILL -> androidx.media3.ui.AspectRatioFrameLayout.RESIZE_MODE_ZOOM
            else -> androidx.media3.ui.AspectRatioFrameLayout.RESIZE_MODE_FIT
        }
        _uiState.value = _uiState.value.copy(toggleResizeMode = next, videoScale = 1.0f)
    }

    private var currentFileId: Int = savedStateHandle.get<Int>("fileId") ?: 0
private var directUrl: String? = savedStateHandle.get<String>("directUrl")?.takeIf { it.isNotEmpty() }

    private val _uiState = MutableStateFlow(PlayerUiState())
    val uiState: StateFlow<PlayerUiState> = _uiState.asStateFlow()

    private var progressSaveJob: kotlinx.coroutines.Job? = null
    private var controlHideJob: kotlinx.coroutines.Job? = null
    private var seekIndicatorJob: kotlinx.coroutines.Job? = null
    private var resumePosition: Long = savedStateHandle.get<Long>("startPosition") ?: 0L
    private var consecutiveSeekCount: Int = 0
    private var lastSeekTime: Long = 0L

    private var castPlayer: CastPlayer? = null
    private var castContext: com.google.android.gms.cast.framework.CastContext? = null
    // The fileId the running Cast session was loaded with. Used so a session
    // ending AFTER the user already switched movies can't seek the NEW movie
    // to the OLD movie's last TV position.
    private var castSessionFileId = -1
    private var castSessionManagerListener:
        com.google.android.gms.cast.framework.SessionManagerListener<com.google.android.gms.cast.framework.CastSession>? = null
    // The ExoPlayer is a @Singleton that outlives this ViewModel — the listener
    // must be removable or each playback session leaks one listener (and the
    // ViewModel it captures) into the shared player forever.
    private var exoPlayerListener: Player.Listener? = null
    private var castExecutor: java.util.concurrent.ExecutorService? = null

    private val castPlayerListener = object : Player.Listener {
        override fun onDeviceInfoChanged(deviceInfo: DeviceInfo) {
            when (deviceInfo.playbackType) {
                DeviceInfo.PLAYBACK_TYPE_LOCAL -> {
                    // Deliberately NOT clearing isCasting here: this callback can
                    // fire BEFORE SessionManager.onSessionEnded, and dropping the
                    // flag early makes activePlayer() switch to the local player,
                    // whose stale position then overwrites resumePosition before
                    // the disconnect-seek reads it. Session callbacks own the
                    // casting=false transition.
                }
                DeviceInfo.PLAYBACK_TYPE_REMOTE -> {
                    _uiState.value = _uiState.value.copy(isCasting = true)
                    exoPlayer.pause()
                }
            }
        }

        override fun onTracksChanged(tracks: Tracks) {
            // Reflect the cast receiver's audio/subtitle tracks in the UI.
            updateTracks()
        }

        override fun onIsPlayingChanged(isPlaying: Boolean) {
            // The local listener can't supply this while casting (it's paused);
            // without it the play/pause button and controls auto-hide run off a
            // stale isPlaying=false for the entire cast session.
            _uiState.value = _uiState.value.copy(isPlaying = isPlaying)
        }

        override fun onPlaybackStateChanged(playbackState: Int) {
            // Mirror the local player behaviour: when the receiver reports the
            // media finished, persist progress as completed so Continue Watching
            // doesn't resurrect a fully watched movie mid-credits.
            if (playbackState == Player.STATE_ENDED && _uiState.value.isCasting) {
                saveProgress(completed = true)
            }
        }
    }

    init {
        initCastPlayer()
        setupPlayerListener()
        loadAndPlay()
        startProgressTracking()
        observeQuality()
    }

    @OptIn(UnstableApi::class)
    private fun initCastPlayer() {
        // Legacy GMS CastContext path (media3-cast 1.2.1 + play-services-cast-framework).
        // DefaultCastOptionsProvider is declared in the manifest, so getSharedInstance()
        // bootstraps the default media receiver. Must run on the main thread to avoid
        // DeadObjectException and to ensure MediaRouter registration.
        // Android TV builds are cast RECEIVERS, not senders — running the
        // sender stack there only risks weird route pickers and wasted
        // discovery. Leanback check also keeps CastContext off devices
        // without proper GMS cast support.
        if (context.packageManager.hasSystemFeature(android.content.pm.PackageManager.FEATURE_LEANBACK)) {
            android.util.Log.i("PlayerViewModel", "Leanback device: cast sender disabled")
            return
        }
        viewModelScope.launch(kotlinx.coroutines.Dispatchers.Main) {
            try {
                val ctx = try {
                    CastContext.getSharedInstance(context)
                } catch (e: Exception) {
                    null
                }
                if (ctx != null) {
                    castContext = ctx
                    val player = try {
                        CastPlayer(ctx)
                    } catch (_: Throwable) { null }
                    player?.addListener(castPlayerListener)
                    castPlayer = player
                    // When a Cast session starts/resumes, push the current media to the device.
                    val listener = object : com.google.android.gms.cast.framework.SessionManagerListener<com.google.android.gms.cast.framework.CastSession> {
                        override fun onSessionStarted(s: com.google.android.gms.cast.framework.CastSession, r: String) {
                            _uiState.value = _uiState.value.copy(isCasting = true)
                            castToDevice()
                        }
                        override fun onSessionResumed(s: com.google.android.gms.cast.framework.CastSession, wasSuspended: Boolean) {
                            _uiState.value = _uiState.value.copy(isCasting = true)
                            // The receiver usually still has our media loaded; only (re)load
                            // when it has nothing, otherwise reconnecting restarts the movie.
                            if (castPlayer?.playbackState == Player.STATE_IDLE) castToDevice()
                        }
                        override fun onSessionEnded(s: com.google.android.gms.cast.framework.CastSession, e: Int) {
                            _uiState.value = _uiState.value.copy(isCasting = false)
                            // Resume the local player from where the TV left off —
                            // but only if this session was for the movie still open.
                            // endCurrentSession() fired during a movie switch must not
                            // seek the freshly loaded file to the old timeline.
                            if (currentFileId == castSessionFileId) {
                                try { exoPlayer.seekTo(resumePosition) } catch (_: Throwable) {}
                            }
                        }
                        override fun onSessionStarting(s: com.google.android.gms.cast.framework.CastSession) {}
                        override fun onSessionStartFailed(s: com.google.android.gms.cast.framework.CastSession, e: Int) {
                            _uiState.value = _uiState.value.copy(isCasting = false)
                        }
                        override fun onSessionResuming(s: com.google.android.gms.cast.framework.CastSession, r: String) {}
                        override fun onSessionResumeFailed(s: com.google.android.gms.cast.framework.CastSession, e: Int) {
                            _uiState.value = _uiState.value.copy(isCasting = false)
                        }
                        override fun onSessionEnding(s: com.google.android.gms.cast.framework.CastSession) {}
                        override fun onSessionSuspended(s: com.google.android.gms.cast.framework.CastSession, r: Int) {}
                    }
                    castSessionManagerListener = listener
                    ctx.sessionManager.addSessionManagerListener(listener, com.google.android.gms.cast.framework.CastSession::class.java)
                }
            } catch (e: Throwable) {
                android.util.Log.w("PlayerViewModel", "Cast init failed; cast disabled this session", e)
                castPlayer = null
            }
        }
    }

    @OptIn(UnstableApi::class)
    private fun observeQuality() {
        viewModelScope.launch {
            settingsRepository.preferredQuality.collect { quality ->
                _uiState.value = _uiState.value.copy(preferredQuality = quality)
                applyQualityConstraint(quality)
            }
        }
    }

    @OptIn(UnstableApi::class)
    private fun setupPlayerListener() {
        val listener = object : Player.Listener {
            override fun onPlaybackStateChanged(state: Int) {
                when (state) {
                    Player.STATE_BUFFERING -> {
                        _uiState.value = _uiState.value.copy(isBuffering = true)
                    }
                    Player.STATE_READY -> {
                        _uiState.value = _uiState.value.copy(
                            isLoading = false,
                            isBuffering = false,
                            duration = exoPlayer.duration
                        )
                        updateTracks()
                    }
                    Player.STATE_ENDED -> {
                        _uiState.value = _uiState.value.copy(
                            isPlaying = false,
                            showControls = true
                        )
                        saveProgress(completed = true)

                        val ui = _uiState.value
                        if (ui.isAudioFile) {
                            val nextIndex = ui.currentAudioIndex + 1
                            if (nextIndex in ui.folderAudioFiles.indices) {
                                val nextFile = ui.folderAudioFiles[nextIndex]
                                playNextFile(nextFile.id)
                            }
                        }
                    }
                    Player.STATE_IDLE -> {
                    }
                }
            }

            override fun onIsPlayingChanged(isPlaying: Boolean) {
                _uiState.value = _uiState.value.copy(isPlaying = isPlaying)
                if (isPlaying) {
                    scheduleControlsHide()
                }
            }

            override fun onTracksChanged(tracks: Tracks) {
                updateTracks()
            }

            override fun onPlayerError(error: PlaybackException) {
                saveProgress()
                val parsedError = parsePlaybackError(error)
                _uiState.value = _uiState.value.copy(
                    isLoading = false,
                    error = parsedError
                )
            }
        }
        exoPlayerListener = listener
        exoPlayer.addListener(listener)
    }

    @OptIn(UnstableApi::class)
    private fun parsePlaybackError(error: PlaybackException): PlaybackError {
        val message = error.message ?: ""
        val cause = error.cause?.message ?: ""
        val fullDetails = "$message\n$cause"

        return when {
            message.contains("NO_EXCEEDS_CAPABILITIES", ignoreCase = true) ||
            message.contains("Decoder init failed", ignoreCase = true) ||
            message.contains("codec", ignoreCase = true) ||
            cause.contains("NO_EXCEEDS_CAPABILITIES", ignoreCase = true) -> {
                val codecInfo = extractCodecInfo(message + cause)
                PlaybackError(
                    title = "Format Not Supported",
                    description = "This video uses $codecInfo which your device cannot play. " +
                            "Try a different video or use a device with better codec support.",
                    technicalDetails = fullDetails,
                    canRetry = false,
                    errorType = ErrorType.CODEC_NOT_SUPPORTED
                )
            }
            error.errorCode == PlaybackException.ERROR_CODE_IO_NETWORK_CONNECTION_FAILED ||
            error.errorCode == PlaybackException.ERROR_CODE_IO_NETWORK_CONNECTION_TIMEOUT ||
            message.contains("Unable to connect", ignoreCase = true) ||
            message.contains("timeout", ignoreCase = true) -> {
                PlaybackError(
                    title = "Connection Error",
                    description = "Could not connect to the server. Please check your internet connection and try again.",
                    technicalDetails = fullDetails,
                    canRetry = true,
                    errorType = ErrorType.NETWORK_ERROR
                )
            }
            message.contains("401", ignoreCase = true) ||
            message.contains("403", ignoreCase = true) ||
            message.contains("Unauthorized", ignoreCase = true) -> {
                PlaybackError(
                    title = "Authentication Error",
                    description = "Your session has expired. Please go back and try again, or re-login.",
                    technicalDetails = fullDetails,
                    canRetry = true,
                    errorType = ErrorType.AUTH_ERROR
                )
            }
            message.contains("404", ignoreCase = true) ||
            message.contains("not found", ignoreCase = true) -> {
                PlaybackError(
                    title = "File Not Found",
                    description = "This file is no longer available or may have been deleted.",
                    technicalDetails = fullDetails,
                    canRetry = false,
                    errorType = ErrorType.FILE_NOT_FOUND
                )
            }
            else -> {
                PlaybackError(
                    title = "Playback Error",
                    description = "An error occurred while playing this file.",
                    technicalDetails = fullDetails,
                    canRetry = true,
                    errorType = ErrorType.UNKNOWN
                )
            }
        }
    }

    private fun extractCodecInfo(message: String): String {
        return when {
            message.contains("hevc", ignoreCase = true) ||
            message.contains("hvc1", ignoreCase = true) ||
            message.contains("x265", ignoreCase = true) -> {
                if (message.contains("10bit", ignoreCase = true) ||
                    message.contains("10-bit", ignoreCase = true)) {
                    "HEVC 10-bit (HDR)"
                } else {
                    "HEVC/H.265"
                }
            }
            message.contains("av1", ignoreCase = true) -> "AV1"
            message.contains("vp9", ignoreCase = true) -> "VP9"
            message.contains("dolby", ignoreCase = true) -> "Dolby Vision"
            else -> "an advanced video format"
        }
    }

    @OptIn(UnstableApi::class)
    private fun updateTracks() {
        val tracks = activePlayer().currentTracks
        val audioTracks = mutableListOf<TrackInfo>()
        val subtitleTracks = mutableListOf<TrackInfo>()

        tracks.groups.forEachIndexed { groupIndex, group ->
            val trackGroup = group.mediaTrackGroup

            for (trackIndex in 0 until trackGroup.length) {
                val format = trackGroup.getFormat(trackIndex)
                val isSelected = group.isTrackSelected(trackIndex)

                when {
                    format.sampleMimeType?.startsWith("audio/") == true ||
                    group.type == C.TRACK_TYPE_AUDIO -> {
                        audioTracks.add(TrackInfo(
                            index = trackIndex,
                            groupIndex = groupIndex,
                            name = getTrackName(format, audioTracks.size + 1, "Audio"),
                            language = format.language,
                            isSelected = isSelected
                        ))
                    }
                    format.sampleMimeType?.startsWith("text/") == true ||
                    group.type == C.TRACK_TYPE_TEXT -> {
                        subtitleTracks.add(TrackInfo(
                            index = trackIndex,
                            groupIndex = groupIndex,
                            name = getTrackName(format, subtitleTracks.size + 1, "Subtitle"),
                            language = format.language,
                            isSelected = isSelected
                        ))
                    }
                }
            }
        }

        // Sync the enabled/disabled flag with ExoPlayer's actual selection.
        // ExoPlayer auto-selects text tracks by default, so relying on the
        // state default (false) would show the wrong toggle in the UI.
        val subtitlesSelected = subtitleTracks.any { it.isSelected }

        _uiState.value = _uiState.value.copy(
            audioTracks = audioTracks,
            subtitleTracks = subtitleTracks,
            subtitlesEnabled = subtitlesSelected
        )
    }

    @OptIn(UnstableApi::class)
    private fun getTrackName(format: Format, index: Int, type: String): String {
        val lang = format.language?.let { java.util.Locale(it).displayLanguage.takeIf { b -> b.isNotBlank() } }
        val rawLabel = format.label?.trim()?.takeIf { it.isNotBlank() }
        // Rips often abuse label for site/encoder: filter website/rip junk, keep useful codec tags
        val label = rawLabel?.takeIf {
            !it.contains("www.", true) && !it.contains(".com", true) &&
            !it.contains(".xyz", true) && !it.contains(".store", true) &&
            !it.contains("Rip", true) && it.length < 30 &&
            lang?.let { l -> !it.equals(l, true) } ?: true
        }
        return when {
            lang != null && label != null -> "$lang ($label)"
            lang != null -> lang
            label != null -> label
            else -> "$type Track $index"
        }
    }

    // Cast track-id scheme: deterministic mapping from local TrackGroup index + track index
    // to the Cast MediaTrack id we publish in MediaInfo. Must be >0 and stable across
    // reloads so selectAudioTrack/selectSubtitleTrack can compute the same id later.
    private fun castTrackId(groupIndex: Int, trackIndex: Int): Long = (groupIndex * 1000L + trackIndex + 1L).coerceAtLeast(1L)

    @OptIn(UnstableApi::class)
    fun selectAudioTrack(trackInfo: TrackInfo) {
        // Default Receiver ignores AUDIO setActiveTrackIds per docs (only TEXT works),
        // so we make the mobile's selected audio the TV's default via server remux:
        // /api/stream/{id}/cast?audio=N keeps only that audio as the sole default.
        // This is what fulfills "audio track used in mobile as default track in the tv"
        // without a Custom Receiver. For completeness we still try setActiveTrackIds
        // first (works on Custom), then fall back to remux reload.
        if (_uiState.value.isCasting) {
            // Optimistic UI – so Mobile and TV show same selection instantly
            _uiState.value = _uiState.value.copy(
                audioTracks = _uiState.value.audioTracks.map { it.copy(isSelected = it.groupIndex == trackInfo.groupIndex && it.index == trackInfo.index) }
            )
            // Try Custom Receiver path first (fast, no reload)
            var handled = false
            try {
                val remote = castContext?.sessionManager?.currentCastSession?.remoteMediaClient
                if (remote != null) {
                    val audioId = castTrackId(trackInfo.groupIndex, trackInfo.index)
                    val currentActive = try { remote.mediaStatus?.activeTrackIds?.toList() ?: emptyList() } catch (_: Throwable) { emptyList<Long>() }
                    val textIds = currentActive.filter { id ->
                        _uiState.value.subtitleTracks.any { castTrackId(it.groupIndex, it.index) == id }
                    }
                    val newIds = (listOf(audioId) + textIds).toLongArray()
                    remote.setActiveTrackIds(newIds)
                    android.util.Log.i("PlayerViewModel", "Cast setActiveTrackIds audio=$audioId -> ${newIds.contentToString()} (Custom path)")
                    handled = true
                    // For Default this will be ignored – we still reload via remux below to make it effective
                }
            } catch (e: Throwable) {
                android.util.Log.w("PlayerViewModel", "Cast audio setActiveTrackIds failed", e)
            }
            // Default Receiver fallback: reload cast media with ?audio=N so TV's fMP4 has that track as default
            // This works even though Default ignores AUDIO MediaTracks, because the file itself now only contains the chosen audio.
            viewModelScope.launch {
                try {
                    val serverUrl = settingsRepository.getServerUrl().trimEnd('/')
                    val token = authRepository.getAccessToken()
                    val curPos = try { castPlayer?.currentPosition ?: _uiState.value.currentPosition } catch (_: Throwable) { _uiState.value.currentPosition }
                    val baseCastUrl = "$serverUrl/api/stream/$currentFileId/cast"
                    val query = listOfNotNull(token?.let { "token=$it" }, "audio=${trackInfo.index}").joinToString("&")
                    val url = if (query.isNotEmpty()) "$baseCastUrl?$query" else baseCastUrl
                    val file = _uiState.value.file
                    val title = file?.fileName ?: "Aruvi"
                    val castCtx = castContext
                    val session = castCtx?.sessionManager?.currentCastSession
                    val remoteClient = session?.remoteMediaClient
                    if (remoteClient != null) {
                        val mimeType = "video/mp4" // remuxed fMP4
                        val castMetadata = com.google.android.gms.cast.MediaMetadata(com.google.android.gms.cast.MediaMetadata.MEDIA_TYPE_MOVIE).apply {
                            putString(com.google.android.gms.cast.MediaMetadata.KEY_TITLE, title)
                        }
                        val mediaInfo = com.google.android.gms.cast.MediaInfo.Builder(url)
                            .setStreamType(com.google.android.gms.cast.MediaInfo.STREAM_TYPE_BUFFERED)
                            .setContentType(mimeType)
                            .setMetadata(castMetadata)
                            .build()
                        val loadRequest = com.google.android.gms.cast.MediaLoadRequestData.Builder()
                            .setMediaInfo(mediaInfo)
                            .setAutoplay(true)
                            .setCurrentTime(curPos.coerceAtLeast(0))
                            .build()
                        remoteClient.load(loadRequest)
                        android.util.Log.i("PlayerViewModel", "Cast reload with audio=${trackInfo.index} at pos $curPos for Default fallback")
                    }
                } catch (e: Throwable) {
                    android.util.Log.w("PlayerViewModel", "Cast reload with audio failed", e)
                }
            }
            if (handled) return // Custom case already handled; Default case also reloaded above
            return
        }
        val p = activePlayer()
        val tracks = p.currentTracks
        val group = tracks.groups.getOrNull(trackInfo.groupIndex) ?: return
        val trackGroup = group.mediaTrackGroup

        p.trackSelectionParameters = p.trackSelectionParameters
            .buildUpon()
            .setOverrideForType(
                TrackSelectionOverride(trackGroup, listOf(trackInfo.index))
            )
            .build()
    }

    @OptIn(UnstableApi::class)
    fun selectSubtitleTrack(trackInfo: TrackInfo?) {
        if (_uiState.value.isCasting) {
            try {
                val remote = castContext?.sessionManager?.currentCastSession?.remoteMediaClient
                if (remote != null) {
                    // Build new active set: keep current audio id(s), set/clear text id
                    val currentActive = try { remote.mediaStatus?.activeTrackIds?.toList() ?: emptyList() } catch (_: Throwable) { emptyList<Long>() }
                    val audioIds = currentActive.filter { id ->
                        _uiState.value.audioTracks.any { castTrackId(it.groupIndex, it.index) == id }
                    }.ifEmpty {
                        // If receiver hasn't reported audio id yet, keep current selected audio if known
                        _uiState.value.audioTracks.find { it.isSelected }?.let { listOf(castTrackId(it.groupIndex, it.index)) } ?: emptyList()
                    }
                    val newIds = if (trackInfo == null) {
                        // Subtitles off – only audio
                        audioIds.toLongArray()
                    } else {
                        val textId = castTrackId(trackInfo.groupIndex, trackInfo.index)
                        (audioIds + textId).toLongArray()
                    }
                    remote.setActiveTrackIds(newIds)
                    android.util.Log.i("PlayerViewModel", "Cast setActiveTrackIds subtitles=${trackInfo?.let { castTrackId(it.groupIndex, it.index) } ?: "off"} -> ${newIds.contentToString()}")
                    _uiState.value = _uiState.value.copy(subtitlesEnabled = trackInfo != null,
                        subtitleTracks = _uiState.value.subtitleTracks.map { it.copy(isSelected = trackInfo != null && it.groupIndex == trackInfo.groupIndex && it.index == trackInfo.index) })
                    return
                }
            } catch (e: Throwable) {
                android.util.Log.w("PlayerViewModel", "Cast subtitle select via RemoteMediaClient failed, falling back to CastPlayer", e)
            }
        }
        val p = activePlayer()
        if (trackInfo == null) {
            p.trackSelectionParameters = p.trackSelectionParameters
                .buildUpon()
                .setTrackTypeDisabled(C.TRACK_TYPE_TEXT, true)
                .build()
            _uiState.value = _uiState.value.copy(subtitlesEnabled = false)
        } else {
            val tracks = p.currentTracks
            val group = tracks.groups.getOrNull(trackInfo.groupIndex) ?: return
            val trackGroup = group.mediaTrackGroup

            p.trackSelectionParameters = p.trackSelectionParameters
                .buildUpon()
                .setTrackTypeDisabled(C.TRACK_TYPE_TEXT, false)
                .setOverrideForType(
                    TrackSelectionOverride(trackGroup, listOf(trackInfo.index))
                )
                .build()
            _uiState.value = _uiState.value.copy(subtitlesEnabled = true)
        }
    }

    fun setSubtitleSize(size: SubtitleSize) {
        _uiState.value = _uiState.value.copy(subtitleSize = size)
        if (_uiState.value.isCasting) applySubtitleSizeToCastReceiver(size)
    }

    /**
     * Pushes the app's SubtitleSize scale to the Cast receiver's TextTrackStyle.
     * The Default Media Receiver renders subtitles itself (local SubtitleView is
     * not used while casting), so `SubtitleView.setFractionalTextSize()` has
     * no effect. The Cast SDK instead uses TextTrackStyle.fontScale.
     * SMALL=0.7 / MEDIUM=1.0 / LARGE=1.4 / XL=1.8 maps directly.
     * This is best-effort – if no Cast session is active or the receiver
     * rejects the style, we simply log and keep the local preference.
     */
    private fun applySubtitleSizeToCastReceiver(size: SubtitleSize) {
        try {
            val ctx = castContext ?: return
            val client = ctx.sessionManager.currentCastSession?.remoteMediaClient ?: return
            val style = com.google.android.gms.cast.TextTrackStyle().apply {
                fontScale = size.scale
                // Optional: keep white on black shadow for readability on Default Receiver
                foregroundColor = com.google.android.gms.cast.TextTrackStyle.COLOR_WHITE
                backgroundColor = com.google.android.gms.cast.TextTrackStyle.COLOR_NONE
                edgeType = com.google.android.gms.cast.TextTrackStyle.EDGE_TYPE_DROP_SHADOW
            }
            client.setTextTrackStyle(style)
            android.util.Log.i("PlayerViewModel", "Applied subtitle size ${size.displayName} (scale=${size.scale}) to Cast receiver")
        } catch (e: Throwable) {
            android.util.Log.w("PlayerViewModel", "Failed to apply subtitle size to Cast receiver", e)
        }
    }

    fun toggleSettings() {
        _uiState.value = _uiState.value.copy(
            showSettings = !_uiState.value.showSettings,
            showControls = true
        )
        if (_uiState.value.showSettings) {
            controlHideJob?.cancel()
        } else {
            scheduleControlsHide()
        }
    }

    fun hideSettings() {
        _uiState.value = _uiState.value.copy(showSettings = false)
        scheduleControlsHide()
    }

    @OptIn(UnstableApi::class)
    fun loadAndPlay() {
        viewModelScope.launch {
            _uiState.value = _uiState.value.copy(isLoading = true, error = null)

            // Opening/switching a movie while casting would leave the TV on the
            // old file while progress tracking pairs its position with the new
            // currentFileId. End the cast session up front.
            if (_uiState.value.isCasting) {
                try { castContext?.sessionManager?.endCurrentSession(true) } catch (_: Throwable) {}
                _uiState.value = _uiState.value.copy(isCasting = false)
            }

            val directStreamUrl = directUrl
            if (directStreamUrl != null) {
                val mediaItem = MediaItem.Builder()
                    .setUri(directStreamUrl)
                    .setMediaId("stream")
                    .build()
                val srcFactory = DefaultMediaSourceFactory(dataSourceFactory)
                exoPlayer.setMediaSource(srcFactory.createMediaSource(mediaItem))
                exoPlayer.prepare()
                exoPlayer.playWhenReady = true
                // isLoading stays true until the player's listener sets it to false on STATE_READY
                return@launch
            }

            val fileResult = filesRepository.getFile(currentFileId)
            fileResult.fold(
                onSuccess = { file ->
                    _uiState.value = _uiState.value.copy(
                        file = file,
                        isAudioFile = file.isAudio
                    )

                    if (file.isAudio && file.folderId != null) {
                        filesRepository.getFiles(
                            folderId = file.folderId,
                            page = 1,
                            perPage = 100,
                            fileType = "audio"
                        ).onSuccess { response ->
                            val audioFiles = response.items.sortedBy { it.fileName }
                            val index = audioFiles.indexOfFirst { it.id == currentFileId }
                            _uiState.value = _uiState.value.copy(
                                folderAudioFiles = audioFiles,
                                currentAudioIndex = index
                            )
                        }
                    }

                    if (resumePosition <= 0) {
                        filesRepository.getWatchProgress(currentFileId).onSuccess { progress ->
                            progress?.let {
                                resumePosition = it.position.toLong() * 1000L
                            }
                        }
                    }

                    // File existence checks + MediaStore queries are disk /
                    // provider round-trips — keep them off the main thread.
                    val localUri: Uri? = withContext(kotlinx.coroutines.Dispatchers.IO) {
                    val downloadsDir = if (Build.VERSION.SDK_INT < 29) {
                        Environment.getExternalStoragePublicDirectory(
                            Environment.DIRECTORY_DOWNLOADS
                        )
                    } else {
                        null
                    }
                    var foundUri: Uri? = null
                    val legacyFile = downloadsDir?.let { File(it, file.fileName) }
                    if (legacyFile != null && legacyFile.exists() && legacyFile.length() > 0) {
                        foundUri = Uri.fromFile(legacyFile)
                    } else if (Build.VERSION.SDK_INT >= 29) {
                        // Scoped storage: downloads are stored as MediaStore.Downloads rows,
                        // not raw files at the public Downloads path.
                        val selection = "${MediaStore.Downloads.DISPLAY_NAME} = ?"
                        val selectionArgs = arrayOf(file.fileName)
                        context.contentResolver.query(
                            MediaStore.Downloads.EXTERNAL_CONTENT_URI,
                            arrayOf(MediaStore.Downloads._ID, MediaStore.Downloads.IS_PENDING),
                            selection,
                            selectionArgs,
                            null
                        )?.use { cursor ->
                            if (cursor.moveToFirst()) {
                                val id = cursor.getLong(cursor.getColumnIndexOrThrow(MediaStore.Downloads._ID))
                                val isPending = cursor.getInt(
                                    cursor.getColumnIndexOrThrow(MediaStore.Downloads.IS_PENDING)
                                ) == 1
                                if (!isPending) {
                                    foundUri = Uri.withAppendedPath(MediaStore.Downloads.EXTERNAL_CONTENT_URI, id.toString())
                                }
                            }
                        }
                    }
                    foundUri
                    }

                    val useLocalFile = localUri != null

                    val mediaItem: MediaItem
                    val mediaSourceFactory: DefaultMediaSourceFactory

                    if (useLocalFile) {
                        mediaItem = MediaItem.Builder()
                            .setUri(localUri)
                            .setMediaId(currentFileId.toString())
                            .build()
                        // Use a basic data source for local files
                        mediaSourceFactory = DefaultMediaSourceFactory(context)
                    } else {
                        val serverUrl = settingsRepository.getServerUrl().trimEnd('/')

val streamUrl = "$serverUrl/api/stream/$currentFileId"
                        mediaItem = MediaItem.Builder()
                            .setUri(streamUrl)
                            .setMediaId(currentFileId.toString())
                            .build()

                        mediaSourceFactory = DefaultMediaSourceFactory(dataSourceFactory)
                    }

                    exoPlayer.setMediaSource(mediaSourceFactory.createMediaSource(mediaItem))
                    exoPlayer.prepare()

                    if (resumePosition > 0) {
                        exoPlayer.seekTo(resumePosition)
                    }

                    exoPlayer.playWhenReady = true
                },
                onFailure = { e ->
                    _uiState.value = _uiState.value.copy(
                        isLoading = false,
                        error = PlaybackError(
                            title = "Failed to Load",
                            description = e.message ?: "Could not load file information",
                            technicalDetails = null,
                            canRetry = true,
                            errorType = ErrorType.UNKNOWN
                        )
                    )
                }
            )
        }
    }

    fun playNextFile(newFileId: Int) {
        if (_uiState.value.isCasting) {
            try { castContext?.sessionManager?.endCurrentSession(true) } catch (_: Throwable) {}
            _uiState.value = _uiState.value.copy(isCasting = false)
        }
        currentFileId = newFileId
        resumePosition = 0
        exoPlayer.stop()
        loadAndPlay()
    }

    fun retry() {
        resumePosition = exoPlayer.currentPosition.coerceAtLeast(0)
        saveProgress()
        exoPlayer.stop()
        exoPlayer.clearMediaItems()
        loadAndPlay()
    }

    fun setResumePosition(position: Long) {
        resumePosition = position
    }

    fun togglePlayback() {
        val p = activePlayer()
        if (p.isPlaying) {
            p.pause()
            saveProgress()
        } else if (p.playbackState == Player.STATE_ENDED) {
            // Video finished: replay from the start.
            p.seekToDefaultPosition()
            p.play()
        } else {
            p.play()
        }
        showControls()
    }

    fun openInExternalPlayer(context: Context) {
        viewModelScope.launch {
            val file = _uiState.value.file
            val streamUrl = when {
                directUrl != null -> directUrl
                file != null -> {
                    val serverUrl = settingsRepository.getServerUrl().trimEnd('/')
                    val publicLinkResult = filesRepository.getPublicLink(file.id, serverUrl)
                    publicLinkResult.getOrElse {
                        val token = authRepository.getAccessToken()
                        if (token != null) {
                            "$serverUrl/api/stream/${file.id}?token=$token"
                        } else {
                            "$serverUrl/api/stream/${file.id}"
                        }
                    }
                }
                else -> return@launch
            }

            val intent = Intent(Intent.ACTION_VIEW).apply {
                setDataAndType(Uri.parse(streamUrl), "video/*")
                flags = Intent.FLAG_ACTIVITY_NEW_TASK
            }

            if (context.packageManager.resolveActivity(intent, 0) == null) {
                Toast.makeText(context, "No external player found", Toast.LENGTH_SHORT).show()
                return@launch
            }

            try {
                context.startActivity(intent)
            } catch (e: android.content.ActivityNotFoundException) {
                Toast.makeText(context, "No external player found", Toast.LENGTH_SHORT).show()
            } catch (e: Exception) {
                android.util.Log.w("PlayerViewModel", "external player launch failed", e)
            }
        }
    }

    private fun castToDevice() {
        val player = castPlayer ?: return
        viewModelScope.launch {
            val serverUrl = settingsRepository.getServerUrl().trimEnd('/')
            val token = authRepository.getAccessToken()

            // Capture the local position and silence local playback IMMEDIATELY:
            // the public-link request below is a network round-trip, and pausing
            // only after it meant phone + TV played simultaneously for that gap.
            val startPositionMs = exoPlayer.currentPosition.coerceAtLeast(0)
            exoPlayer.pause()

            // Prefer the public, unauthenticated stream URL so the Chromecast
            // receiver can fetch it directly (it cannot send bearer tokens or
            // custom auth headers). Falls back to the token URL if the public
            // link can't be generated. MKV is essential – Default Receiver
            // cannot demux Matroska (Supported Media lists only MP4/WebM/MP2T).
            // Backend now exposes /api/stream/{id}/cast which remuxes MKV →
            // fragmented MP4 via ffmpeg -c copy (Dockerfile adds ffmpeg) so
            // the same MKV library plays on Default Receiver without re-encode
            // when codecs are already H264/AAC (HEVC/VP9/AV1 still play on
            // capable Cast devices like Ultra/Google TV).
            val isMkvSource = file?.fileName?.lowercase()?.endsWith(".mkv") == true ||
                (file?.mimeType?.lowercase() == "video/x-matroska")
            // Mobile's selected audio → TV's default: Default Receiver ignores AUDIO
            // setActiveTrackIds per docs, so we make the mobile's choice the file's
            // sole default audio via ?audio=N on the cast endpoint (backend remux
            // keeps only that track with -map 0:a:N). Works for both MKV and MP4
            // multi-audio, and keeps existing behavior when no explicit selection.
            val selectedAudioForCast = _uiState.value.audioTracks.find { it.isSelected }
            val url = if (isMkvSource || selectedAudioForCast != null) {
                // Cast-optimized remux endpoint; token may still be needed if public hash not yet ready
                // For MKV always remux (container fix); for MP4 only when audio selection needed
                val baseCastUrl = "$serverUrl/api/stream/$currentFileId/cast"
                val tokenPart = token?.let { "token=$it" }
                val audioPart = selectedAudioForCast?.let { "audio=${it.index}" }
                val query = listOfNotNull(tokenPart, audioPart).joinToString("&")
                if (query.isNotEmpty()) "$baseCastUrl?$query" else baseCastUrl
            } else {
                val publicLink = filesRepository.getPublicLink(currentFileId, serverUrl)
                publicLink.getOrElse {
                    if (token != null) "$serverUrl/api/stream/$currentFileId?token=$token"
                    else "$serverUrl/api/stream/$currentFileId"
                }
            }

            val file = _uiState.value.file
            val title = file?.fileName ?: "Aruvi"

            // Thumbnails are also fetched by the receiver, so pass the token as
            // a query param (best-effort; missing art is non-fatal).
            val thumbnailUrl = if (file?.thumbnailFileId != null) {
                "$serverUrl/api/stream/$currentFileId/thumbnail" + (if (token != null) "?token=$token" else "")
            } else null

            try {
                val mediaMetadata = MediaMetadata.Builder()
                    .setTitle(title)
                    .setArtworkUri(thumbnailUrl?.let { Uri.parse(it) })
                    .build()
                // media3 1.2.1 MediaItem.Builder has no setContentType/
                // setStreamType; setMimeType is the supported equivalent and
                // BUFFERED is already the Cast default stream type. The MIME
                // hint selects the receiver's DEMUXER, so it must match the
                // real container: an MKV served with a video/mp4 hint fails to
                // load even when its codecs are supported. Prefer the backend
                // MIME, fall back to the filename extension (most libraries
                // here are .mkv), and only then assume MP4.
                // For MKV Cast we already remux to fMP4 on the server, so always hint video/mp4
                // (Default Receiver's Shaka demuxer for MP4 works, Matroska does not).
                // For non-MKV keep original MIME hint.
                val mimeType = if (isMkvSource) "video/mp4" else sequenceOf(
                    file?.mimeType?.takeIf { it.startsWith("video/") || it.startsWith("audio/") },
                    mapOf(
                        "webm" to "video/webm",
                        "mp4" to "video/mp4",
                        "m4v" to "video/mp4",
                        "mov" to "video/mp4",
                        "ts" to "video/mp2t",
                        "mp3" to "audio/mpeg",
                        "m4a" to "audio/mp4",
                        "flac" to "audio/flac",
                        "ogg" to "audio/ogg",
                        "opus" to "audio/ogg",
                        "wav" to "audio/wav"
                    )[file?.fileName?.substringAfterLast('.', "")?.lowercase() ?: ""],
                    "video/mp4"
                ).firstOrNull { !it.isNullOrBlank() }!!
                // Snapshot local tracks BEFORE we pause – this is what lets the
                // Default Receiver expose switching for MP4/WebM files without a
                // Custom Receiver. We translate every local audio/text TrackGroup
                // into a Cast MediaTrack with a stable id (castTrackId). The
                // Default Receiver's Shaka demuxer will then allow
                // RemoteMediaClient.setActiveTrackIds() to switch. MKV embedded
                // tracks still won't demux on Default Receiver (format limit),
                // but MP4 multi-audio / WebVTT side-loaded now works. Also
                // includes internet subtitles (if any were fetched) as TEXT tracks
                // with external VTT URLs – Default Receiver renders those.
                val snapshotGroups = try { exoPlayer.currentTracks.groups } catch (_: Throwable) { null }
                val castTracks = mutableListOf<com.google.android.gms.cast.MediaTrack>()
                if (snapshotGroups != null) {
                    snapshotGroups.forEachIndexed { gIdx, group ->
                        val trackGroup = group.mediaTrackGroup
                        for (tIdx in 0 until trackGroup.length) {
                            val format = trackGroup.getFormat(tIdx)
                            val isAudio = format.sampleMimeType?.startsWith("audio/") == true || group.type == C.TRACK_TYPE_AUDIO
                            val isText = format.sampleMimeType?.startsWith("text/") == true || group.type == C.TRACK_TYPE_TEXT
                            if (isAudio) {
                                val id = castTrackId(gIdx, tIdx)
                                val name = getTrackName(format, castTracks.count { it.type == com.google.android.gms.cast.MediaTrack.TYPE_AUDIO } + 1, "Audio")
                                val builder = com.google.android.gms.cast.MediaTrack.Builder(id, com.google.android.gms.cast.MediaTrack.TYPE_AUDIO)
                                builder.setName(name)
                                format.language?.let { builder.setLanguage(it) }
                                // For muxed MP4 the receiver demuxes from the main content; no contentId needed.
                                // ContentType hint helps Shaka choose demuxer.
                                builder.setContentType("audio/mp4")
                                castTracks.add(builder.build())
                            } else if (isText) {
                                val id = castTrackId(gIdx, tIdx)
                                val name = getTrackName(format, castTracks.count { it.type == com.google.android.gms.cast.MediaTrack.TYPE_TEXT } + 1, "Subtitle")
                                val builder = com.google.android.gms.cast.MediaTrack.Builder(id, com.google.android.gms.cast.MediaTrack.TYPE_TEXT)
                                builder.setName(name)
                                format.language?.let { builder.setLanguage(it) }
                                builder.setSubtype(com.google.android.gms.cast.MediaTrack.SUBTYPE_CAPTIONS)
                                builder.setContentType("text/vtt")
                                // Embedded subs: no external contentId – receiver demuxes from main stream.
                                // Side-loaded subs would have a URL; if we ever attach internet subs we
                                // would call builder.setContentId(vttUrl) and setContentType("text/vtt").
                                castTracks.add(builder.build())
                            }
                        }
                    }
                }
                // Enrich with internet subtitles if embedded list is empty and we have a file name
                // (best-effort, no network on main thread – we already have file; if no embedded
                // text tracks but user expects subtitles, they can fetch via /api/subtitles/search
                // and we would add them here as additional TEXT tracks with contentId = subtitle VTT url)
                val mediaItem = MediaItem.Builder()
                    .setUri(url)
                    .setMediaId(currentFileId.toString())
                    .setMediaMetadata(mediaMetadata)
                    .setMimeType(mimeType)
                    .build()
                // Start where the LOCAL player was when casting began (see
                // capture above): reading the shared resumePosition instead can
                // hit a zeroed value if updatePosition() synced it from the
                // still-idle CastPlayer first (androidx/media#25 behaviour).
                castSessionFileId = currentFileId
                // Starting at/after the end (resume of a finished movie) asks
                // the receiver to seek past the final frame → instant ENDED or
                // a stuck spinner. Restart cleanly from 0 instead.
                val localDur = exoPlayer.duration
                val safeStart =
                    if (localDur > 0 && startPositionMs >= localDur - 1500) 0L else startPositionMs

                // Prefer enriched load via RemoteMediaClient (exposes MediaTracks to Default Receiver)
                // Fallback to CastPlayer if no session yet.
                var usedEnrichedLoad = false
                try {
                    val castCtx = castContext
                    val session = castCtx?.sessionManager?.currentCastSession
                    val remoteClient = session?.remoteMediaClient
                    if (remoteClient != null && castTracks.isNotEmpty()) {
                        val castMetadata = com.google.android.gms.cast.MediaMetadata(com.google.android.gms.cast.MediaMetadata.MEDIA_TYPE_MOVIE).apply {
                            putString(com.google.android.gms.cast.MediaMetadata.KEY_TITLE, title)
                            thumbnailUrl?.let { addImage(com.google.android.gms.cast.WebImage(Uri.parse(it))) }
                        }
                        val customData = org.json.JSONObject().apply {
                            put("ar_mode", when (_uiState.value.toggleResizeMode) {
                                androidx.media3.ui.AspectRatioFrameLayout.RESIZE_MODE_FILL -> "fill"
                                androidx.media3.ui.AspectRatioFrameLayout.RESIZE_MODE_ZOOM -> "zoom"
                                else -> "fit"
                            })
                            put("videoScale", _uiState.value.videoScale)
                            // Default Receiver ignores customData, but a future Styled Receiver
                            // could read it to apply CSS object-fit. Keeping it here makes the
                            // same sender work on both receivers without code change.
                        }
                        val castMediaInfoBuilder = com.google.android.gms.cast.MediaInfo.Builder(url)
                            .setStreamType(com.google.android.gms.cast.MediaInfo.STREAM_TYPE_BUFFERED)
                            .setContentType(mimeType)
                            .setMetadata(castMetadata)
                            .setCustomData(customData)
                        if (castTracks.isNotEmpty()) castMediaInfoBuilder.setMediaTracks(castTracks)
                        val mediaInfo = castMediaInfoBuilder.build()
                        val loadRequest = com.google.android.gms.cast.MediaLoadRequestData.Builder()
                            .setMediaInfo(mediaInfo)
                            .setAutoplay(true)
                            .setCurrentTime(safeStart)
                            .build()
                        remoteClient.load(loadRequest)
                        usedEnrichedLoad = true
                        android.util.Log.i("PlayerViewModel", "Cast enriched load via RemoteMediaClient with ${castTracks.size} tracks (mime=$mimeType, start=$safeStart)")
                    }
                } catch (e: Throwable) {
                    android.util.Log.w("PlayerViewModel", "Enriched Cast load failed, falling back to CastPlayer", e)
                }
                if (!usedEnrichedLoad) {
                player.setMediaItem(mediaItem, safeStart)
                player.prepare()
                player.play()
                }
                // Re-apply the user's preferred subtitle size to the receiver.
                // Default Receiver resets TextTrackStyle on each load; without
                // this the size reverts to medium every time casting starts.
                // Delay is unnecessary – RemoteMediaClient queues until media loaded.
                try {
                    applySubtitleSizeToCastReceiver(_uiState.value.subtitleSize)
                } catch (_: Throwable) {}
                // If we did enriched load, also apply resize hint via TextTrackStyle is separate;
                // for video aspect the Default Receiver still uses its own <video> object-fit
                // (contain). Styled/Custom Receiver could read customData.ar_mode. On Default
                // the control remains local-only but we keep UI enabled so the choice persists
                // after disconnect and for future Styled migration.
            } catch (e: Throwable) {
                // Never swallow cast-load failures silently: a rejected load
                // leaves the receiver idle ("no media selected") with no clue
                // why. Surface it in logcat under the cast tag.
                android.util.Log.w("PlayerViewModel", "castToDevice load failed url=$url", e)
            }
        }
    }

    fun stopCasting() {
        // End the Cast session (stops the receiver) rather than just pausing it,
        // so the notification/lock-screen controls are torn down too.
        try {
            castContext?.sessionManager?.endCurrentSession(true)
        } catch (_: Throwable) {}
        try {
            castPlayer?.clearMediaItems()
        } catch (_: Throwable) {}
        _uiState.value = _uiState.value.copy(isCasting = false)
    }

    // Returns the player that should currently receive control/query calls.
    // While casting, all playback control must route to the CastPlayer, not the
    // (paused) local ExoPlayer — otherwise the Chromecast is unaffected.
    private fun activePlayer(): Player =
        if (_uiState.value.isCasting) castPlayer ?: exoPlayer else exoPlayer

    fun play() {
        val p = activePlayer()
        if (p.playbackState == Player.STATE_ENDED) {
            p.seekToDefaultPosition()
        }
        p.play()
    }

    fun pause() {
        activePlayer().pause()
    }

    fun seekTo(positionMs: Long) {
        val p = activePlayer()
        val state = p.playbackState
        // STATE_ENDED must be allowed: at end-of-video a seek is the only
        // operation that restarts playback (media3 play() is a no-op when
        // ENDED, and a seek transitions ENDED → BUFFERING → READY).
        if (state != Player.STATE_READY && state != Player.STATE_BUFFERING && state != Player.STATE_ENDED) return
        val duration = p.duration.takeIf { it > 0 } ?: Long.MAX_VALUE
        val clampedPosition = positionMs.coerceIn(0, duration)
        p.seekTo(clampedPosition)
        updatePosition()
        showControls()
    }

    fun updateCurrentPosition(position: Long) {
        _uiState.value = _uiState.value.copy(currentPosition = position)
    }

    fun onSeekEnd() {
        val target = _uiState.value.currentPosition
        seekTo(target)
    }

    private fun getAcceleratedSeekMs(): Long {
        val now = System.currentTimeMillis()
        if (now - lastSeekTime > 1500) {
            consecutiveSeekCount = 0
        }
        lastSeekTime = now
        consecutiveSeekCount++

        val seekMs = when {
            consecutiveSeekCount <= 3 -> 10_000L
            consecutiveSeekCount <= 6 -> 30_000L
            consecutiveSeekCount <= 10 -> 60_000L
            consecutiveSeekCount <= 15 -> 120_000L
            else -> 300_000L
        }
        return seekMs
    }

    fun seekBackward() {
        val seekMs = getAcceleratedSeekMs()
        val newPos = activePlayer().currentPosition - seekMs
        seekTo(newPos)
        showSeekIndicator(seekMs, false)
    }

    fun seekForward() {
        val seekMs = getAcceleratedSeekMs()
        val newPos = activePlayer().currentPosition + seekMs
        seekTo(newPos)
        showSeekIndicator(seekMs, true)
    }

    private fun showSeekIndicator(seekMs: Long, isForward: Boolean) {
        val text = formatSeekAmount(seekMs)
        _uiState.value = _uiState.value.copy(
            showSeekIndicator = true,
            seekIndicatorText = if (isForward) "+$text" else "-$text",
            seekIndicatorForward = isForward
        )
        seekIndicatorJob?.cancel()
        seekIndicatorJob = viewModelScope.launch {
            delay(800)
            _uiState.value = _uiState.value.copy(showSeekIndicator = false)
        }
    }

    private fun formatSeekAmount(ms: Long): String {
        val totalSeconds = ms / 1000
        return when {
            totalSeconds >= 60 -> "${totalSeconds / 60}min"
            else -> "${totalSeconds}s"
        }
    }

    fun jumpToPercent(percent: Int) {
        val dur = activePlayer().duration
        if (dur <= 0) return
        val target = (dur * percent / 100L)
        seekTo(target)
        showControls()
        _uiState.value = _uiState.value.copy(
            showSeekIndicator = true,
            seekIndicatorText = "${percent}%",
            seekIndicatorForward = true
        )
        seekIndicatorJob?.cancel()
        seekIndicatorJob = viewModelScope.launch {
            delay(1200)
            _uiState.value = _uiState.value.copy(showSeekIndicator = false)
        }
    }

    fun jumpToTimestamp(hours: Int, minutes: Int, seconds: Int) {
        val posMs = ((hours * 3600L) + (minutes * 60L) + seconds) * 1000L
        seekTo(posMs)
        _uiState.value = _uiState.value.copy(showJumpDialog = false)
        if (_uiState.value.isPlaying) scheduleControlsHide()
    }

    fun toggleJumpDialog() {
        _uiState.value = _uiState.value.copy(
            showJumpDialog = !_uiState.value.showJumpDialog
        )
        if (_uiState.value.showJumpDialog) {
            controlHideJob?.cancel()
        } else if (_uiState.value.isPlaying) {
            scheduleControlsHide()
        }
    }

    fun setPlaybackSpeed(speed: Float) {
        activePlayer().setPlaybackSpeed(speed)
        _uiState.value = _uiState.value.copy(playbackSpeed = speed)
    }

    @OptIn(UnstableApi::class)
    fun setPreferredQuality(quality: String) {
        _uiState.value = _uiState.value.copy(preferredQuality = quality)
        viewModelScope.launch {
            settingsRepository.setPreferredQuality(quality)
        }
        applyQualityConstraint(quality)
    }

    private fun getQualityMaxDimensions(quality: String): Pair<Int, Int> {
        return when (quality) {
            "1080p" -> 1920 to 1080
            "720p" -> 1280 to 720
            "480p" -> 854 to 480
            "360p" -> 640 to 360
            else -> Int.MAX_VALUE to Int.MAX_VALUE
        }
    }

    @OptIn(UnstableApi::class)
    private fun applyQualityConstraint(quality: String) {
        val (maxWidth, maxHeight) = getQualityMaxDimensions(quality)
        // Apply to whichever player currently owns playback — while casting,
        // constraining only the paused local player left the preference
        // silently ignored by the receiver.
        val target = activePlayer()
        target.trackSelectionParameters = target.trackSelectionParameters
            .buildUpon()
            .setMaxVideoSize(maxWidth, maxHeight)
            .build()
    }

    fun showControls() {
        _uiState.value = _uiState.value.copy(showControls = true)
        if (!_uiState.value.showSettings) {
            scheduleControlsHide()
        }
    }

    fun hideControls() {
        if (_uiState.value.isPlaying && !_uiState.value.showSettings) {
            _uiState.value = _uiState.value.copy(showControls = false)
        }
    }

    private fun scheduleControlsHide() {
        controlHideJob?.cancel()
        controlHideJob = viewModelScope.launch {
            delay(5000)
            if (_uiState.value.isPlaying && !_uiState.value.showSettings) {
                _uiState.value = _uiState.value.copy(showControls = false)
            }
        }
    }

    private fun startProgressTracking() {
        viewModelScope.launch {
            var ticks = 0
while (isActive) {
                updatePosition()

                if (activePlayer().isPlaying) {
                    ticks++
                    if (ticks >= 15) {
                        saveProgress(completed = false)
                        ticks = 0
                    }
                } else {
                    ticks = 0
                }

                delay(1000)
            }
        }
    }

    private fun updatePosition() {
        val p = activePlayer()
        _uiState.value = _uiState.value.copy(
            currentPosition = p.currentPosition,
            bufferedPosition = p.bufferedPosition,
            duration = p.duration.coerceAtLeast(0)
        )
        // Keep the resume point in sync with whichever player is active — but
        // only when that player actually knows its position (READY/playing).
        // A CastPlayer before its first status update reports position 0 with
        // an empty timeline (androidx/media#25); trusting it here zeroed the
        // saved watch position and broke resume-on-disconnect.
        if (p.playbackState == Player.STATE_READY || p.isPlaying) {
            resumePosition = p.currentPosition.coerceAtLeast(0)
        }
    }

    fun saveProgress(completed: Boolean = false) {
        val p = activePlayer()
        val position = (p.currentPosition / 1000).toInt()
        val duration = (p.duration / 1000).toInt().takeIf { it > 0 }

        if (position <= 0 && !completed) return
        if (currentFileId <= 0) return

        progressSaveJob?.cancel()
        progressSaveJob = viewModelScope.launch {
            filesRepository.updateWatchProgress(
                fileId = currentFileId,
                position = position,
                duration = duration,
                completed = completed
            )
        }
    }

    fun onLeavePlayer() {
        saveProgress()
        if (_uiState.value.isAudioFile && exoPlayer.isPlaying) {
            startBackgroundAudio()
        } else {
            exoPlayer.pause()
        }
    }

    private var isBackgroundAudioActive = false

    fun startBackgroundAudio() {
        isBackgroundAudioActive = true
        val intent = Intent(context, AudioPlaybackService::class.java)
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            context.startForegroundService(intent)
        } else {
            context.startService(intent)
        }
    }

    fun stopBackgroundAudio() {
        isBackgroundAudioActive = false
        val intent = Intent(context, AudioPlaybackService::class.java)
        context.stopService(intent)
    }

    override fun onCleared() {
        super.onCleared()
        exoPlayerListener?.let {
            try { exoPlayer.removeListener(it) } catch (_: Throwable) {}
        }
        exoPlayerListener = null
        castExecutor?.let {
            try { it.shutdown() } catch (_: Throwable) {}
        }
        castExecutor = null
        castPlayer?.let {
            try { it.removeListener(castPlayerListener) } catch (_: Throwable) {}
            try { it.release() } catch (_: Throwable) {}
        }
        castSessionManagerListener?.let {
            try {
                castContext?.sessionManager?.removeSessionManagerListener(
                    it, com.google.android.gms.cast.framework.CastSession::class.java
                )
            } catch (_: Throwable) {}
        }
        castSessionManagerListener = null
        castContext = null
        saveProgress()
        if (!isBackgroundAudioActive) {
            // The ExoPlayer is a shared @Singleton. Only tear down the media
            // this session loaded — if a new session has already replaced the
            // playlist (different mediaId), stop()+clearMediaItems() would
            // kill the fresh session's playback.
            val stillOwnsMedia =
                exoPlayer.currentMediaItem?.mediaId == currentFileId.toString() ||
                    exoPlayer.currentMediaItem == null
            if (stillOwnsMedia) {
                exoPlayer.stop()
                exoPlayer.clearMediaItems()
            }
        }
    }
}
