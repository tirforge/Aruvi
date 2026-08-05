package com.aruvi.tir.ui.player

import android.view.KeyEvent
import android.view.ViewGroup
import androidx.compose.animation.*
import androidx.compose.animation.core.animateFloatAsState
import androidx.compose.animation.core.tween
import androidx.compose.animation.core.spring
import androidx.compose.animation.core.Spring
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.focusable
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.automirrored.filled.OpenInNew
import androidx.compose.material.icons.automirrored.filled.VolumeUp
import androidx.compose.material.icons.filled.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.draw.shadow
import androidx.compose.ui.focus.FocusRequester
import androidx.compose.ui.focus.focusRequester
import androidx.compose.ui.focus.onFocusChanged
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.graphicsLayer
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.input.key.Key
import androidx.compose.ui.input.key.KeyEventType
import androidx.compose.ui.input.key.key
import androidx.compose.ui.input.key.onKeyEvent
import androidx.compose.ui.input.key.onPreviewKeyEvent
import androidx.compose.ui.input.key.type
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.viewinterop.AndroidView
import androidx.hilt.navigation.compose.hiltViewModel
import androidx.media3.ui.PlayerView
import androidx.media3.ui.SubtitleView
import com.aruvi.tir.ui.theme.*

/**
 * Full-screen media player with TV-optimized controls.
 * Enhanced with accelerating seek, jump-to-position, and playback speed.
 */
@Composable
fun PlayerScreen(
    onBackClick: () -> Unit,
    viewModel: PlayerViewModel = hiltViewModel()
) {
    val uiState by viewModel.uiState.collectAsState()
    val context = LocalContext.current
    val focusRequester = remember { FocusRequester() }
    val controlsFocusRequester = remember { FocusRequester() }
    var controlsFocused by remember { mutableStateOf(false) }

    // Handle back and save progress when leaving
    DisposableEffect(Unit) {
        onDispose {
            viewModel.onLeavePlayer()
        }
    }

    Box(
        modifier = Modifier
            .fillMaxSize()
            .background(Color.Black)
            .focusRequester(focusRequester)
            .focusable()
            .onPreviewKeyEvent { event ->
                if (event.nativeKeyEvent.action == KeyEvent.ACTION_DOWN) {
                    when (event.nativeKeyEvent.keyCode) {
                        KeyEvent.KEYCODE_DPAD_CENTER, KeyEvent.KEYCODE_ENTER -> {
                            when {
                                uiState.showJumpDialog -> false // dialog handles it
                                uiState.showSettings -> false   // settings handles it
                                uiState.error != null -> false  // error overlay handles it
                                // Controls are up: let the focused control handle
                                // ENTER, but if nothing has focus fall back to
                                // play/pause (same pattern as LEFT/RIGHT below).
                                uiState.showControls -> !controlsFocused
                                else -> {
                                    viewModel.togglePlayback()
                                    true
                                }
                            }
                        }
                        KeyEvent.KEYCODE_DPAD_LEFT -> {
                            // Seek when controls are hidden, OR when controls are shown
                            // but no control button currently has focus (so the focused
                            // Slider/buttons get a chance to handle navigation/scrubbing).
                            if (!uiState.showSettings && !uiState.showJumpDialog && uiState.error == null &&
                                (!uiState.showControls || !controlsFocused)
                            ) {
                                viewModel.seekBackward()
                                true
                            } else false
                        }
                        KeyEvent.KEYCODE_DPAD_RIGHT -> {
                            if (!uiState.showSettings && !uiState.showJumpDialog && uiState.error == null &&
                                (!uiState.showControls || !controlsFocused)
                            ) {
                                viewModel.seekForward()
                                true
                            } else false
                        }
                        KeyEvent.KEYCODE_DPAD_UP -> {
                            if (uiState.showSettings || uiState.showJumpDialog || uiState.error != null || uiState.showControls) {
                                false
                            } else {
                                viewModel.toggleSettings()
                                true
                            }
                        }
                        KeyEvent.KEYCODE_DPAD_DOWN -> {
                            if (uiState.showSettings || uiState.showJumpDialog || uiState.error != null || uiState.showControls) {
                                false
                            } else {
                                viewModel.showControls()
                                true
                            }
                        }
                        KeyEvent.KEYCODE_BACK -> {
                            when {
                                uiState.showJumpDialog -> {
                                    viewModel.toggleJumpDialog()
                                    true
                                }
                                uiState.showSettings -> {
                                    viewModel.hideSettings()
                                    true
                                }
                                // Hide controls first instead of leaving the player,
                                // so a stray BACK press doesn't exit playback.
                                // (Only while playing — hideControls() ignores the
                                // request when paused, which would trap BACK.)
                                uiState.showControls && uiState.isPlaying -> {
                                    viewModel.hideControls()
                                    true
                                }
                                else -> {
                                    onBackClick()
                                    true
                                }
                            }
                        }
                        KeyEvent.KEYCODE_MEDIA_PLAY_PAUSE -> {
                            viewModel.togglePlayback()
                            true
                        }
                        KeyEvent.KEYCODE_MEDIA_PLAY -> {
                            viewModel.play()
                            true
                        }
                        KeyEvent.KEYCODE_MEDIA_PAUSE -> {
                            viewModel.pause()
                            true
                        }
                        KeyEvent.KEYCODE_MEDIA_REWIND -> {
                            viewModel.seekBackward()
                            true
                        }
                        KeyEvent.KEYCODE_MEDIA_FAST_FORWARD -> {
                            viewModel.seekForward()
                            true
                        }
                        // Number keys 0-9 for jump-to-percent
                        KeyEvent.KEYCODE_0, KeyEvent.KEYCODE_NUMPAD_0 -> {
                            viewModel.jumpToPercent(0); true
                        }
                        KeyEvent.KEYCODE_1, KeyEvent.KEYCODE_NUMPAD_1 -> {
                            viewModel.jumpToPercent(10); true
                        }
                        KeyEvent.KEYCODE_2, KeyEvent.KEYCODE_NUMPAD_2 -> {
                            viewModel.jumpToPercent(20); true
                        }
                        KeyEvent.KEYCODE_3, KeyEvent.KEYCODE_NUMPAD_3 -> {
                            viewModel.jumpToPercent(30); true
                        }
                        KeyEvent.KEYCODE_4, KeyEvent.KEYCODE_NUMPAD_4 -> {
                            viewModel.jumpToPercent(40); true
                        }
                        KeyEvent.KEYCODE_5, KeyEvent.KEYCODE_NUMPAD_5 -> {
                            viewModel.jumpToPercent(50); true
                        }
                        KeyEvent.KEYCODE_6, KeyEvent.KEYCODE_NUMPAD_6 -> {
                            viewModel.jumpToPercent(60); true
                        }
                        KeyEvent.KEYCODE_7, KeyEvent.KEYCODE_NUMPAD_7 -> {
                            viewModel.jumpToPercent(70); true
                        }
                        KeyEvent.KEYCODE_8, KeyEvent.KEYCODE_NUMPAD_8 -> {
                            viewModel.jumpToPercent(80); true
                        }
                        KeyEvent.KEYCODE_9, KeyEvent.KEYCODE_NUMPAD_9 -> {
                            viewModel.jumpToPercent(90); true
                        }
                        else -> {
                            viewModel.showControls()
                            false
                        }
                    }
                } else {
                    false
                }
            }
    ) {
        // ExoPlayer Surface
        AndroidView(
            factory = { context ->
                PlayerView(context).apply {
                    useController = false
                    layoutParams = ViewGroup.LayoutParams(
                        ViewGroup.LayoutParams.MATCH_PARENT,
                        ViewGroup.LayoutParams.MATCH_PARENT
                    )
                    player = viewModel.exoPlayer
                }
            },
            update = { playerView ->
                playerView.player = viewModel.exoPlayer
                playerView.keepScreenOn = true
                playerView.resizeMode = uiState.toggleResizeMode
                // Apply the chosen subtitle size (fraction of video height).
                // MEDIUM (scale 1.0) restores the platform/user default.
                if (uiState.subtitleSize.scale == 1.0f) {
                    playerView.subtitleView?.setUserDefaultTextSize()
                } else {
                    playerView.subtitleView?.setFractionalTextSize(
                        SubtitleView.DEFAULT_TEXT_SIZE_FRACTION * uiState.subtitleSize.scale
                    )
                }
            },
            modifier = Modifier.fillMaxSize()
        )

        // Loading overlay
        AnimatedVisibility(
            visible = uiState.isLoading,
            enter = fadeIn(),
            exit = fadeOut()
        ) {
            LoadingOverlay()
        }

        // Buffering indicator
        AnimatedVisibility(
            visible = uiState.isBuffering && !uiState.isLoading,
            enter = fadeIn(),
            exit = fadeOut()
        ) {
            Box(
                modifier = Modifier.fillMaxSize(),
                contentAlignment = Alignment.Center
            ) {
                CircularProgressIndicator(
                    color = TVPrimary,
                    modifier = Modifier.size(56.dp),
                    strokeWidth = 4.dp
                )
            }
        }

        // Error overlay
        AnimatedVisibility(
            visible = uiState.error != null,
            enter = fadeIn(),
            exit = fadeOut()
        ) {
            uiState.error?.let { error ->
                val errorFocusRequester = remember { FocusRequester() }
                
                ErrorOverlay(
                    error = error,
                    onRetry = { viewModel.retry() },
                    onExternalPlayer = { viewModel.openInExternalPlayer(context) },
                    onBack = onBackClick,
                    focusRequester = errorFocusRequester
                )
                
                LaunchedEffect(error) {
                    kotlinx.coroutines.delay(200)
                    try {
                        errorFocusRequester.requestFocus()
                    } catch (e: Exception) {}
                }
            }
        }

        // Seek indicator overlay (centered)
        AnimatedVisibility(
            visible = uiState.showSeekIndicator,
            enter = fadeIn(animationSpec = tween(150)) + scaleIn(
                initialScale = 0.8f,
                animationSpec = spring(stiffness = Spring.StiffnessHigh)
            ),
            exit = fadeOut(animationSpec = tween(300))
        ) {
            SeekIndicatorOverlay(
                text = uiState.seekIndicatorText,
                isForward = uiState.seekIndicatorForward
            )
        }

        // Custom TV Controls Overlay
        AnimatedVisibility(
            visible = uiState.showControls && uiState.error == null,
            enter = fadeIn(animationSpec = tween(250)),
            exit = fadeOut(animationSpec = tween(400))
        ) {
            PlayerControls(
                fileName = uiState.file?.fileName ?: "",
                resolution = uiState.file?.resolution,
                isPlaying = uiState.isPlaying,
                currentPosition = uiState.currentPosition,
                bufferedPosition = uiState.bufferedPosition,
                duration = uiState.duration,
                playbackSpeed = uiState.playbackSpeed,
                resizeMode = uiState.toggleResizeMode,
                focusRequester = controlsFocusRequester,
                onFocusChanged = { controlsFocused = it },
                onPlayPause = { viewModel.togglePlayback() },
                onSeekBackward = { viewModel.seekBackward() },
                onSeekForward = { viewModel.seekForward() },
                onSeek = { viewModel.seekTo(it) },
                onCycleSpeed = { viewModel.cyclePlaybackSpeed() },
                onCycleResize = { viewModel.cycleResizeMode() },
                onSettings = { viewModel.toggleSettings() },
                onJumpTo = { viewModel.toggleJumpDialog() }
            )
        }

        // Settings Panel
        AnimatedVisibility(
            visible = uiState.showSettings,
            enter = slideInHorizontally(initialOffsetX = { it }),
            exit = slideOutHorizontally(targetOffsetX = { it })
        ) {
            SettingsPanel(
                audioTracks = uiState.audioTracks,
                subtitleTracks = uiState.subtitleTracks,
                subtitleSize = uiState.subtitleSize,
                subtitlesEnabled = uiState.subtitlesEnabled,
                playbackSpeed = uiState.playbackSpeed,
                preferredQuality = uiState.preferredQuality,
                currentResizeMode = uiState.toggleResizeMode,
                onSelectAudio = { viewModel.selectAudioTrack(it) },
                onSelectSubtitle = { viewModel.selectSubtitleTrack(it) },
                onSubtitleSizeChange = { viewModel.setSubtitleSize(it) },
                onSpeedChange = { viewModel.setPlaybackSpeed(it) },
                onQualityChange = { viewModel.setPreferredQuality(it) },
                onResizeModeChange = { viewModel.setResizeMode(it) },
                onOpenExternal = { viewModel.openInExternalPlayer(context) },
                onClose = { viewModel.hideSettings() }
            )
        }

        // Jump-to-position dialog
        AnimatedVisibility(
            visible = uiState.showJumpDialog,
            enter = fadeIn() + scaleIn(initialScale = 0.9f),
            exit = fadeOut() + scaleOut(targetScale = 0.9f)
        ) {
            JumpToPositionDialog(
                duration = uiState.duration,
                onJump = { h, m, s -> viewModel.jumpToTimestamp(h, m, s) },
                onDismiss = { viewModel.toggleJumpDialog() }
            )
        }
    }

    // Request focus on launch
    LaunchedEffect(Unit) {
        kotlinx.coroutines.delay(100)
        try {
            focusRequester.requestFocus()
        } catch (e: IllegalStateException) {
            // Ignore
        }
    }

    // When controls appear, move focus to the seek bar so the D-pad scrubs
    // immediately (standard streaming-app behavior). UP/DOWN then navigates
    // to the control buttons.
    LaunchedEffect(uiState.showControls, uiState.showSettings, uiState.showJumpDialog, uiState.error) {
        val canFocusControls = uiState.showControls &&
            !uiState.showSettings &&
            !uiState.showJumpDialog &&
            uiState.error == null
        if (canFocusControls) {
            kotlinx.coroutines.delay(300)
            try {
                controlsFocusRequester.requestFocus()
            } catch (e: IllegalStateException) {
                // Ignore
            }
        } else if (!uiState.showControls) {
            // Controls left composition; onFocusChanged may not fire, so reset
            // the flag to avoid blocking root LEFT/RIGHT seeking.
            controlsFocused = false
        }
    }
}

