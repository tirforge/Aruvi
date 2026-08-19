package com.aruvi.tir.ui.mobile.player

import android.app.Activity
import android.content.Context
import android.content.pm.ActivityInfo
import android.media.AudioManager
import android.view.View
import android.view.ViewGroup
import android.view.WindowManager
import androidx.mediarouter.app.MediaRouteButton
import androidx.activity.compose.BackHandler
import androidx.annotation.OptIn
import androidx.compose.animation.AnimatedVisibility
import androidx.compose.animation.fadeIn
import androidx.compose.animation.fadeOut
import androidx.compose.ui.zIndex
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.gestures.detectDragGestures
import androidx.compose.foundation.gestures.detectTapGestures
import androidx.compose.foundation.gestures.detectTransformGestures
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.*
import androidx.compose.material.icons.filled.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.graphicsLayer
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.viewinterop.AndroidView
import androidx.core.view.WindowCompat
import androidx.core.view.WindowInsetsCompat
import androidx.core.view.WindowInsetsControllerCompat
import androidx.hilt.navigation.compose.hiltViewModel
import androidx.media3.common.util.UnstableApi
import androidx.media3.ui.PlayerView
import com.aruvi.tir.ui.player.PlayerViewModel
import com.aruvi.tir.ui.player.TrackInfo
import com.aruvi.tir.ui.player.SubtitleSize
import com.aruvi.tir.ui.mobile.findActivity
import com.aruvi.tir.ui.mobile.findFragmentActivity
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import kotlin.math.max
import kotlin.math.min

