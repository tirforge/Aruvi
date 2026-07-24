package com.aruvi.tir.ui.player

import android.content.Context
import android.content.Intent
import android.net.Uri
import android.os.Build
import android.os.Environment
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
    val seekSpeed: Int = 10_000,
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
        _uiState.value = _uiState.value.copy(toggleResizeMode = mode)
    }

    fun setVideoScale(scale: Float) {
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
        val current = _uiState.value.toggleResizeMode
        val next = when (current) {
            androidx.media3.ui.AspectRatioFrameLayout.RESIZE_MODE_FIT -> androidx.media3.ui.AspectRatioFrameLayout.RESIZE_MODE_FILL
            androidx.media3.ui.AspectRatioFrameLayout.RESIZE_MODE_FILL -> androidx.media3.ui.AspectRatioFrameLayout.RESIZE_MODE_ZOOM
            else -> androidx.media3.ui.AspectRatioFrameLayout.RESIZE_MODE_FIT
        }
        _uiState.value = _uiState.value.copy(toggleResizeMode = next, videoScale = 1.0f)
    }

    private var currentFileId: Int = savedStateHandle.get<Int>("fileId") ?: 0

    private val _uiState = MutableStateFlow(PlayerUiState())
    val uiState: StateFlow<PlayerUiState> = _uiState.asStateFlow()

    private var progressSaveJob: kotlinx.coroutines.Job? = null
    private var controlHideJob: kotlinx.coroutines.Job? = null
    private var seekIndicatorJob: kotlinx.coroutines.Job? = null
    private var seekAccelJob: kotlinx.coroutines.Job? = null
    private var resumePosition: Long = savedStateHandle.get<Long>("startPosition") ?: 0L
    private var consecutiveSeekCount: Int = 0
    private var lastSeekTime: Long = 0L

    private var castPlayer: CastPlayer? = null

    private val castPlayerListener = object : Player.Listener {
        override fun onDeviceInfoChanged(deviceInfo: DeviceInfo) {
            when (deviceInfo.playbackType) {
                DeviceInfo.PLAYBACK_TYPE_LOCAL -> {
                    _uiState.value = _uiState.value.copy(isCasting = false)
                }
                DeviceInfo.PLAYBACK_TYPE_REMOTE -> {
                    _uiState.value = _uiState.value.copy(isCasting = true)
                    exoPlayer.pause()
                }
            }
        }
    }

    init {
        initCastPlayer()
        exoPlayer.trackSelectionParameters = exoPlayer.trackSelectionParameters
            .buildUpon()
            .setTrackTypeDisabled(C.TRACK_TYPE_TEXT, true)
            .build()
        setupPlayerListener()
        loadAndPlay()
        startProgressTracking()
        observeQuality()
    }

    @OptIn(UnstableApi::class)
    private fun initCastPlayer() {
        val executor = java.util.concurrent.Executors.newSingleThreadExecutor()
        viewModelScope.launch(kotlinx.coroutines.Dispatchers.Main) {
            try {
                // Defensive initialization of CastContext to avoid DeadObjectException on Main thread
                val castContextTask = withContext(kotlinx.coroutines.Dispatchers.IO) {
                    try {
                        CastContext.getSharedInstance(context, executor)
                    } catch (e: Exception) {
                        null
                    }
                }

                castContextTask?.addOnSuccessListener { castContext ->
                    viewModelScope.launch {
                        val player = withContext(kotlinx.coroutines.Dispatchers.IO) {
                            try {
                                CastPlayer(castContext)
                            } catch (_: Throwable) {
                                null
                            }
                        }
                        castPlayer = player
                        player?.addListener(castPlayerListener)
                    }
                }?.addOnFailureListener {
                    castPlayer = null
                }
            } catch (e: Exception) {
                // Ignore GMS failures
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
        exoPlayer.addListener(object : Player.Listener {
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
        })
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
        val tracks = exoPlayer.currentTracks
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

        _uiState.value = _uiState.value.copy(
            audioTracks = audioTracks,
            subtitleTracks = subtitleTracks
        )
    }

    @OptIn(UnstableApi::class)
    private fun getTrackName(format: Format, index: Int, type: String): String {
        val language = format.language?.let { lang ->
            java.util.Locale(lang).displayLanguage.takeIf { it.isNotBlank() }
        }
        val label = format.label?.takeIf { it.isNotBlank() }
        
        return when {
            label != null -> label
            language != null -> language
            else -> "$type Track $index"
        }
    }

    @OptIn(UnstableApi::class)
    fun selectAudioTrack(trackInfo: TrackInfo) {
        val tracks = exoPlayer.currentTracks
        val group = tracks.groups.getOrNull(trackInfo.groupIndex) ?: return
        val trackGroup = group.mediaTrackGroup

        exoPlayer.trackSelectionParameters = exoPlayer.trackSelectionParameters
            .buildUpon()
            .setOverrideForType(
                TrackSelectionOverride(trackGroup, listOf(trackInfo.index))
            )
            .build()
    }

    @OptIn(UnstableApi::class)
    fun selectSubtitleTrack(trackInfo: TrackInfo?) {
        if (trackInfo == null) {
            exoPlayer.trackSelectionParameters = exoPlayer.trackSelectionParameters
                .buildUpon()
                .setTrackTypeDisabled(C.TRACK_TYPE_TEXT, true)
                .build()
            _uiState.value = _uiState.value.copy(subtitlesEnabled = false)
        } else {
            val tracks = exoPlayer.currentTracks
            val group = tracks.groups.getOrNull(trackInfo.groupIndex) ?: return
            val trackGroup = group.mediaTrackGroup

            exoPlayer.trackSelectionParameters = exoPlayer.trackSelectionParameters
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
                            perPage = 200,
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

                    val downloadsDir = Environment.getExternalStoragePublicDirectory(
                        Environment.DIRECTORY_DOWNLOADS
                    )
                    val localFile = File(downloadsDir, file.fileName)
                    val useLocalFile = localFile.exists() && localFile.length() > 0

                    val mediaItem: MediaItem
                    val mediaSourceFactory: DefaultMediaSourceFactory

                    if (useLocalFile) {
                        val localUri = Uri.fromFile(localFile)
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
        if (exoPlayer.isPlaying) {
            exoPlayer.pause()
            saveProgress()
        } else {
            exoPlayer.play()
        }
        showControls()
    }

    fun openInExternalPlayer(context: Context) {
        viewModelScope.launch {
            val file = _uiState.value.file ?: return@launch
            val serverUrl = settingsRepository.getServerUrl()
            
            val publicLinkResult = filesRepository.getPublicLink(file.id, serverUrl)
            
            val streamUrl = publicLinkResult.getOrElse {
                val token = authRepository.getAccessToken()
                if (token != null) {
                    "$serverUrl/api/stream/${file.id}?token=$token"
                } else {
                    "$serverUrl/api/stream/${file.id}"
                }
            }
            
            try {
                val intent = Intent(Intent.ACTION_VIEW).apply {
                    setDataAndType(Uri.parse(streamUrl), "video/*")
                    flags = Intent.FLAG_ACTIVITY_NEW_TASK
                }
                context.startActivity(intent)
            } catch (e: Exception) {
                e.printStackTrace()
            }
        }
    }

    private fun castToDevice() {
        val player = castPlayer ?: return
        viewModelScope.launch {
            val serverUrl = settingsRepository.getServerUrl().trimEnd('/')
            val token = authRepository.getAccessToken()
            
            // For Cast, we MUST use a query parameter as CastPlayer doesn't support headers easily
            val url = if (token != null) {
                "$serverUrl/api/stream/$currentFileId?token=$token"
            } else {
                "$serverUrl/api/stream/$currentFileId"
            }
            
            val file = _uiState.value.file
            val title = file?.fileName ?: "Aruvi"
            
            // Use query param for thumbnail as well for the cast device
            val thumbnailUrl = if (file?.thumbnailFileId != null) {
                "$serverUrl/api/stream/$currentFileId/thumbnail" + (if (token != null) "?token=$token" else "")
            } else null

            try {
                val mediaMetadata = MediaMetadata.Builder()
                    .setTitle(title)
                    .setArtworkUri(thumbnailUrl?.let { Uri.parse(it) })
                    .build()
                val mediaItem = MediaItem.Builder()
                    .setUri(url)
                    .setMediaId(currentFileId.toString())
                    .setMediaMetadata(mediaMetadata)
                    .build()
                exoPlayer.pause()
                player.setMediaItem(mediaItem)
                player.prepare()
                player.play()
            } catch (_: Throwable) {}
        }
    }

    fun stopCasting() {
        try {
            castPlayer?.stop()
            castPlayer?.clearMediaItems()
        } catch (_: Throwable) {}
    }

    fun play() {
        exoPlayer.play()
    }

    fun pause() {
        exoPlayer.pause()
    }

    fun seekTo(positionMs: Long) {
        val state = exoPlayer.playbackState
        if (state != Player.STATE_READY && state != Player.STATE_BUFFERING) return
        val clampedPosition = positionMs.coerceIn(0, exoPlayer.duration)
        exoPlayer.seekTo(clampedPosition)
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
        _uiState.value = _uiState.value.copy(seekSpeed = seekMs.toInt())
        return seekMs
    }

    fun seekBackward() {
        val seekMs = getAcceleratedSeekMs()
        val newPos = exoPlayer.currentPosition - seekMs
        seekTo(newPos)
        showSeekIndicator(seekMs, false)
    }

    fun seekForward() {
        val seekMs = getAcceleratedSeekMs()
        val newPos = exoPlayer.currentPosition + seekMs
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
        val dur = exoPlayer.duration
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
    }

    fun toggleJumpDialog() {
        _uiState.value = _uiState.value.copy(
            showJumpDialog = !_uiState.value.showJumpDialog
        )
        if (_uiState.value.showJumpDialog) {
            controlHideJob?.cancel()
        }
    }

    fun setPlaybackSpeed(speed: Float) {
        exoPlayer.setPlaybackSpeed(speed)
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
        exoPlayer.trackSelectionParameters = exoPlayer.trackSelectionParameters
            .buildUpon()
            .setMaxVideoSize(maxWidth, maxHeight)
            .build()
    }

    fun cyclePlaybackSpeed() {
        val speeds = listOf(0.5f, 0.75f, 1.0f, 1.25f, 1.5f, 2.0f)
        val currentIndex = speeds.indexOf(_uiState.value.playbackSpeed)
        val nextIndex = if (currentIndex < 0 || currentIndex >= speeds.size - 1) 0 else currentIndex + 1
        setPlaybackSpeed(speeds[nextIndex])
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
                
                if (exoPlayer.isPlaying) {
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
        _uiState.value = _uiState.value.copy(
            currentPosition = exoPlayer.currentPosition,
            bufferedPosition = exoPlayer.bufferedPosition,
            duration = exoPlayer.duration.coerceAtLeast(0)
        )
    }

    fun saveProgress(completed: Boolean = false) {
        val position = (exoPlayer.currentPosition / 1000).toInt()
        val duration = (exoPlayer.duration / 1000).toInt().takeIf { it > 0 }

        if (position <= 0 && !completed) return

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
        castPlayer?.let {
            try { it.removeListener(castPlayerListener) } catch (_: Throwable) {}
            try { it.release() } catch (_: Throwable) {}
        }
        saveProgress()
        if (!isBackgroundAudioActive) {
            exoPlayer.stop()
            exoPlayer.clearMediaItems()
        }
    }
}