// ─── Seek Indicator ─────────────────────────────────────────────────

/**
 * Large centered seek indicator showing e.g. "◀◀ -30s" or "▶▶ +2min".
 */
@Composable
private fun SeekIndicatorOverlay(
    text: String,
    isForward: Boolean
) {
    Box(
        modifier = Modifier.fillMaxSize(),
        contentAlignment = Alignment.Center
    ) {
        Surface(
            color = Color.Black.copy(alpha = 0.7f),
            shape = RoundedCornerShape(20.dp),
            modifier = Modifier.shadow(
                elevation = 16.dp,
                shape = RoundedCornerShape(20.dp),
                ambientColor = TVPrimary.copy(alpha = 0.3f)
            )
        ) {
            Row(
                modifier = Modifier.padding(horizontal = 36.dp, vertical = 20.dp),
                verticalAlignment = Alignment.CenterVertically,
                horizontalArrangement = Arrangement.Center
            ) {
                if (!isForward) {
                    Icon(
                        imageVector = Icons.Default.FastRewind,
                        contentDescription = null,
                        tint = TVSecondary,
                        modifier = Modifier.size(36.dp)
                    )
                    Spacer(modifier = Modifier.width(12.dp))
                }
                Text(
                    text = text,
                    color = Color.White,
                    fontSize = 32.sp,
                    fontWeight = FontWeight.Bold
                )
                if (isForward) {
                    Spacer(modifier = Modifier.width(12.dp))
                    Icon(
                        imageVector = Icons.Default.FastForward,
                        contentDescription = null,
                        tint = TVSecondary,
                        modifier = Modifier.size(36.dp)
                    )
                }
            }
        }
    }
}