@OptIn(androidx.media3.common.util.UnstableApi::class)
@ExperimentalMaterial3Api
@Composable
fun MobilePlayerScreen(
    startPosition: Long = 0L,
    viewModel: PlayerViewModel = hiltViewModel(),
    onBack: () -> Unit
) {
    val context = LocalContext.current
    val activity = context.findActivity()
    val uiState by viewModel.uiState.collectAsState()
    val scope = rememberCoroutineScope()

    // Message for gesture feedback (Volume/Brightness)
    var gestureMessage by remember { mutableStateOf<String?>(null) }
    var gestureIcon by remember { mutableStateOf<androidx.compose.ui.graphics.vector.ImageVector?>(null) }
    var gestureJob by remember { mutableStateOf<kotlinx.coroutines.Job?>(null) }

    // Helper to show gesture feedback
    fun showGestureFeedback(text: String, icon: androidx.compose.ui.graphics.vector.ImageVector) {
        gestureMessage = text
        gestureIcon = icon
        gestureJob?.cancel()
        gestureJob = scope.launch { 
            delay(1500)
            gestureMessage = null
            gestureIcon = null
        }
    }

    // Reactive Orientation Management
    LaunchedEffect(uiState.orientationLock) {
        val requested = when (uiState.orientationLock) {
            1 -> ActivityInfo.SCREEN_ORIENTATION_LANDSCAPE
            2 -> ActivityInfo.SCREEN_ORIENTATION_PORTRAIT
            else -> ActivityInfo.SCREEN_ORIENTATION_SENSOR
        }
        activity?.requestedOrientation = requested
    }

    // Full Screen & Persistence (Immersive Sticky)
    DisposableEffect(Unit) {
        val originalOrientation = activity?.requestedOrientation
        val window = activity?.window
        
        if (activity != null && window != null) {
            WindowCompat.setDecorFitsSystemWindows(window, false)
            window.addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)

            val insetsController = WindowCompat.getInsetsController(window, window.decorView)
            insetsController.systemBarsBehavior = WindowInsetsControllerCompat.BEHAVIOR_SHOW_TRANSIENT_BARS_BY_SWIPE
            insetsController.hide(WindowInsetsCompat.Type.systemBars())

            if (android.os.Build.VERSION.SDK_INT >= android.os.Build.VERSION_CODES.P) {
                val params = window.attributes
                params.layoutInDisplayCutoutMode = WindowManager.LayoutParams.LAYOUT_IN_DISPLAY_CUTOUT_MODE_SHORT_EDGES
                window.attributes = params
            }
        }

        if (startPosition > 0) {
             viewModel.setResumePosition(startPosition)
        }
        
        onDispose {
            activity?.requestedOrientation = originalOrientation ?: ActivityInfo.SCREEN_ORIENTATION_UNSPECIFIED
            if (window != null) {
                WindowCompat.setDecorFitsSystemWindows(window, false)
                window.clearFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
                val insetsController = WindowCompat.getInsetsController(window, window.decorView)
                insetsController.show(WindowInsetsCompat.Type.systemBars())
            }
            viewModel.onLeavePlayer()
        }
    }

    // Stop background audio when returning to the player screen
    LaunchedEffect(Unit) {
        viewModel.stopBackgroundAudio()
    }

    BackHandler {
        onBack()
    }

    // Settings Bottom Sheet
    if (uiState.showSettings) {
        ModalBottomSheet(
            onDismissRequest = { viewModel.hideSettings() },
            containerColor = MaterialTheme.colorScheme.surface,
            contentColor = MaterialTheme.colorScheme.onSurface
        ) {
            PlayerSettingsSheet(
                uiState = uiState,
                onSpeedChange = viewModel::setPlaybackSpeed,
                onAudioTrackSelect = viewModel::selectAudioTrack,
                onSubtitleTrackSelect = viewModel::selectSubtitleTrack,
                onSubtitleSizeChange = viewModel::setSubtitleSize,
                onResizeModeChange = viewModel::setResizeMode,
                onVideoScaleChange = viewModel::setVideoScale,
                onOrientationChange = viewModel::setOrientationLock,
                onQualityChange = viewModel::setPreferredQuality
            )
        }
    }

    Box(
        modifier = Modifier
            .fillMaxSize()
            .background(Color.Black)
    ) {
        // 1. Player View (Bottom Layer)
        AndroidView(
            factory = { ctx ->
                PlayerView(ctx).apply {
                    useController = false
                    layoutParams = ViewGroup.LayoutParams(
                        ViewGroup.LayoutParams.MATCH_PARENT,
                        ViewGroup.LayoutParams.MATCH_PARENT
                    )
                    player = viewModel.exoPlayer
                    keepScreenOn = true
                    isClickable = false
                    isFocusable = false
                }
            },
            update = { playerView ->
                playerView.player = viewModel.exoPlayer
                playerView.resizeMode = uiState.toggleResizeMode
            },
            modifier = Modifier
                .fillMaxSize()
                .graphicsLayer(
                    scaleX = uiState.videoScale,
                    scaleY = uiState.videoScale,
                    translationX = uiState.videoOffsetX,
                    translationY = uiState.videoOffsetY
                )
        )

        // 2. Gesture & Touch Overlay (Middle Layer)
        Box(
            modifier = Modifier
                .fillMaxSize()
                .zIndex(1f)
                .pointerInput(Unit) {
                    detectTransformGestures { _, pan, zoom, _ ->
                        if (zoom != 1f || pan != androidx.compose.ui.geometry.Offset.Zero) {
                            viewModel.setVideoScale(viewModel.uiState.value.videoScale * zoom)
                            // Apply pan only if zoomed or zooming
                            if (viewModel.uiState.value.videoScale > 1.0f || zoom != 1.0f) {
                                viewModel.updatePan(pan.x, pan.y)
                            }
                        }
                    }
                }
                .pointerInput(Unit) {
                    val containerSize = size
                    var accumulatedDragX = 0f
                    var accumulatedDragY = 0f
                    var touchMode = 0 // 0=NONE, 1=SEEK, 2=VOLUME, 3=BRIGHTNESS
                    val touchSlop = 50f // Threshold to lock gesture
                    
                    var dragStartPosition = 0L
                    var startVolume = 0
                    var startBrightness = 0.5f
                    var startX = 0f

                    detectDragGestures(
                        onDragStart = { offset ->
                            accumulatedDragX = 0f
                            accumulatedDragY = 0f
                            touchMode = 0
                            startX = offset.x
                        },
                        onDragEnd = { 
                             if (touchMode == 1) { // SEEK
                                 viewModel.onSeekEnd()
                             }
                             touchMode = 0
                        },
                        onDragCancel = { 
                            if (touchMode == 1) {
                                viewModel.onSeekEnd()
                            }
                             touchMode = 0
                        }
                    ) { _, dragAmount ->
                        val width = containerSize.width.toFloat()
                        val height = containerSize.height.toFloat()
                        
                        accumulatedDragX += dragAmount.x
                        accumulatedDragY += dragAmount.y
                        
                        if (touchMode == 0) {
                            // Detect Lock
                            if (kotlin.math.abs(accumulatedDragX) > touchSlop) {
                                // Lock to SEEK
                                touchMode = 1
                                dragStartPosition = viewModel.uiState.value.currentPosition
                            } else if (kotlin.math.abs(accumulatedDragY) > touchSlop) {
                                // Lock to Vertical
                                if (startX < width * 0.5f) {
                                    touchMode = 3 // BRIGHTNESS
                                    val lp = activity?.window?.attributes
                                    startBrightness = lp?.screenBrightness?.takeIf { it >= 0 } ?: 0.5f
                                } else {
                                    touchMode = 2 // VOLUME
                                    val audioManager = context.getSystemService(Context.AUDIO_SERVICE) as AudioManager
                                    startVolume = audioManager.getStreamVolume(AudioManager.STREAM_MUSIC)
                                }
                            }
                        }
                        
                        // Execute based on locked mode
                        when (touchMode) {
                            1 -> { // SEEK
                                 // Sensitivity: 1px = 100ms
                                 val seekDelta = (accumulatedDragX * 200).toLong() 
                                 val duration = viewModel.uiState.value.duration
                                 // Use startPosition + delta to avoid drift/stutter
                                 val newPos = (dragStartPosition + seekDelta).coerceIn(0, duration)
                                 viewModel.updateCurrentPosition(newPos)
                                 
                                 val direction = if (seekDelta > 0) "+" else "-"
                                 val seconds = kotlin.math.abs(seekDelta / 1000)
                                 val icon = if (seekDelta > 0) Icons.Filled.Forward10 else Icons.Filled.Replay10
                                 showGestureFeedback("${direction}${seconds}s (${formatTime(newPos)})", icon)
                            }
                            2 -> { // VOLUME
                                 val verticalDelta = -accumulatedDragY
                                 val audioManager = context.getSystemService(Context.AUDIO_SERVICE) as AudioManager
                                 val maxVolume = audioManager.getStreamMaxVolume(AudioManager.STREAM_MUSIC)
                                 
                                 // Full height = max volume change
                                 val changePercent = verticalDelta / height
                                 val changeVol = (changePercent * maxVolume).toInt()
                                 val newVolume = (startVolume + changeVol).coerceIn(0, maxVolume)
                                 audioManager.setStreamVolume(AudioManager.STREAM_MUSIC, newVolume, 0)
                                 
                                 val percent = (newVolume.toFloat() / maxVolume * 100).toInt()
                                 showGestureFeedback("Volume: $percent%", Icons.AutoMirrored.Filled.VolumeUp)
                            }
                            3 -> { // BRIGHTNESS
                                 val verticalDelta = -accumulatedDragY
                                 // Full height = 1.0 change
                                 val changePercent = verticalDelta / height
                                 val newBrightness = (startBrightness + changePercent).coerceIn(0f, 1f)
                                 
                                 activity?.window?.attributes?.let { attributes ->
                                     attributes.screenBrightness = newBrightness
                                     activity.window.attributes = attributes
                                 }
                                 showGestureFeedback("Brightness: ${(newBrightness * 100).toInt()}%", Icons.Filled.Settings)
                            }
                        }
                    }
                }
                .pointerInput(Unit) {
                    detectTapGestures(
                        onDoubleTap = { offset ->
                            val width = size.width.toFloat()
                            if (offset.x < width / 2) {
                                viewModel.seekBackward()
                            } else {
                                viewModel.seekForward()
                            }
                        },
                        onTap = {
                            if (uiState.showControls) viewModel.hideControls() else viewModel.showControls()
                        }
                    )
                }
        )

    

    // 3. Overlay Controls (Top Layer)
        Box(modifier = Modifier.fillMaxSize().zIndex(2f)) {
            MobilePlayerControls(
                isVisible = uiState.showControls,
                isPlaying = uiState.isPlaying,
                currentPosition = uiState.currentPosition,
                duration = uiState.duration,
                title = uiState.file?.fileName ?: "Playing...",
                onPlayPause = { viewModel.togglePlayback() },
                onSeek = { pos -> viewModel.seekTo(pos) },
                onForward = { viewModel.seekForward() },
                onRewind = { viewModel.seekBackward() },
                onBack = onBack,
                onResize = { viewModel.cycleResizeMode() },
                onOrientation = { viewModel.cycleOrientation() },
                onSettings = { viewModel.toggleSettings() },
                onBackgroundAudio = {
                    viewModel.startBackgroundAudio()
                    onBack()
                },
                onOpenExternal = { viewModel.openInExternalPlayer(context) },
                orientationMode = uiState.orientationLock,
                isAudioFile = uiState.isAudioFile
            )
        }
        
        // 4. Gesture Feedback Overlay
        if (gestureMessage != null && gestureIcon != null) {
            Box(
                modifier = Modifier.fillMaxSize(),
                contentAlignment = Alignment.Center
            ) {
                Surface(
                    color = Color.Black.copy(alpha = 0.7f),
                    shape = RoundedCornerShape(16.dp)
                ) {
                    Column(
                        modifier = Modifier.padding(24.dp),
                        horizontalAlignment = Alignment.CenterHorizontally
                    ) {
                        Icon(gestureIcon!!, contentDescription = null, tint = Color.White, modifier = Modifier.size(48.dp))
                        Spacer(modifier = Modifier.height(8.dp))
                        Text(
                            text = gestureMessage!!,
                            style = MaterialTheme.typography.titleMedium,
                            color = Color.White
                        )
                    }
                }
            }
        }
        
        // 5. Seek Indicator (Existing)
        if (uiState.showSeekIndicator) {
            Box(
                modifier = Modifier.fillMaxSize(),
                contentAlignment = Alignment.Center
            ) {
                Surface(
                    color = Color.Black.copy(alpha = 0.7f),
                    shape = RoundedCornerShape(16.dp)
                ) {
                    Text(
                        text = uiState.seekIndicatorText,
                        style = MaterialTheme.typography.displayMedium,
                        color = Color.White,
                        modifier = Modifier.padding(24.dp)
                    )
                }
            }
        }
        
        // Loading
         if (uiState.isLoading || uiState.isBuffering) {
             Box(modifier = Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
                 CircularProgressIndicator(color = MaterialTheme.colorScheme.primary)
             }
         }

         // Error Overlay
         if (uiState.error != null) {
             PlayerErrorScreen(
                 error = uiState.error!!,
                 onRetry = { viewModel.retry() },
                 onOpenExternal = { viewModel.openInExternalPlayer(context) },
                 onBack = onBack
             )
         }
    }
}