// ─── Loading Overlay ────────────────────────────────────────────────

@Composable
private fun LoadingOverlay() {
    Box(
        modifier = Modifier
            .fillMaxSize()
            .background(
                Brush.radialGradient(
                    colors = listOf(
                        Color.Black.copy(alpha = 0.9f),
                        Color.Black.copy(alpha = 0.95f)
                    )
                )
            ),
        contentAlignment = Alignment.Center
    ) {
        Column(horizontalAlignment = Alignment.CenterHorizontally) {
            CircularProgressIndicator(
                color = TVPrimary,
                modifier = Modifier.size(72.dp),
                strokeWidth = 5.dp,
                trackColor = TVPrimary.copy(alpha = 0.15f)
            )
            Spacer(modifier = Modifier.height(28.dp))
            Text(
                text = "Preparing video...",
                style = MaterialTheme.typography.titleLarge,
                color = TVTextPrimary,
                fontWeight = FontWeight.Medium
            )
            Spacer(modifier = Modifier.height(8.dp))
            Text(
                text = "Connecting to stream",
                style = MaterialTheme.typography.bodyMedium,
                color = TVTextSecondary.copy(alpha = 0.6f)
            )
        }
    }
}

// ─── Error Overlay ──────────────────────────────────────────────────

@Composable
private fun ErrorOverlay(
    error: PlaybackError,
    onRetry: () -> Unit,
    onExternalPlayer: () -> Unit,
    onBack: () -> Unit,
    focusRequester: FocusRequester = remember { FocusRequester() }
) {
    var showDetails by remember { mutableStateOf(false) }

    Box(
        modifier = Modifier
            .fillMaxSize()
            .background(Color.Black.copy(alpha = 0.92f)),
        contentAlignment = Alignment.Center
    ) {
        Column(
            horizontalAlignment = Alignment.CenterHorizontally,
            modifier = Modifier
                .widthIn(max = 600.dp)
                .padding(48.dp)
        ) {
            val errorIcon = when (error.errorType) {
                ErrorType.CODEC_NOT_SUPPORTED -> Icons.Default.VideoFile
                ErrorType.NETWORK_ERROR -> Icons.Default.WifiOff
                ErrorType.AUTH_ERROR -> Icons.Default.Lock
                ErrorType.FILE_NOT_FOUND -> Icons.Default.SearchOff
                ErrorType.UNKNOWN -> Icons.Default.Error
            }

            // Glowing error icon
            Box(
                contentAlignment = Alignment.Center,
                modifier = Modifier
                    .size(100.dp)
                    .background(
                        color = TVError.copy(alpha = 0.1f),
                        shape = CircleShape
                    )
            ) {
                Icon(
                    imageVector = errorIcon,
                    contentDescription = null,
                    tint = TVError,
                    modifier = Modifier.size(56.dp)
                )
            }

            Spacer(modifier = Modifier.height(28.dp))

            Text(
                text = error.title,
                style = MaterialTheme.typography.headlineMedium,
                color = TVTextPrimary,
                fontWeight = FontWeight.Bold,
                textAlign = TextAlign.Center
            )

            Spacer(modifier = Modifier.height(16.dp))

            Text(
                text = error.description,
                style = MaterialTheme.typography.bodyLarge,
                color = TVTextSecondary,
                textAlign = TextAlign.Center,
                lineHeight = 24.sp
            )

            if (error.technicalDetails != null) {
                Spacer(modifier = Modifier.height(16.dp))
                TextButton(onClick = { showDetails = !showDetails }) {
                    Text(
                        text = if (showDetails) "Hide details" else "Show technical details",
                        color = TVTextSecondary.copy(alpha = 0.7f),
                        fontSize = 12.sp
                    )
                }
                AnimatedVisibility(visible = showDetails) {
                    Surface(
                        color = Color.Black.copy(alpha = 0.5f),
                        shape = RoundedCornerShape(8.dp),
                        modifier = Modifier.padding(top = 8.dp)
                    ) {
                        Text(
                            text = error.technicalDetails,
                            style = MaterialTheme.typography.bodySmall,
                            color = TVTextSecondary.copy(alpha = 0.6f),
                            modifier = Modifier.padding(12.dp),
                            fontSize = 10.sp
                        )
                    }
                }
            }

            Spacer(modifier = Modifier.height(32.dp))

            Row(horizontalArrangement = Arrangement.spacedBy(16.dp)) {
                PlayerActionButton(
                    text = "Go Back",
                    icon = Icons.AutoMirrored.Filled.ArrowBack,
                    onClick = onBack,
                    isPrimary = !error.canRetry,
                    modifier = Modifier.focusRequester(focusRequester)
                )
                
                PlayerActionButton(
                    text = "External Player",
                    icon = Icons.AutoMirrored.Filled.OpenInNew,
                    onClick = onExternalPlayer,
                    isPrimary = false
                )
                
                if (error.canRetry) {
                    PlayerActionButton(
                        text = "Retry",
                        icon = Icons.Default.Refresh,
                        onClick = onRetry,
                        isPrimary = true
                    )
                }
            }
        }
    }
}

@Composable
private fun PlayerActionButton(
    text: String,
    icon: ImageVector,
    onClick: () -> Unit,
    isPrimary: Boolean = false,
    modifier: Modifier = Modifier
) {
    var isFocused by remember { mutableStateOf(false) }

    Surface(
        onClick = onClick,
        color = when {
            isPrimary && isFocused -> TVPrimary
            isPrimary -> TVPrimary.copy(alpha = 0.85f)
            isFocused -> TVCardFocused
            else -> Color.Transparent
        },
        shape = RoundedCornerShape(12.dp),
        modifier = modifier
            .onFocusChanged { isFocused = it.isFocused }
            .border(
                width = if (isFocused) 2.dp else 1.dp,
                color = if (isFocused) TVFocusRing else TVTextSecondary.copy(alpha = 0.2f),
                shape = RoundedCornerShape(12.dp)
            )
    ) {
        Row(
            modifier = Modifier.padding(horizontal = 28.dp, vertical = 14.dp),
            verticalAlignment = Alignment.CenterVertically
        ) {
            Icon(
                imageVector = icon,
                contentDescription = null,
                tint = if (isPrimary) Color.White else TVTextPrimary,
                modifier = Modifier.size(20.dp)
            )
            Spacer(modifier = Modifier.width(10.dp))
            Text(
                text = text,
                color = if (isPrimary) Color.White else TVTextPrimary,
                fontWeight = FontWeight.Medium,
                fontSize = 15.sp
            )
        }
    }
}

// ─── Player Controls ────────────────────────────────────────────────

@Composable
private fun PlayerControls(
    fileName: String,
    resolution: String?,
    isPlaying: Boolean,
    currentPosition: Long,
    bufferedPosition: Long,
    duration: Long,
    playbackSpeed: Float,
    resizeMode: Int,
    focusRequester: FocusRequester,
    onFocusChanged: (Boolean) -> Unit,
    onPlayPause: () -> Unit,
    onSeekBackward: () -> Unit,
    onSeekForward: () -> Unit,
    onSeek: (Long) -> Unit,
    onCycleSpeed: () -> Unit,
    onCycleResize: () -> Unit,
    onSettings: () -> Unit,
    onJumpTo: () -> Unit
) {
    Box(
        modifier = Modifier
            .fillMaxSize()
            .background(
                Brush.verticalGradient(
                    colors = listOf(
                        Color.Black.copy(alpha = 0.85f),
                        Color.Transparent,
                        Color.Transparent,
                        Color.Black.copy(alpha = 0.92f)
                    )
                )
            )
            // Track whether any control inside has focus so the root key
            // handler knows when to let the focused control own LEFT/RIGHT.
            // Note: must use hasFocus (descendant focus); isFocused is only
            // true when this non-focusable Box itself owns focus (never).
            .onFocusChanged { onFocusChanged(it.hasFocus) }
    ) {
        // ── Top bar ──
        Row(
            modifier = Modifier
                .fillMaxWidth()
                .padding(horizontal = 32.dp, vertical = 24.dp)
                .align(Alignment.TopStart),
            verticalAlignment = Alignment.CenterVertically
        ) {
            Column(modifier = Modifier.weight(1f)) {
                Text(
                    text = fileName,
                    style = MaterialTheme.typography.titleLarge,
                    color = TVTextPrimary,
                    fontWeight = FontWeight.SemiBold,
                    maxLines = 1,
                    overflow = TextOverflow.Ellipsis
                )
                Row(
                    verticalAlignment = Alignment.CenterVertically,
                    horizontalArrangement = Arrangement.spacedBy(12.dp)
                ) {
                    if (resolution != null) {
                        ResolutionBadge(resolution)
                    }
                    if (playbackSpeed != 1.0f) {
                        SpeedBadge(playbackSpeed)
                    }
                }
            }

            // Jump button
            ControlIconButton(
                icon = Icons.Default.Timer,
                contentDescription = "Jump to time",
                onClick = onJumpTo,
                size = 44.dp
            )

            Spacer(modifier = Modifier.width(8.dp))

            // Settings button (always visible)
            ControlIconButton(
                icon = Icons.Default.Settings,
                contentDescription = "Settings",
                onClick = onSettings,
                size = 44.dp
            )
        }

        // ── Bottom controls ──
        Column(
            modifier = Modifier
                .fillMaxWidth()
                .align(Alignment.BottomCenter)
                .padding(horizontal = 48.dp, vertical = 32.dp)
        ) {
            // Enhanced progress bar (gets initial focus so LEFT/RIGHT scrubs
            // immediately — the standard streaming-app seek behavior)
            if (duration > 0) {
                EnhancedSeekBar(
                    currentPosition = currentPosition,
                    bufferedPosition = bufferedPosition,
                    duration = duration,
                    onSeek = onSeek,
                    onSeekBackward = onSeekBackward,
                    onSeekForward = onSeekForward,
                    onPlayPause = onPlayPause,
                    focusRequester = focusRequester
                )
            }

            Spacer(modifier = Modifier.height(8.dp))

            // Time display
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.SpaceBetween
            ) {
                TimeDisplay(formatDuration(currentPosition))
                if (duration > 0) {
                    val remaining = duration - currentPosition
                    TimeDisplay("-${formatDuration(remaining)}")
                }
            }

            Spacer(modifier = Modifier.height(24.dp))

            // Quick cycle buttons: Speed and Resize (one press each, label shows current value)
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.Center,
                verticalAlignment = Alignment.CenterVertically
            ) {
                QuickCycleButton(
                    label = "${speedLabel(playbackSpeed)}x",
                    onClick = onCycleSpeed
                )
                Spacer(modifier = Modifier.width(24.dp))
                QuickCycleButton(
                    label = resizeLabel(resizeMode),
                    onClick = onCycleResize
                )
            }

            Spacer(modifier = Modifier.height(16.dp))

            // Playback controls
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.Center,
                verticalAlignment = Alignment.CenterVertically
            ) {
                ControlIconButton(
                    icon = Icons.Default.Replay10,
                    contentDescription = "Rewind",
                    onClick = onSeekBackward,
                    size = 56.dp,
                    iconSize = 32.dp
                )

                Spacer(modifier = Modifier.width(40.dp))

                PlayPauseButton(
                    isPlaying = isPlaying,
                    onClick = onPlayPause
                )

                Spacer(modifier = Modifier.width(40.dp))

                ControlIconButton(
                    icon = Icons.Default.Forward10,
                    contentDescription = "Forward",
                    onClick = onSeekForward,
                    size = 56.dp,
                    iconSize = 32.dp
                )
            }

            // Keyboard shortcut hint
            Spacer(modifier = Modifier.height(16.dp))
            Text(
                text = "Hold ◀▶ to fast seek  •  0-9 jump to %",
                style = MaterialTheme.typography.bodySmall,
                color = TVTextSecondary.copy(alpha = 0.4f),
                textAlign = TextAlign.Center,
                modifier = Modifier.fillMaxWidth()
            )
        }
    }
}

// ─── Enhanced Seek Bar ──────────────────────────────────────────────

@Composable
private fun EnhancedSeekBar(
    currentPosition: Long,
    bufferedPosition: Long,
    duration: Long,
    onSeek: (Long) -> Unit,
    onSeekBackward: () -> Unit,
    onSeekForward: () -> Unit,
    onPlayPause: () -> Unit,
    focusRequester: FocusRequester? = null
) {
    // progress calculation removed as it was unused
    val bufferedProgress = (bufferedPosition.toFloat() / duration.toFloat()).coerceIn(0f, 1f)

    // Local drag position so the thumb tracks the finger without firing a
    // seek on every drag delta; the actual seek happens once on release.
    var dragPosition by remember { mutableStateOf<Long?>(null) }
    val sliderValue = (dragPosition ?: currentPosition).toFloat()

    // Highlight the whole seek bar when it has focus so it's obvious that
    // LEFT/RIGHT will scrub (streaming-app style). hasFocus (not isFocused):
    // the Box itself isn't focusable — the Slider child is.
    var seekBarFocused by remember { mutableStateOf(false) }

    Column {
        Box(
            modifier = Modifier
                .fillMaxWidth()
                .onFocusChanged { seekBarFocused = it.hasFocus }
                .border(
                    width = if (seekBarFocused) 2.dp else 0.dp,
                    color = if (seekBarFocused) TVFocusRing.copy(alpha = 0.8f) else Color.Transparent,
                    shape = RoundedCornerShape(6.dp)
                )
        ) {
            // Track background
            Box(
                modifier = Modifier
                    .fillMaxWidth()
                    .height(6.dp)
                    .clip(RoundedCornerShape(3.dp))
                    .background(TVProgressBackground)
                    .align(Alignment.Center)
            )

            // Buffered progress
            Box(
                modifier = Modifier
                    .fillMaxWidth(bufferedProgress)
                    .height(6.dp)
                    .clip(RoundedCornerShape(3.dp))
                    .background(TVPrimary.copy(alpha = 0.25f))
                    .align(Alignment.CenterStart)
            )

            // Chapter marks (10% intervals)
            if (duration > 60_000) { // Only for videos > 1 min
                Row(modifier = Modifier.fillMaxWidth().height(6.dp).align(Alignment.Center)) {
                    for (i in 1..9) {
                        Box(
                            modifier = Modifier
                                .weight(1f)
                                .fillMaxHeight()
                        ) {
                            Box(
                                modifier = Modifier
                                    .width(1.dp)
                                    .fillMaxHeight()
                                    .background(Color.White.copy(alpha = 0.08f))
                                    .align(Alignment.CenterEnd)
                            )
                        }
                    }
                    Box(modifier = Modifier.weight(1f))
                }
            }

            // Playback slider. Focused by default when controls appear; DPAD
            // LEFT/RIGHT drives the accelerated seek (with the big overlay
            // indicator) — the standard streaming-app behavior.
            Slider(
                value = sliderValue,
                onValueChange = { dragPosition = it.toLong() },
                onValueChangeFinished = {
                    dragPosition?.let {
                        dragPosition = null
                        onSeek(it)
                    }
                },
                valueRange = 0f..duration.toFloat(),
                steps = (duration / 10_000L).toInt().coerceAtLeast(0),
                modifier = Modifier
                    .fillMaxWidth()
                    .focusable()
                    .then(
                        if (focusRequester != null) Modifier.focusRequester(focusRequester) else Modifier
                    )
                    .onKeyEvent { event ->
                        if (event.type == KeyEventType.KeyDown) {
                            when (event.key) {
                                Key.DirectionLeft -> {
                                    onSeekBackward()
                                    true
                                }
                                Key.DirectionRight -> {
                                    onSeekForward()
                                    true
                                }
                                Key.DirectionCenter, Key.Enter -> {
                                    onPlayPause()
                                    true
                                }
                                else -> false
                            }
                        } else false
                    },
                colors = SliderDefaults.colors(
                    thumbColor = TVPrimary,
                    activeTrackColor = TVPrimary,
                    inactiveTrackColor = Color.Transparent
                )
            )
        }
    }
}