@Composable
fun MobilePlayerControls(
    isVisible: Boolean,
    isPlaying: Boolean,
    currentPosition: Long,
    duration: Long,
    title: String,
    onPlayPause: () -> Unit,
    onSeek: (Long) -> Unit,
    onForward: () -> Unit,
    onRewind: () -> Unit,
    onBack: () -> Unit,
    onResize: () -> Unit,
    onOrientation: () -> Unit,
    onSettings: () -> Unit,
    onBackgroundAudio: () -> Unit,
    onOpenExternal: () -> Unit,
    orientationMode: Int,
    isAudioFile: Boolean = false
) {
    AnimatedVisibility(
        visible = isVisible,
        enter = fadeIn(),
        exit = fadeOut(),
        modifier = Modifier.fillMaxSize()
    ) {
        Box(
            modifier = Modifier
                .fillMaxSize()
                .background(Color.Black.copy(alpha = 0.3f)) // Lighter scrim
        ) {
            // Top Gradient & Bar
            Box(
                modifier = Modifier
                    .fillMaxWidth()
                    .align(Alignment.TopCenter)
                    .background(
                        Brush.verticalGradient(
                            colors = listOf(Color.Black.copy(alpha = 0.8f), Color.Transparent)
                        )
                    )
                    .padding(16.dp)
            ) {
                Row(
                    modifier = Modifier.fillMaxWidth(),
                    verticalAlignment = Alignment.CenterVertically
                ) {
                    IconButton(onClick = onBack) {
                        Icon(Icons.AutoMirrored.Filled.ArrowBack, "Back", tint = Color.White)
                    }
                    Text(
                        text = title,
                        style = MaterialTheme.typography.titleMedium,
                        color = Color.White,
                        fontWeight = FontWeight.SemiBold,
                        modifier = Modifier.padding(start = 8.dp).weight(1f),
                        maxLines = 1
                    )
                    IconButton(onClick = onResize) {
                        Icon(Icons.Filled.Fullscreen, "Resize", tint = Color.White)
                    }
                    val density = LocalDensity.current
                    val buttonSizePx = with(density) { 48.dp.toPx().toInt() }
                    Box(
                        modifier = Modifier.size(48.dp),
                        contentAlignment = Alignment.Center
                    ) {
                        AndroidView(
                            factory = { ctx ->
                                val activity = ctx.findFragmentActivity()
                                val btn = MediaRouteButton(activity ?: ctx)
                                btn.layoutParams = ViewGroup.LayoutParams(buttonSizePx, buttonSizePx)
                                btn.setBackgroundColor(android.graphics.Color.BLACK)
                                btn
                            },
                            modifier = Modifier.size(48.dp)
                        )
                    }
                    IconButton(onClick = onOrientation) {
                        val icon = when (orientationMode) {
                            1 -> Icons.Filled.ScreenLockLandscape
                            2 -> Icons.Filled.ScreenLockPortrait
                            else -> Icons.Filled.ScreenRotation
                        }
                        Icon(icon, "Orientation", tint = Color.White)
                    }
                    if (isAudioFile) {
                        IconButton(onClick = onBackgroundAudio) {
                            Icon(Icons.Filled.Headphones, "Background Play", tint = Color.White)
                        }
                    }
                    IconButton(onClick = onOpenExternal) {
                        Icon(Icons.AutoMirrored.Filled.OpenInNew, "External Player", tint = Color.White)
                    }
                    IconButton(onClick = onSettings) {
                        Icon(Icons.Filled.Settings, "Settings", tint = Color.White)
                    }
                }
            }

            // Center Controls
            Row(
                modifier = Modifier.align(Alignment.Center),
                horizontalArrangement = Arrangement.spacedBy(64.dp), // More spaced
                verticalAlignment = Alignment.CenterVertically
            ) {
                IconButton(onClick = onRewind, modifier = Modifier.size(56.dp)) {
                    Icon(Icons.Filled.Replay10, "Rewind", tint = Color.White, modifier = Modifier.size(40.dp))
                }

                IconButton(
                    onClick = onPlayPause,
                    modifier = Modifier
                        .size(80.dp)
                        .background(Color.Black.copy(alpha = 0.5f), CircleShape)
                        .padding(4.dp)
                ) {
                    Icon(
                        if (isPlaying) Icons.Filled.Pause else Icons.Filled.PlayArrow,
                        "Play/Pause",
                        tint = Color.White,
                        modifier = Modifier.size(48.dp)
                    )
                }

                IconButton(onClick = onForward, modifier = Modifier.size(56.dp)) {
                    Icon(Icons.Filled.Forward10, "Forward", tint = Color.White, modifier = Modifier.size(40.dp))
                }
            }

            // Bottom Gradient & Bar
            Box(
                 modifier = Modifier
                    .fillMaxWidth()
                    .align(Alignment.BottomCenter)
                    .background(
                        Brush.verticalGradient(
                            colors = listOf(Color.Transparent, Color.Black.copy(alpha = 0.9f))
                        )
                    )
                    .padding(horizontal = 24.dp, vertical = 20.dp)
            ) {
                Column {
                    // Time and Duration
                    Row(
                        modifier = Modifier.fillMaxWidth(),
                        horizontalArrangement = Arrangement.SpaceBetween
                    ) {
                        Text(
                            formatTime(currentPosition), 
                            color = Color.White.copy(alpha = 0.9f), 
                            style = MaterialTheme.typography.labelMedium,
                            fontWeight = FontWeight.Medium
                        )
                        Text(
                            formatTime(duration), 
                            color = Color.White.copy(alpha = 0.9f), 
                            style = MaterialTheme.typography.labelMedium,
                            fontWeight = FontWeight.Medium
                        )
                    }
                    
                    Spacer(modifier = Modifier.height(8.dp))

                    Slider(
                        value = currentPosition.toFloat(),
                        onValueChange = { onSeek(it.toLong()) },
                        valueRange = 0f..duration.toFloat().coerceAtLeast(1f),
                        colors = SliderDefaults.colors(
                            thumbColor = MaterialTheme.colorScheme.primary,
                            activeTrackColor = MaterialTheme.colorScheme.primary,
                            inactiveTrackColor = Color.White.copy(alpha = 0.3f)
                        ),
                        modifier = Modifier.height(20.dp)
                    )
                }
            }
        }
    }
}