// ─── Badges ─────────────────────────────────────────────────────────

@Composable
private fun ResolutionBadge(resolution: String) {
    Surface(
        color = TVPrimary.copy(alpha = 0.15f),
        shape = RoundedCornerShape(4.dp)
    ) {
        Text(
            text = resolution,
            style = MaterialTheme.typography.labelSmall,
            color = TVPrimaryLight,
            fontWeight = FontWeight.SemiBold,
            modifier = Modifier.padding(horizontal = 8.dp, vertical = 2.dp)
        )
    }
}

@Composable
private fun SpeedBadge(speed: Float) {
    Surface(
        color = TVSecondary.copy(alpha = 0.15f),
        shape = RoundedCornerShape(4.dp)
    ) {
        Text(
            text = "${speed}x",
            style = MaterialTheme.typography.labelSmall,
            color = TVSecondary,
            fontWeight = FontWeight.Bold,
            modifier = Modifier.padding(horizontal = 8.dp, vertical = 2.dp)
        )
    }
}

// ─── Time Display ───────────────────────────────────────────────────

@Composable
private fun TimeDisplay(time: String) {
    Surface(
        color = Color.Black.copy(alpha = 0.4f),
        shape = RoundedCornerShape(6.dp)
    ) {
        Text(
            text = time,
            style = MaterialTheme.typography.titleMedium,
            color = TVTextPrimary,
            fontWeight = FontWeight.Medium,
            modifier = Modifier.padding(horizontal = 14.dp, vertical = 5.dp),
            letterSpacing = 0.5.sp
        )
    }
}

// ─── Play/Pause Button ──────────────────────────────────────────────

@Composable
private fun PlayPauseButton(
    isPlaying: Boolean,
    onClick: () -> Unit
) {
    var isFocused by remember { mutableStateOf(false) }
    val scale by animateFloatAsState(
        targetValue = if (isFocused) 1.1f else 1f,
        animationSpec = spring(stiffness = Spring.StiffnessMedium),
        label = "playBtnScale"
    )

    Surface(
        onClick = onClick,
        color = if (isFocused) TVPrimary else TVPrimary.copy(alpha = 0.9f),
        shape = CircleShape,
        modifier = Modifier
            .size(80.dp)
            .graphicsLayer { scaleX = scale; scaleY = scale }
            .onFocusChanged { isFocused = it.isFocused }
            .then(
                if (isFocused) Modifier.shadow(
                    elevation = 20.dp,
                    shape = CircleShape,
                    ambientColor = TVPrimary.copy(alpha = 0.6f)
                ) else Modifier
            )
    ) {
        Box(contentAlignment = Alignment.Center) {
            Icon(
                imageVector = if (isPlaying) Icons.Default.Pause else Icons.Default.PlayArrow,
                contentDescription = if (isPlaying) "Pause" else "Play",
                tint = Color.White,
                modifier = Modifier.size(48.dp)
            )
        }
    }
}

// ─── Control Icon Button ────────────────────────────────────────────

@Composable
private fun ControlIconButton(
    icon: ImageVector,
    contentDescription: String,
    onClick: () -> Unit,
    size: androidx.compose.ui.unit.Dp = 48.dp,
    iconSize: androidx.compose.ui.unit.Dp = 24.dp
) {
    var isFocused by remember { mutableStateOf(false) }
    val scale by animateFloatAsState(
        targetValue = if (isFocused) 1.12f else 1f,
        animationSpec = spring(
            dampingRatio = Spring.DampingRatioNoBouncy,
            stiffness = Spring.StiffnessHigh
        ),
        label = "ctrlBtnScale"
    )

    Surface(
        onClick = onClick,
        color = if (isFocused) TVPrimary.copy(alpha = 0.3f) else Color.Transparent,
        shape = CircleShape,
        modifier = Modifier
            .size(size)
            .graphicsLayer { scaleX = scale; scaleY = scale }
            .onFocusChanged { isFocused = it.isFocused }
            .border(
                width = if (isFocused) 2.dp else 0.dp,
                color = if (isFocused) TVFocusRing else Color.Transparent,
                shape = CircleShape
            )
    ) {
        Box(contentAlignment = Alignment.Center) {
            Icon(
                imageVector = icon,
                contentDescription = contentDescription,
                tint = if (isFocused) Color.White else TVTextPrimary,
                modifier = Modifier.size(iconSize)
            )
        }
    }
}

// ─── Quick Cycle Button (Speed / Resize) ────────────────────────────

@Composable
private fun QuickCycleButton(
    label: String,
    onClick: () -> Unit
) {
    var isFocused by remember { mutableStateOf(false) }

    Surface(
        onClick = onClick,
        color = if (isFocused) TVPrimary.copy(alpha = 0.3f) else Color.Transparent,
        shape = RoundedCornerShape(10.dp),
        modifier = Modifier
            .onFocusChanged { isFocused = it.isFocused }
            .border(
                width = if (isFocused) 2.dp else 1.dp,
                color = if (isFocused) TVFocusRing else TVTextSecondary.copy(alpha = 0.2f),
                shape = RoundedCornerShape(10.dp)
            )
    ) {
        Row(
            modifier = Modifier.padding(horizontal = 18.dp, vertical = 8.dp),
            verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.spacedBy(8.dp)
        ) {
            Text(
                text = label,
                color = if (isFocused) Color.White else TVTextPrimary,
                fontWeight = FontWeight.Medium,
                fontSize = 14.sp
            )
            Text(
                text = "◀▶",
                color = TVTextSecondary.copy(alpha = 0.5f),
                fontSize = 12.sp
            )
        }
    }
}

private fun speedLabel(speed: Float): String =
    if (speed == speed.toInt().toFloat()) speed.toInt().toString() else speed.toString()

private fun resizeLabel(mode: Int): String = when (mode) {
    androidx.media3.ui.AspectRatioFrameLayout.RESIZE_MODE_FILL -> "Fill"
    androidx.media3.ui.AspectRatioFrameLayout.RESIZE_MODE_ZOOM -> "Zoom"
    else -> "Fit"
}

// ─── Jump-to-Position Dialog ────────────────────────────────────────