@Composable
fun PlayerSettingsSheet(
    uiState: com.aruvi.tir.ui.player.PlayerUiState,
    onSpeedChange: (Float) -> Unit,
    onAudioTrackSelect: (TrackInfo) -> Unit,
    onSubtitleTrackSelect: (TrackInfo?) -> Unit,
    onSubtitleSizeChange: (SubtitleSize) -> Unit,
    onResizeModeChange: (Int) -> Unit,
    onVideoScaleChange: (Float) -> Unit,
    onOrientationChange: (Int) -> Unit,
    onQualityChange: (String) -> Unit
) {
    var selectedTab by remember { mutableStateOf(0) }
    val tabs = listOf("Speed", "Audio", "Subtitles", "Display", "Quality")

    Column(
        modifier = Modifier
            .fillMaxWidth()
            .padding(bottom = 32.dp)
            .background(MaterialTheme.colorScheme.surface)
    ) {
        // Handle
        Box(
            modifier = Modifier
                .padding(vertical = 12.dp)
                .width(40.dp)
                .height(4.dp)
                .background(MaterialTheme.colorScheme.onSurfaceVariant.copy(alpha = 0.4f), CircleShape)
                .align(Alignment.CenterHorizontally)
        )

        ScrollableTabRow(
            selectedTabIndex = selectedTab,
            containerColor = Color.Transparent,
            contentColor = MaterialTheme.colorScheme.primary,
            edgePadding = 0.dp
        ) {
            tabs.forEachIndexed { index, title ->
                Tab(
                    selected = selectedTab == index,
                    onClick = { selectedTab = index },
                    text = { Text(title, style = MaterialTheme.typography.titleSmall) },
                    selectedContentColor = MaterialTheme.colorScheme.primary,
                    unselectedContentColor = MaterialTheme.colorScheme.onSurfaceVariant
                )
            }
        }

        Spacer(modifier = Modifier.height(16.dp))

        when (selectedTab) {
            0 -> { // Speed
                val speeds = listOf(0.5f, 0.75f, 1.0f, 1.25f, 1.5f, 2.0f)
                LazyColumn(modifier = Modifier.height(250.dp)) {
                    items(speeds) { speed ->
                        SettingsItem(
                            text = "${speed}x",
                            subText = if (speed == 1.0f) "Normal" else null,
                            isSelected = uiState.playbackSpeed == speed,
                            onClick = { onSpeedChange(speed) }
                        )
                    }
                }
            }
            1 -> { // Audio
                if (uiState.audioTracks.isEmpty()) {
                    Box(modifier = Modifier.fillMaxWidth().height(200.dp), contentAlignment = Alignment.Center) {
                        Text("No audio tracks available", color = MaterialTheme.colorScheme.onSurfaceVariant)
                    }
                } else {
                     LazyColumn(modifier = Modifier.height(250.dp)) {
                        items(uiState.audioTracks) { track ->
                            SettingsItem(
                                text = track.name,
                                isSelected = track.isSelected,
                                onClick = { onAudioTrackSelect(track) },
                                icon = Icons.Filled.PlayArrow
                            )
                        }
                    }
                }
            }
            2 -> { // Subtitles
                LazyColumn(modifier = Modifier.height(250.dp)) {
                    item {
                        SettingsItem(
                            text = "Off",
                            isSelected = !uiState.subtitlesEnabled,
                            onClick = { onSubtitleTrackSelect(null) },
                            icon = Icons.Filled.Close
                        )
                    }
                    items(uiState.subtitleTracks) { track ->
                        SettingsItem(
                            text = track.name,
                            isSelected = track.isSelected && uiState.subtitlesEnabled,
                            onClick = { onSubtitleTrackSelect(track) },
                             icon = Icons.Filled.Info
                        )
                    }
                    
                    item {
                        HorizontalDivider(
                            modifier = Modifier.padding(vertical = 12.dp),
                            color = MaterialTheme.colorScheme.outlineVariant
                        )
                        Text(
                            "Subtitle Size", 
                            style = MaterialTheme.typography.labelLarge, 
                            color = MaterialTheme.colorScheme.primary,
                            modifier = Modifier.padding(horizontal = 24.dp, vertical = 8.dp)
                        )
                    }
                    
                    items(SubtitleSize.values()) { size ->
                        SettingsItem(
                            text = size.displayName,
                            isSelected = uiState.subtitleSize == size,
                            onClick = { onSubtitleSizeChange(size) }
                        )
                    }
                }
            }
            4 -> { // Quality
                val qualities = listOf("auto", "1080p", "720p", "480p", "360p")
                val qualityLabels = mapOf(
                    "auto" to "Auto",
                    "1080p" to "1080p",
                    "720p" to "720p",
                    "480p" to "480p",
                    "360p" to "360p"
                )
                LazyColumn(modifier = Modifier.height(250.dp)) {
                    items(qualities) { quality ->
                        SettingsItem(
                            text = qualityLabels[quality] ?: quality,
                            subText = if (quality == "auto") "Let player decide" else null,
                            isSelected = uiState.preferredQuality == quality,
                            onClick = { onQualityChange(quality) }
                        )
                    }
                }
            }
            3 -> { // Display
                Column(modifier = Modifier.padding(horizontal = 24.dp)) {
                    Text(
                        "Resize Mode",
                        style = MaterialTheme.typography.labelLarge,
                        color = MaterialTheme.colorScheme.primary,
                        modifier = Modifier.padding(bottom = 12.dp)
                    )
                    
                    val modes = listOf(
                         "Fit" to androidx.media3.ui.AspectRatioFrameLayout.RESIZE_MODE_FIT,
                         "Fill" to androidx.media3.ui.AspectRatioFrameLayout.RESIZE_MODE_FILL,
                         "Zoom" to androidx.media3.ui.AspectRatioFrameLayout.RESIZE_MODE_ZOOM
                    )
                    
                    Row(
                        horizontalArrangement = Arrangement.spacedBy(8.dp),
                        modifier = Modifier.fillMaxWidth()
                    ) {
                        modes.forEach { (name, mode) ->
                            FilterChip(
                                selected = uiState.toggleResizeMode == mode,
                                onClick = { onResizeModeChange(mode) },
                                label = { Text(name) },
                                leadingIcon = if (uiState.toggleResizeMode == mode) {
                                    { Icon(Icons.Filled.Check, null) }
                                } else null
                            )
                        }
                    }
                    
                    Spacer(modifier = Modifier.height(24.dp))
                    
                    Text(
                        "Custom Zoom: ${(uiState.videoScale * 100).toInt()}%",
                        style = MaterialTheme.typography.labelLarge,
                        color = MaterialTheme.colorScheme.primary
                    )
                    
                    Slider(
                        value = uiState.videoScale,
                        onValueChange = { onVideoScaleChange(it) },
                        valueRange = 0.5f..3.0f,
                        steps = 0,
                        modifier = Modifier.padding(top = 8.dp)
                    )
                    
                    if (uiState.videoScale != 1.0f) {
                        TextButton(
                            onClick = { onVideoScaleChange(1.0f) },
                            modifier = Modifier.align(Alignment.End)
                        ) {
                            Text("Reset Zoom")
                        }
                    }

                    Spacer(modifier = Modifier.height(24.dp))
                    
                    Text(
                        "Orientation",
                        style = MaterialTheme.typography.labelLarge,
                        color = MaterialTheme.colorScheme.primary,
                        modifier = Modifier.padding(bottom = 12.dp)
                    )
                    
                    val orientationModes = listOf(
                        "Auto" to 0,
                        "Landscape" to 1,
                        "Portrait" to 2
                    )
                    
                    Row(
                        horizontalArrangement = Arrangement.spacedBy(8.dp),
                        modifier = Modifier.fillMaxWidth()
                    ) {
                        orientationModes.forEach { (name, mode) ->
                            FilterChip(
                                selected = uiState.orientationLock == mode,
                                onClick = { onOrientationChange(mode) },
                                label = { Text(name) },
                                leadingIcon = if (uiState.orientationLock == mode) {
                                    { Icon(Icons.Filled.Check, null) }
                                } else null
                            )
                        }
                    }
                }
            }
        }
    }
}

@Composable
fun SettingsItem(
    text: String,
    subText: String? = null,
    isSelected: Boolean,
    onClick: () -> Unit,
    icon: androidx.compose.ui.graphics.vector.ImageVector? = null
) {
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .clickable(onClick = onClick)
            .padding(horizontal = 24.dp, vertical = 16.dp),
        horizontalArrangement = Arrangement.spacedBy(16.dp),
        verticalAlignment = Alignment.CenterVertically
    ) {
        if (icon != null) {
            Icon(
                icon, 
                contentDescription = null, 
                tint = if (isSelected) MaterialTheme.colorScheme.primary else MaterialTheme.colorScheme.onSurfaceVariant
            )
        }
        
        Column(modifier = Modifier.weight(1f)) {
            Text(
                text = text,
                style = MaterialTheme.typography.bodyLarge,
                color = if (isSelected) MaterialTheme.colorScheme.primary else MaterialTheme.colorScheme.onSurface,
                fontWeight = if (isSelected) FontWeight.Bold else FontWeight.Normal
            )
            if (subText != null) {
                Text(
                    text = subText,
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant
                )
            }
        }
        
        if (isSelected) {
            Icon(Icons.Filled.Check, "Selected", tint = MaterialTheme.colorScheme.primary)
        }
    }
}