@Composable
private fun JumpToPositionDialog(
    duration: Long,
    onJump: (Int, Int, Int) -> Unit,
    onDismiss: () -> Unit
) {
    var hours by remember { mutableStateOf("") }
    var minutes by remember { mutableStateOf("") }
    var seconds by remember { mutableStateOf("") }
    val focusRequesterH = remember { FocusRequester() }
    val focusRequesterM = remember { FocusRequester() }
    val focusRequesterS = remember { FocusRequester() }
    val durationText = formatDuration(duration)
    val showHours = duration >= 3600_000

    Box(
        modifier = Modifier
            .fillMaxSize()
            .background(Color.Black.copy(alpha = 0.75f))
            .clickable(onClick = onDismiss),
        contentAlignment = Alignment.Center
    ) {
        Surface(
            color = Color(0xFF1A1D23),
            shape = RoundedCornerShape(20.dp),
            modifier = Modifier
                .widthIn(max = 420.dp)
                .border(1.dp, TVPrimary.copy(alpha = 0.3f), RoundedCornerShape(20.dp))
                .clickable(onClick = {}) // prevent click-through
        ) {
            Column(
                modifier = Modifier.padding(32.dp),
                horizontalAlignment = Alignment.CenterHorizontally
            ) {
                Icon(
                    imageVector = Icons.Default.Timer,
                    contentDescription = null,
                    tint = TVPrimary,
                    modifier = Modifier.size(36.dp)
                )
                Spacer(modifier = Modifier.height(16.dp))
                Text(
                    text = "Jump to Time",
                    style = MaterialTheme.typography.titleLarge,
                    color = TVTextPrimary,
                    fontWeight = FontWeight.Bold
                )
                Spacer(modifier = Modifier.height(8.dp))
                Text(
                    text = "Duration: $durationText",
                    style = MaterialTheme.typography.bodySmall,
                    color = TVTextSecondary
                )
                Spacer(modifier = Modifier.height(24.dp))

                // Time input fields
                Row(
                    horizontalArrangement = Arrangement.spacedBy(8.dp),
                    verticalAlignment = Alignment.CenterVertically
                ) {
                    if (showHours) {
                        TimeInputField(
                            value = hours,
                            onValueChange = { if (it.length <= 2 && it.all { c -> c.isDigit() }) hours = it },
                            label = "HH",
                            focusRequester = focusRequesterH
                        )
                        Text(":", color = TVTextPrimary, fontSize = 28.sp, fontWeight = FontWeight.Bold)
                    }
                    TimeInputField(
                        value = minutes,
                        onValueChange = { if (it.length <= 2 && it.all { c -> c.isDigit() }) minutes = it },
                        label = "MM",
                        focusRequester = focusRequesterM
                    )
                    Text(":", color = TVTextPrimary, fontSize = 28.sp, fontWeight = FontWeight.Bold)
                    TimeInputField(
                        value = seconds,
                        onValueChange = { if (it.length <= 2 && it.all { c -> c.isDigit() }) seconds = it },
                        label = "SS",
                        focusRequester = focusRequesterS
                    )
                }

                Spacer(modifier = Modifier.height(28.dp))

                // Quick jump buttons
                Text(
                    text = "Quick Jump",
                    style = MaterialTheme.typography.labelMedium,
                    color = TVTextSecondary,
                    modifier = Modifier.fillMaxWidth()
                )
                Spacer(modifier = Modifier.height(8.dp))
                Row(
                    horizontalArrangement = Arrangement.spacedBy(8.dp),
                    modifier = Modifier.fillMaxWidth()
                ) {
                    listOf(25, 50, 75).forEach { percent ->
                        val targetMs = duration * percent / 100
                        QuickJumpChip(
                            label = "$percent%",
                            subtitle = formatDuration(targetMs),
                            onClick = {
                                val totalSec = (targetMs / 1000).toInt()
                                onJump(totalSec / 3600, (totalSec % 3600) / 60, totalSec % 60)
                            },
                            modifier = Modifier.weight(1f)
                        )
                    }
                }

                Spacer(modifier = Modifier.height(20.dp))

                // Action buttons
                Row(horizontalArrangement = Arrangement.spacedBy(12.dp)) {
                    PlayerActionButton(
                        text = "Cancel",
                        icon = Icons.Default.Close,
                        onClick = onDismiss,
                        isPrimary = false
                    )
                    PlayerActionButton(
                        text = "Jump",
                        icon = Icons.Default.PlayArrow,
                        onClick = {
                            val h = hours.toIntOrNull() ?: 0
                            val m = minutes.toIntOrNull() ?: 0
                            val s = seconds.toIntOrNull() ?: 0
                            onJump(h, m, s)
                        },
                        isPrimary = true
                    )
                }
            }
        }
    }

    // Focus first input
    LaunchedEffect(Unit) {
        kotlinx.coroutines.delay(200)
        try {
            if (showHours) focusRequesterH.requestFocus()
            else focusRequesterM.requestFocus()
        } catch (e: Exception) { /* ignore */ }
    }
}

@Composable
private fun TimeInputField(
    value: String,
    onValueChange: (String) -> Unit,
    label: String,
    focusRequester: FocusRequester
) {
    var isFocused by remember { mutableStateOf(false) }

    Column(horizontalAlignment = Alignment.CenterHorizontally) {
        Surface(
            color = if (isFocused) TVPrimary.copy(alpha = 0.15f) else TVSurfaceVariant,
            shape = RoundedCornerShape(12.dp),
            modifier = Modifier
                .size(72.dp)
                .border(
                    width = if (isFocused) 2.dp else 1.dp,
                    color = if (isFocused) TVPrimary else TVTextSecondary.copy(alpha = 0.2f),
                    shape = RoundedCornerShape(12.dp)
                )
        ) {
            Box(contentAlignment = Alignment.Center) {
                if (value.isEmpty()) {
                    Text(
                        text = label,
                        color = TVTextDisabled,
                        fontSize = 20.sp,
                        fontWeight = FontWeight.Bold
                    )
                }
                androidx.compose.foundation.text.BasicTextField(
                    value = value,
                    onValueChange = onValueChange,
                    textStyle = androidx.compose.ui.text.TextStyle(
                        color = TVTextPrimary,
                        fontSize = 28.sp,
                        fontWeight = FontWeight.Bold,
                        textAlign = TextAlign.Center
                    ),
                    singleLine = true,
                    modifier = Modifier
                        .fillMaxSize()
                        .focusRequester(focusRequester)
                        .onFocusChanged { isFocused = it.isFocused }
                        .padding(8.dp),
                    keyboardOptions = androidx.compose.foundation.text.KeyboardOptions(
                        keyboardType = androidx.compose.ui.text.input.KeyboardType.Number
                    )
                )
            }
        }
    }
}

@Composable
private fun QuickJumpChip(
    label: String,
    subtitle: String,
    onClick: () -> Unit,
    modifier: Modifier = Modifier
) {
    var isFocused by remember { mutableStateOf(false) }

    Surface(
        onClick = onClick,
        color = if (isFocused) TVPrimary.copy(alpha = 0.2f) else TVSurfaceVariant,
        shape = RoundedCornerShape(10.dp),
        modifier = modifier
            .onFocusChanged { isFocused = it.isFocused }
            .border(
                width = if (isFocused) 2.dp else 0.dp,
                color = if (isFocused) TVPrimary else Color.Transparent,
                shape = RoundedCornerShape(10.dp)
            )
    ) {
        Column(
            modifier = Modifier.padding(12.dp),
            horizontalAlignment = Alignment.CenterHorizontally
        ) {
            Text(
                text = label,
                color = if (isFocused) TVPrimary else TVTextPrimary,
                fontWeight = FontWeight.Bold,
                fontSize = 16.sp
            )
            Text(
                text = subtitle,
                color = TVTextSecondary,
                fontSize = 11.sp
            )
        }
    }
}

// ─── Settings Panel ─────────────────────────────────────────────────

@Composable
private fun SettingsPanel(
    audioTracks: List<TrackInfo>,
    subtitleTracks: List<TrackInfo>,
    subtitleSize: SubtitleSize,
    subtitlesEnabled: Boolean,
    playbackSpeed: Float,
    preferredQuality: String,
    currentResizeMode: Int,
    onSelectAudio: (TrackInfo) -> Unit,
    onSelectSubtitle: (TrackInfo?) -> Unit,
    onSubtitleSizeChange: (SubtitleSize) -> Unit,
    onSpeedChange: (Float) -> Unit,
    onQualityChange: (String) -> Unit,
    onResizeModeChange: (Int) -> Unit,
    onOpenExternal: () -> Unit,
    onClose: () -> Unit
) {
    val firstItemFocusRequester = remember { FocusRequester() }

    Box(modifier = Modifier.fillMaxSize()) {
        // Backdrop
        Box(
            modifier = Modifier
                .fillMaxSize()
                .background(Color.Black.copy(alpha = 0.6f))
                .clickable(onClick = onClose)
        )

        // Panel
        Surface(
            modifier = Modifier
                .fillMaxHeight()
                .width(420.dp)
                .align(Alignment.CenterEnd),
            color = Color(0xFF141720),
            shape = RoundedCornerShape(topStart = 20.dp, bottomStart = 20.dp)
        ) {
            Column(
                modifier = Modifier
                    .fillMaxSize()
                    .padding(20.dp)
            ) {
                // Header
                Row(
                    modifier = Modifier
                        .fillMaxWidth()
                        .padding(bottom = 20.dp),
                    horizontalArrangement = Arrangement.SpaceBetween,
                    verticalAlignment = Alignment.CenterVertically
                ) {
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        Icon(
                            imageVector = Icons.Default.Tune,
                            contentDescription = null,
                            tint = TVPrimary,
                            modifier = Modifier.size(24.dp)
                        )
                        Spacer(modifier = Modifier.width(12.dp))
                        Text(
                            text = "Settings",
                            style = MaterialTheme.typography.titleLarge,
                            color = TVTextPrimary,
                            fontWeight = FontWeight.Bold
                        )
                    }
                    FocusableCloseButton(onClick = onClose)
                }

                // Scrollable content
                Column(
                    modifier = Modifier
                        .weight(1f)
                        .verticalScroll(rememberScrollState()),
                    verticalArrangement = Arrangement.spacedBy(6.dp)
                ) {
                    // Playback speed section
                    SettingsSectionLabel(title = "Playback Speed", icon = Icons.Default.Speed)
                    Row(
                        modifier = Modifier.fillMaxWidth(),
                        horizontalArrangement = Arrangement.spacedBy(6.dp)
                    ) {
                        listOf(0.5f, 0.75f, 1.0f, 1.25f, 1.5f, 2.0f).forEach { speed ->
                            FocusableSpeedOption(
                                label = if (speed == 1.0f) "1x" else "${speed}x",
                                isSelected = playbackSpeed == speed,
                                onClick = { onSpeedChange(speed) },
                                modifier = Modifier.weight(1f),
                                focusRequester = if (speed == 0.5f) firstItemFocusRequester else null
                            )
                        }
                    }
                    Spacer(modifier = Modifier.height(12.dp))

                    // Quality section
                    SettingsSectionLabel(title = "Video Quality", icon = Icons.Default.Hd)
                    Row(
                        modifier = Modifier.fillMaxWidth(),
                        horizontalArrangement = Arrangement.spacedBy(6.dp)
                    ) {
                        val qualities = listOf("auto" to "Auto", "1080p" to "1080p", "720p" to "720p", "480p" to "480p", "360p" to "360p")
                        qualities.forEach { (value, label) ->
                            FocusableSpeedOption(
                                label = label,
                                isSelected = preferredQuality == value,
                                onClick = { onQualityChange(value) },
                                modifier = Modifier.weight(1f)
                            )
                        }
                    }
                    Spacer(modifier = Modifier.height(12.dp))

                    // Resize Mode section
                    SettingsSectionLabel(title = "Resize Mode", icon = Icons.Default.Crop)
                    Row(
                        modifier = Modifier.fillMaxWidth(),
                        horizontalArrangement = Arrangement.spacedBy(6.dp)
                    ) {
                        val resizeModes = listOf(
                            androidx.media3.ui.AspectRatioFrameLayout.RESIZE_MODE_FIT to "Fit",
                            androidx.media3.ui.AspectRatioFrameLayout.RESIZE_MODE_FILL to "Fill",
                            androidx.media3.ui.AspectRatioFrameLayout.RESIZE_MODE_ZOOM to "Zoom"
                        )
                        resizeModes.forEach { (mode, label) ->
                            FocusableSpeedOption(
                                label = label,
                                isSelected = currentResizeMode == mode,
                                onClick = { onResizeModeChange(mode) },
                                modifier = Modifier.weight(1f)
                            )
                        }
                    }
                    Spacer(modifier = Modifier.height(12.dp))

                    // Audio section
                    if (audioTracks.isNotEmpty()) {
                        SettingsSectionLabel(title = "Audio Track", icon = Icons.AutoMirrored.Filled.VolumeUp)
                        audioTracks.forEach { track ->
                            FocusableTrackItem(
                                name = track.name,
                                subtitle = track.language,
                                isSelected = track.isSelected,
                                onClick = { onSelectAudio(track) }
                            )
                        }
                        Spacer(modifier = Modifier.height(12.dp))
                    }

                    // Subtitle section
                    if (subtitleTracks.isNotEmpty()) {
                        SettingsSectionLabel(title = "Subtitles", icon = Icons.Default.Subtitles)
                        FocusableTrackItem(
                            name = "Off",
                            subtitle = "Disable subtitles",
                            isSelected = !subtitlesEnabled,
                            onClick = { onSelectSubtitle(null) }
                        )
                        subtitleTracks.forEach { track ->
                            FocusableTrackItem(
                                name = track.name,
                                subtitle = track.language,
                                isSelected = track.isSelected && subtitlesEnabled,
                                onClick = { onSelectSubtitle(track) }
                            )
                        }
                        Spacer(modifier = Modifier.height(12.dp))

                        // Subtitle size
                        SettingsSectionLabel(title = "Text Size", icon = Icons.Default.FormatSize)
                        Row(
                            modifier = Modifier.fillMaxWidth(),
                            horizontalArrangement = Arrangement.spacedBy(8.dp)
                        ) {
                            SubtitleSize.entries.forEach { size ->
                                FocusableSizeOption(
                                    label = size.displayName,
                                    isSelected = subtitleSize == size,
                                    onClick = { onSubtitleSizeChange(size) },
                                    modifier = Modifier.weight(1f)
                                )
                            }
                        }
                    }
                }

                // External Player button
                Spacer(modifier = Modifier.height(8.dp))
                var extFocus by remember { mutableStateOf(false) }
                Surface(
                    onClick = onOpenExternal,
                    color = if (extFocus) TVPrimary else TVSurfaceVariant,
                    shape = RoundedCornerShape(12.dp),
                    modifier = Modifier
                        .fillMaxWidth()
                        .height(52.dp)
                        .onFocusChanged { extFocus = it.isFocused }
                        .border(
                            width = if (extFocus) 2.dp else 0.dp,
                            color = if (extFocus) Color.White else Color.Transparent,
                            shape = RoundedCornerShape(12.dp)
                        )
                ) {
                    Row(
                        modifier = Modifier.fillMaxSize().padding(horizontal = 20.dp),
                        verticalAlignment = Alignment.CenterVertically,
                        horizontalArrangement = Arrangement.SpaceBetween
                    ) {
                        Row(verticalAlignment = Alignment.CenterVertically) {
                            Icon(
                                imageVector = Icons.AutoMirrored.Filled.OpenInNew,
                                contentDescription = null,
                                tint = if (extFocus) Color.White else TVPrimary,
                                modifier = Modifier.size(22.dp)
                            )
                            Spacer(modifier = Modifier.width(12.dp))
                            Text(
                                text = "Open in External Player",
                                style = MaterialTheme.typography.bodyLarge,
                                color = if (extFocus) Color.White else TVTextPrimary,
                                fontWeight = FontWeight.Medium
                            )
                        }
                        Icon(
                            imageVector = Icons.Default.ChevronRight,
                            contentDescription = null,
                            tint = if (extFocus) Color.White else TVTextSecondary
                        )
                    }
                }

                // Navigation hint
                Box(
                    modifier = Modifier
                        .fillMaxWidth()
                        .padding(top = 16.dp)
                        .background(
                            color = Color.White.copy(alpha = 0.04f),
                            shape = RoundedCornerShape(8.dp)
                        )
                        .padding(12.dp)
                ) {
                    Text(
                        text = "↑↓ Navigate  •  OK Select  •  ← Back",
                        style = MaterialTheme.typography.bodySmall,
                        color = TVTextSecondary.copy(alpha = 0.6f),
                        textAlign = TextAlign.Center,
                        modifier = Modifier.fillMaxWidth()
                    )
                }
            }
        }
    }

    // Focus first item (wait for the 300ms slide-in animation to finish so
    // focus reliably lands on the speed chips instead of racing the layout)
    LaunchedEffect(Unit) {
        kotlinx.coroutines.delay(400)
        try { firstItemFocusRequester.requestFocus() } catch (e: Exception) { }
    }
}