fun formatTime(ms: Long): String {
    val seconds = (ms / 1000) % 60
    val minutes = (ms / (1000 * 60)) % 60
    val hours = (ms / (1000 * 60 * 60))
    return if (hours > 0) String.format("%d:%02d:%02d", hours, minutes, seconds)
    else String.format("%d:%02d", minutes, seconds)
}



@Composable
fun PlayerErrorScreen(
    error: com.aruvi.tir.ui.player.PlaybackError,
    onRetry: () -> Unit,
    onOpenExternal: () -> Unit,
    onBack: () -> Unit
) {
    Box(
        modifier = Modifier
            .fillMaxSize()
            .background(Color.Black.copy(alpha = 0.9f))
            .zIndex(10f), // Ensure it covers everything
        contentAlignment = Alignment.Center
    ) {
        Column(
            horizontalAlignment = Alignment.CenterHorizontally,
            verticalArrangement = Arrangement.Center,
            modifier = Modifier.padding(32.dp)
        ) {
            Icon(
                imageVector = Icons.Filled.Warning,
                contentDescription = null,
                tint = MaterialTheme.colorScheme.error,
                modifier = Modifier.size(64.dp)
            )
            Spacer(modifier = Modifier.height(16.dp))
            Text(
                text = error.title,
                style = MaterialTheme.typography.titleLarge,
                color = Color.White,
                fontWeight = FontWeight.Bold
            )
            Spacer(modifier = Modifier.height(8.dp))
            Text(
                text = error.description,
                style = MaterialTheme.typography.bodyMedium,
                color = Color.White.copy(alpha = 0.8f),
                fontWeight = FontWeight.Normal,
                textAlign = androidx.compose.ui.text.style.TextAlign.Center,
                modifier = Modifier.padding(horizontal = 16.dp)
            )
            
            if (error.technicalDetails != null) {
                Spacer(modifier = Modifier.height(8.dp))
                Text(
                    text = error.technicalDetails.take(200), // Limit length
                    style = MaterialTheme.typography.labelSmall,
                    color = Color.White.copy(alpha = 0.5f),
                    modifier = Modifier.padding(horizontal = 16.dp),
                    maxLines = 3
                )
            }

            Spacer(modifier = Modifier.height(32.dp))
            
            Row(horizontalArrangement = Arrangement.spacedBy(16.dp)) {
                OutlinedButton(
                    onClick = onBack,
                    colors = ButtonDefaults.outlinedButtonColors(contentColor = Color.White)
                ) {
                    Text("Go Back")
                }
                
                if (error.canRetry) {
                    Button(onClick = onRetry) {
                        Text("Retry")
                    }
                }
                
                Button(
                    onClick = onOpenExternal,
                    colors = ButtonDefaults.buttonColors(containerColor = MaterialTheme.colorScheme.secondary)
                ) {
                    Text("External Player")
                }
            }
        }
    }
}