// ─── Settings Helpers ───────────────────────────────────────────────

@Composable
private fun SettingsSectionLabel(title: String, icon: ImageVector) {
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .padding(vertical = 8.dp),
        verticalAlignment = Alignment.CenterVertically
    ) {
        Icon(
            imageVector = icon,
            contentDescription = null,
            tint = TVPrimary,
            modifier = Modifier.size(16.dp)
        )
        Spacer(modifier = Modifier.width(8.dp))
        Text(
            text = title.uppercase(),
            style = MaterialTheme.typography.labelMedium,
            color = TVPrimary,
            fontWeight = FontWeight.Bold,
            letterSpacing = 1.sp
        )
    }
}

@Composable
private fun FocusableCloseButton(onClick: () -> Unit) {
    var isFocused by remember { mutableStateOf(false) }

    Box(
        modifier = Modifier
            .size(40.dp)
            .clip(CircleShape)
            .background(if (isFocused) TVPrimary else Color.White.copy(alpha = 0.08f))
            .border(
                width = if (isFocused) 3.dp else 0.dp,
                color = if (isFocused) Color.White else Color.Transparent,
                shape = CircleShape
            )
            .focusable()
            .onFocusChanged { isFocused = it.isFocused }
            .clickable(onClick = onClick),
        contentAlignment = Alignment.Center
    ) {
        Icon(
            imageVector = Icons.Default.Close,
            contentDescription = "Close",
            tint = if (isFocused) Color.White else TVTextSecondary,
            modifier = Modifier.size(20.dp)
        )
    }
}

@Composable
private fun FocusableTrackItem(
    name: String,
    subtitle: String?,
    isSelected: Boolean,
    onClick: () -> Unit,
    focusRequester: FocusRequester? = null,
    modifier: Modifier = Modifier
) {
    var isFocused by remember { mutableStateOf(false) }

    val animatedBackgroundColor by animateColorAsState(
        targetValue = when {
            isFocused -> TVPrimary
            isSelected -> TVPrimary.copy(alpha = 0.25f)
            else -> Color.White.copy(alpha = 0.05f)
        },
        animationSpec = tween(durationMillis = 150),
        label = "bgColor"
    )

    val animatedBorderColor by animateColorAsState(
        targetValue = when {
            isFocused -> Color.White
            isSelected -> TVPrimary.copy(alpha = 0.6f)
            else -> Color.Transparent
        },
        animationSpec = tween(durationMillis = 150),
        label = "borderColor"
    )

    Surface(
        onClick = onClick,
        color = animatedBackgroundColor,
        shape = RoundedCornerShape(12.dp),
        modifier = modifier
            .fillMaxWidth()
            .then(if (focusRequester != null) Modifier.focusRequester(focusRequester) else Modifier)
            .onFocusChanged { isFocused = it.isFocused }
            .border(
                width = if (isFocused) 3.dp else if (isSelected) 1.dp else 0.dp,
                color = animatedBorderColor,
                shape = RoundedCornerShape(12.dp)
            )
    ) {
        Row(
            modifier = Modifier
                .fillMaxWidth()
                .padding(horizontal = 16.dp, vertical = 14.dp),
            horizontalArrangement = Arrangement.SpaceBetween,
            verticalAlignment = Alignment.CenterVertically
        ) {
            Column(modifier = Modifier.weight(1f)) {
                Text(
                    text = name,
                    style = MaterialTheme.typography.bodyLarge,
                    color = if (isFocused) Color.White else TVTextPrimary,
                    fontWeight = if (isSelected || isFocused) FontWeight.Bold else FontWeight.Normal,
                    maxLines = 2,
                    overflow = TextOverflow.Ellipsis
                )
                if (subtitle != null && subtitle != name) {
                    Text(
                        text = subtitle,
                        style = MaterialTheme.typography.bodySmall,
                        color = if (isFocused) Color.White.copy(alpha = 0.9f) else TVTextSecondary,
                        fontSize = 12.sp
                    )
                }
            }
            if (isSelected) {
                Icon(
                    imageVector = Icons.Default.CheckCircle,
                    contentDescription = "Selected",
                    tint = if (isFocused) Color.White else TVPrimary,
                    modifier = Modifier.size(24.dp)
                )
            }
            if (isFocused && !isSelected) {
                Icon(
                    imageVector = Icons.Default.ChevronRight,
                    contentDescription = null,
                    tint = Color.White,
                    modifier = Modifier.size(24.dp)
                )
            }
        }
    }
}

@Composable
private fun FocusableSizeOption(
    label: String,
    isSelected: Boolean,
    onClick: () -> Unit,
    modifier: Modifier = Modifier
) {
    var isFocused by remember { mutableStateOf(false) }

    val bgColor by animateColorAsState(
        targetValue = when {
            isFocused -> TVPrimary
            isSelected -> TVPrimary.copy(alpha = 0.35f)
            else -> Color.White.copy(alpha = 0.05f)
        },
        animationSpec = tween(150), label = "sizeBg"
    )

    Surface(
        onClick = onClick,
        color = bgColor,
        shape = RoundedCornerShape(10.dp),
        modifier = modifier
            .onFocusChanged { isFocused = it.isFocused }
            .border(
                width = if (isFocused) 3.dp else if (isSelected) 1.dp else 0.dp,
                color = if (isFocused) Color.White else if (isSelected) TVPrimary else Color.Transparent,
                shape = RoundedCornerShape(10.dp)
            )
    ) {
        Box(
            contentAlignment = Alignment.Center,
            modifier = Modifier.padding(vertical = 14.dp, horizontal = 8.dp)
        ) {
            Text(
                text = label.take(1).uppercase(),
                style = MaterialTheme.typography.titleMedium,
                color = if (isFocused || isSelected) Color.White else TVTextSecondary,
                fontWeight = FontWeight.Bold,
                fontSize = 16.sp
            )
        }
    }
}

@Composable
private fun FocusableSpeedOption(
    label: String,
    isSelected: Boolean,
    onClick: () -> Unit,
    modifier: Modifier = Modifier,
    focusRequester: FocusRequester? = null
) {
    var isFocused by remember { mutableStateOf(false) }

    val bgColor by animateColorAsState(
        targetValue = when {
            isFocused -> TVPrimary
            isSelected -> TVPrimary.copy(alpha = 0.35f)
            else -> Color.White.copy(alpha = 0.05f)
        },
        animationSpec = tween(150), label = "speedBg"
    )

    Surface(
        onClick = onClick,
        color = bgColor,
        shape = RoundedCornerShape(10.dp),
        modifier = modifier
            .then(if (focusRequester != null) Modifier.focusRequester(focusRequester) else Modifier)
            .onFocusChanged { isFocused = it.isFocused }
            .border(
                width = if (isFocused) 3.dp else if (isSelected) 1.dp else 0.dp,
                color = if (isFocused) Color.White else if (isSelected) TVPrimary else Color.Transparent,
                shape = RoundedCornerShape(10.dp)
            )
    ) {
        Box(
            contentAlignment = Alignment.Center,
            modifier = Modifier.padding(vertical = 12.dp, horizontal = 4.dp)
        ) {
            Text(
                text = label,
                color = if (isFocused || isSelected) Color.White else TVTextSecondary,
                fontWeight = if (isSelected) FontWeight.Bold else FontWeight.Medium,
                fontSize = 13.sp
            )
        }
    }
}

// ─── Utilities ──────────────────────────────────────────────────────

private fun formatDuration(ms: Long): String {
    if (ms <= 0) return "0:00"
    val totalSeconds = ms / 1000
    val hours = totalSeconds / 3600
    val minutes = (totalSeconds % 3600) / 60
    val seconds = totalSeconds % 60
    return if (hours > 0) {
        String.format("%d:%02d:%02d", hours, minutes, seconds)
    } else {
        String.format("%d:%02d", minutes, seconds)
    }
}
