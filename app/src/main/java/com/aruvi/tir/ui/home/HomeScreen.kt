package com.aruvi.tir.ui.home

import androidx.compose.animation.core.*
import androidx.compose.foundation.Image
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.basicMarquee
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.*
import androidx.compose.material.icons.outlined.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.focus.FocusRequester
import androidx.compose.ui.focus.focusRequester
import androidx.compose.ui.focus.onFocusChanged
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.toArgb
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.res.painterResource
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.hilt.navigation.compose.hiltViewModel
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.LifecycleEventObserver
import androidx.compose.ui.platform.LocalLifecycleOwner
import coil.compose.AsyncImage
import com.aruvi.tir.ui.components.*
import com.aruvi.tir.ui.theme.*
import dev.holtchas.focustrail.compose.FocusTrailBox
import dev.holtchas.focustrail.compose.FocusTrailDefaults
import dev.holtchas.focustrail.compose.FocusTrailShape

/**
 * Modern home screen with enhanced aesthetics for TV.
 */
@Composable
fun HomeScreen(
onFileClick: (Int) -> Unit,
onFolderClick: (Int) -> Unit,
onSearchClick: () -> Unit,
onGrabClick: () -> Unit,
onSettingsClick: () -> Unit,
viewModel: HomeViewModel = hiltViewModel()
) {
    val uiState by viewModel.uiState.collectAsState()
    val focusRequester = remember { FocusRequester() }

    val lifecycleOwner = LocalLifecycleOwner.current
    DisposableEffect(lifecycleOwner, viewModel) {
        val observer = LifecycleEventObserver { _, event ->
            when (event) {
                Lifecycle.Event.ON_RESUME -> viewModel.startAutoRefresh()
                Lifecycle.Event.ON_PAUSE -> viewModel.stopAutoRefresh()
                else -> {}
            }
        }
        lifecycleOwner.lifecycle.addObserver(observer)
        onDispose {
            lifecycleOwner.lifecycle.removeObserver(observer)
        }
    }

    Box(modifier = Modifier.fillMaxSize()) {
        TvAnimatedBackground(modifier = Modifier.fillMaxSize())
        when {
            uiState.isLoading -> {
                ModernLoadingState()
            }

            uiState.error != null -> {
                ModernErrorState(
                    message = uiState.error!!,
                    onRetry = { viewModel.refresh() },
                    onSettings = onSettingsClick
                )
            }

            else -> {
                Column(modifier = Modifier.fillMaxSize()) {
                    // Modern top bar
    ModernTopBar(
        onSearchClick = onSearchClick,
        onGrabClick = onGrabClick,
        onSettingsClick = onSettingsClick
    )

                    // Content rows
                    LazyColumn(
                        state = rememberLazyListState(),
                        modifier = Modifier
                            .fillMaxSize()
                            .focusRequester(focusRequester),
                        contentPadding = PaddingValues(bottom = 48.dp),
                        verticalArrangement = Arrangement.spacedBy(8.dp)
                    ) {
                        // Hero banner (featured content)
                        val featured = uiState.continueWatching.firstOrNull()
                            ?: uiState.recentFiles.firstOrNull()
                        if (featured != null && uiState.serverUrl.isNotEmpty()) {
                            item {
                                HeroBanner(
                                    file = featured,
                                    thumbnailUrl = "${uiState.serverUrl}/api/stream/${featured.id}/thumbnail",
                                    onPlay = { onFileClick(featured.id) }
                                )
                            }
                        }

                        // Continue Watching section
                        if (uiState.continueWatching.isNotEmpty()) {
                            item {
                                ContentSection(
                                    title = "Continue Watching",
                                    subtitle = "${uiState.continueWatching.size} in progress",
                                    icon = Icons.Default.PlayCircle
                                ) {
                                    ContentRow(
                                        title = "",
                                        files = uiState.continueWatching,
                                        serverUrl = uiState.serverUrl,
                                        onFileClick = onFileClick,
                                        useLargeCards = true
                                    )
                                }
                            }
                        }

                        // Recently Added section
                        if (uiState.recentFiles.isNotEmpty()) {
                            item {
                                ContentSection(
                                    title = "Recently Added",
                                    subtitle = "Latest uploads",
                                    icon = Icons.Default.Schedule
                                ) {
                                    ContentRow(
                                        title = "",
                                        files = uiState.recentFiles,
                                        serverUrl = uiState.serverUrl,
                                        onFileClick = onFileClick
                                    )
                                }
                            }
                        }

                        // Folders section
                        if (uiState.folders.isNotEmpty()) {
                            item {
                                ContentSection(
                                    title = "Your Library",
                                    subtitle = "${uiState.folders.size} folders",
                                    icon = Icons.Default.Folder
                                ) {
                                    FolderRow(
                                        title = "",
                                        folders = uiState.folders,
                                        onFolderClick = onFolderClick
                                    )
                                }
                            }
                        }

                        // Empty state
                        if (uiState.continueWatching.isEmpty() && 
                            uiState.recentFiles.isEmpty() && 
                            uiState.folders.isEmpty()) {
                            item {
                                ModernEmptyState()
                            }
                        }
                    }
                }
            }
        }
    }

    // Request focus on first load
    LaunchedEffect(uiState.isLoading) {
        if (!uiState.isLoading) {
            kotlinx.coroutines.delay(100)
            try {
                focusRequester.requestFocus()
            } catch (e: IllegalStateException) {
                // Ignore
            }
        }
    }
}

/**
 * Modern top bar with gradient and refined styling.
 */
@Composable
private fun ModernTopBar(
onSearchClick: () -> Unit,
onGrabClick: () -> Unit,
onSettingsClick: () -> Unit
) {
    Box(
        modifier = Modifier
            .fillMaxWidth()
            .background(
                Brush.verticalGradient(
                    colors = listOf(
                        Color.Black.copy(alpha = 0.8f),
                        Color.Transparent
                    )
                )
            )
    ) {
        Row(
            modifier = Modifier
                .fillMaxWidth()
                .padding(horizontal = 40.dp, vertical = 20.dp),
            horizontalArrangement = Arrangement.SpaceBetween,
            verticalAlignment = Alignment.CenterVertically
        ) {
            // App branding
            Row(verticalAlignment = Alignment.CenterVertically) {
                // Logo
                Surface(
                    color = TVPrimary.copy(alpha = 0.15f),
                    shape = RoundedCornerShape(14.dp),
                    modifier = Modifier.size(46.dp)
                ) {
                    Box(contentAlignment = Alignment.Center) {
                        Image(
                            painter = painterResource(id = com.aruvi.tir.R.drawable.app_logo),
                            contentDescription = null,
                            modifier = Modifier.size(36.dp),
                            contentScale = ContentScale.Fit
                        )
                    }
                }
                
                Spacer(modifier = Modifier.width(14.dp))
                
                Column {
                    Text(
                        text = "Aruvi",
                        style = MaterialTheme.typography.titleLarge,
                        color = TVTextPrimary,
                        fontWeight = FontWeight.Bold,
                        fontSize = 22.sp,
                        letterSpacing = (-0.5).sp
                    )
                    Text(
                        text = "Stream your files",
                        style = MaterialTheme.typography.bodySmall,
                        color = TVTextSecondary.copy(alpha = 0.6f),
                        fontSize = 11.sp,
                        letterSpacing = 0.5.sp
                    )
                }
            }

        // Action buttons
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            ModernActionButton(
                icon = Icons.Outlined.Search,
                label = "Search",
                onClick = onSearchClick
            )

            ModernActionButton(
                icon = Icons.Outlined.Movie,
                label = "Movies",
                onClick = onGrabClick
            )

            ModernActionButton(
                icon = Icons.Outlined.Settings,
                label = "Settings",
                onClick = onSettingsClick
            )
        }
            
        }
    }
}

/**
 * Modern action button for top bar.
 */
@Composable
private fun ModernActionButton(
    icon: ImageVector,
    label: String,
    onClick: () -> Unit
) {
    var isFocused by remember { mutableStateOf(false) }
    
    Surface(
        onClick = onClick,
        color = if (isFocused) TVPrimary.copy(alpha = 0.2f) else Color.White.copy(alpha = 0.05f),
        shape = RoundedCornerShape(10.dp),
        modifier = Modifier
            .onFocusChanged { isFocused = it.isFocused }
            .border(
                width = if (isFocused) 2.dp else 0.dp,
                color = if (isFocused) TVPrimary else Color.Transparent,
                shape = RoundedCornerShape(10.dp)
            )
    ) {
        Row(
            modifier = Modifier.padding(horizontal = 14.dp, vertical = 10.dp),
            verticalAlignment = Alignment.CenterVertically
        ) {
            Icon(
                imageVector = icon,
                contentDescription = label,
                tint = if (isFocused) TVPrimary else TVTextSecondary,
                modifier = Modifier.size(18.dp)
            )
            Spacer(modifier = Modifier.width(8.dp))
            Text(
                text = label,
                style = MaterialTheme.typography.bodyMedium,
                color = if (isFocused) TVTextPrimary else TVTextSecondary,
                fontWeight = if (isFocused) FontWeight.Medium else FontWeight.Normal,
                fontSize = 13.sp
            )
        }
    }
}

/**
 * Content section with header.
 */
@Composable
private fun ContentSection(
    title: String,
    subtitle: String,
    icon: ImageVector,
    content: @Composable () -> Unit
) {
    Column(
        modifier = Modifier.padding(top = 16.dp)
    ) {
        // Section header
        Row(
            modifier = Modifier
                .fillMaxWidth()
                .padding(horizontal = 40.dp, vertical = 8.dp),
            verticalAlignment = Alignment.CenterVertically
        ) {
            // Accent line
            Box(
                modifier = Modifier
                    .width(3.dp)
                    .height(24.dp)
                    .clip(RoundedCornerShape(2.dp))
                    .background(TVPrimary)
            )
            
            Spacer(modifier = Modifier.width(12.dp))
            
            Icon(
                imageVector = icon,
                contentDescription = null,
                tint = TVPrimary.copy(alpha = 0.8f),
                modifier = Modifier.size(18.dp)
            )
            
            Spacer(modifier = Modifier.width(10.dp))
            
            Column {
                Text(
                    text = title,
                    style = MaterialTheme.typography.titleMedium,
                    color = TVTextPrimary,
                    fontWeight = FontWeight.SemiBold,
                    fontSize = 16.sp,
                    letterSpacing = 0.sp
                )
                Text(
                    text = subtitle,
                    style = MaterialTheme.typography.bodySmall,
                    color = TVTextSecondary.copy(alpha = 0.5f),
                    fontSize = 11.sp
                )
            }
        }
        
        Spacer(modifier = Modifier.height(8.dp))
        
        content()
    }
}

/**
 * Full-width hero banner for featured content.
 */
@Composable
private fun HeroBanner(
    file: com.aruvi.tir.data.model.FileItem,
    thumbnailUrl: String,
    onPlay: () -> Unit
) {
    var isFocused by remember { mutableStateOf(false) }
    val context = LocalContext.current

    val heroStyle = FocusTrailDefaults.tvCardStyle(
        shape = FocusTrailShape.ROUND_RECT,
        durationMs = 10_000L,
        startDelayMs = 1_000L,
        cornerRadius = 20.dp,
        borderWidth = 3.dp,
        staticBorderWidth = 3.dp,
        trailPadding = 14.dp,
        glowWidth = 14.dp,
        staticColor = TVFocusRing.toArgb(),
        trailColor = TVFocusRing.toArgb(),
        baseAlpha = 150,
        glowAlpha = 60,
        highlightAlpha = 255,
        trailLengthRatio = 0.16f,
        minTrailLength = 48.dp,
        drawOppositeTrail = true,
        focusScale = 1.02f
    )

    FocusTrailBox(
        modifier = Modifier
            .fillMaxWidth()
            .height(320.dp)
            .padding(horizontal = 40.dp, vertical = 12.dp)
            .tiltOnFocus(isFocused, maxDegrees = 2f),
        active = isFocused,
        style = heroStyle
    ) {
        Box(
            modifier = Modifier
                .fillMaxSize()
                .clip(RoundedCornerShape(24.dp))
                .background(TVCardBackground)
                .clickable(
                    onClick = {
                        TvSound.click(context)
                        onPlay()
                    }
                )
                .onFocusChanged { state ->
                    if (state.isFocused && !isFocused) {
                        TvSound.navigate(context)
                    }
                    isFocused = state.isFocused
                }
        ) {
        // Backdrop image with placeholder layer
        Box(
            modifier = Modifier
                .fillMaxSize()
                .background(TVCardBackground),
            contentAlignment = Alignment.Center
        ) {
            Icon(
                imageVector = Icons.Default.Movie,
                contentDescription = null,
                modifier = Modifier.size(72.dp),
                tint = TVTextDisabled.copy(alpha = 0.5f)
            )
        }
        AsyncImage(
            model = thumbnailUrl,
            contentDescription = file.fileName,
            modifier = Modifier.fillMaxSize(),
            contentScale = ContentScale.Crop
        )

        // Scrim for readability
        Box(
            modifier = Modifier
                .fillMaxWidth()
                .fillMaxHeight()
                .background(
                    Brush.horizontalGradient(
                        colors = listOf(
                            Color.Black.copy(alpha = 0.85f),
                            Color.Black.copy(alpha = 0.25f),
                            Color.Transparent
                        )
                    )
                )
        )

        // Content overlay
        Column(
            modifier = Modifier
                .align(Alignment.CenterStart)
                .padding(horizontal = 40.dp)
        ) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Box(
                    modifier = Modifier
                        .clip(RoundedCornerShape(8.dp))
                        .background(TVPrimary)
                        .padding(horizontal = 10.dp, vertical = 4.dp)
                ) {
                    Text(
                        text = if (file.progressPercent > 0f) "RESUME" else "FEATURED",
                        style = MaterialTheme.typography.labelLarge,
                        color = Color.Black,
                        fontWeight = FontWeight.Bold,
                        letterSpacing = 2.sp
                    )
                }
            }

            Spacer(modifier = Modifier.height(12.dp))

            Text(
                text = file.fileName,
                style = MaterialTheme.typography.headlineLarge,
                color = Color.White,
                fontWeight = FontWeight.Bold,
                maxLines = if (isFocused) 1 else 2,
                overflow = if (isFocused) TextOverflow.Clip else TextOverflow.Ellipsis,
                modifier = if (isFocused) Modifier.basicMarquee() else Modifier
            )

            Spacer(modifier = Modifier.height(8.dp))

            Row(horizontalArrangement = Arrangement.spacedBy(16.dp)) {
                Text(
                    text = file.formattedSize,
                    style = MaterialTheme.typography.bodyMedium,
                    color = Color.White.copy(alpha = 0.8f)
                )
                file.formattedDuration?.let { duration ->
                    Text(
                        text = duration,
                        style = MaterialTheme.typography.bodyMedium,
                        color = Color.White.copy(alpha = 0.8f)
                    )
                }
                file.resolution?.let { res ->
                    Text(
                        text = res,
                        style = MaterialTheme.typography.bodyMedium,
                        color = TVPrimaryLight
                    )
                }
            }
        }

        // Play affordance
        Row(
            modifier = Modifier
                .align(Alignment.CenterEnd)
                .padding(horizontal = 48.dp)
                .clip(RoundedCornerShape(16.dp))
                .background(Color.Black.copy(alpha = 0.55f))
                .padding(horizontal = 20.dp, vertical = 12.dp),
            verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.spacedBy(8.dp)
        ) {
            Icon(
                imageVector = Icons.Default.PlayArrow,
                contentDescription = null,
                modifier = Modifier.size(28.dp),
                tint = Color.White
            )
            Text(
                text = if (file.progressPercent > 0f) "Continue" else "Play",
                style = MaterialTheme.typography.titleMedium,
                color = Color.White,
                fontWeight = FontWeight.SemiBold
            )
        }
        }
    }
}

/**
 * Modern loading state with animation.
 */
@Composable
private fun ModernLoadingState() {
    Column(
        modifier = Modifier
            .fillMaxSize()
            .padding(horizontal = 48.dp, vertical = 80.dp)
    ) {
        // Fake top bar shimmer
        Row(
            modifier = Modifier
                .fillMaxWidth()
                .padding(bottom = 32.dp),
            horizontalArrangement = Arrangement.SpaceBetween
        ) {
            ShimmerBlock(width = 200.dp, height = 40.dp)
            Row(horizontalArrangement = Arrangement.spacedBy(16.dp)) {
                ShimmerBlock(width = 44.dp, height = 44.dp, shape = CircleShape)
                ShimmerBlock(width = 44.dp, height = 44.dp, shape = CircleShape)
            }
        }

        // Section title shimmer
        ShimmerBlock(width = 180.dp, height = 20.dp)
        Spacer(modifier = Modifier.height(16.dp))

        // Row of shimmer cards
        Row(horizontalArrangement = Arrangement.spacedBy(16.dp)) {
            repeat(5) {
                ShimmerCard()
            }
        }

        Spacer(modifier = Modifier.height(32.dp))

        // Second section
        ShimmerBlock(width = 150.dp, height = 20.dp)
        Spacer(modifier = Modifier.height(16.dp))

        Row(horizontalArrangement = Arrangement.spacedBy(16.dp)) {
            repeat(5) {
                ShimmerCard()
            }
        }

        Spacer(modifier = Modifier.height(24.dp))

        // Loading message
        Box(
            modifier = Modifier.fillMaxWidth(),
            contentAlignment = Alignment.Center
        ) {
            val infiniteTransition = rememberInfiniteTransition(label = "loading")
            val alpha by infiniteTransition.animateFloat(
                initialValue = 0.4f,
                targetValue = 1f,
                animationSpec = infiniteRepeatable(
                    animation = tween(800),
                    repeatMode = RepeatMode.Reverse
                ),
                label = "alpha"
            )
            Text(
                text = "Loading your library...",
                style = MaterialTheme.typography.bodyMedium,
                color = TVTextSecondary.copy(alpha = alpha * 0.7f)
            )
        }
    }
}

/**
 * Shimmer block helper for various shapes.
 */
@Composable
private fun ShimmerBlock(
    width: androidx.compose.ui.unit.Dp,
    height: androidx.compose.ui.unit.Dp,
    shape: androidx.compose.ui.graphics.Shape = RoundedCornerShape(8.dp)
) {
    val shimmerColors = listOf(TVCardBackground, TVCardFocused, TVCardBackground)
    val transition = rememberInfiniteTransition(label = "shimmer")
    val translateAnim by transition.animateFloat(
        initialValue = 0f, targetValue = 1000f,
        animationSpec = infiniteRepeatable(
            animation = tween(1200, easing = FastOutSlowInEasing),
            repeatMode = RepeatMode.Restart
        ), label = "offset"
    )
    Box(
        modifier = Modifier
            .width(width)
            .height(height)
            .clip(shape)
            .background(
                brush = Brush.horizontalGradient(
                    colors = shimmerColors,
                    startX = translateAnim - 200f,
                    endX = translateAnim + 200f
                )
            )
    )
}

/**
 * Modern error state.
 */
@Composable
private fun ModernErrorState(
    message: String,
    onRetry: () -> Unit,
    onSettings: () -> Unit
) {
    var isRetryFocused by remember { mutableStateOf(false) }
    var isSettingsFocused by remember { mutableStateOf(false) }
    
    Box(
        modifier = Modifier.fillMaxSize(),
        contentAlignment = Alignment.Center
    ) {
        Column(
            horizontalAlignment = Alignment.CenterHorizontally,
            modifier = Modifier.padding(48.dp)
        ) {
            Surface(
                color = TVError.copy(alpha = 0.1f),
                shape = CircleShape,
                modifier = Modifier.size(72.dp)
            ) {
                Box(contentAlignment = Alignment.Center) {
                    Icon(
                        imageVector = Icons.Default.CloudOff,
                        contentDescription = null,
                        tint = TVError,
                        modifier = Modifier.size(36.dp)
                    )
                }
            }
            
            Spacer(modifier = Modifier.height(24.dp))
            
            Text(
                text = "Connection Error",
                style = MaterialTheme.typography.titleLarge,
                color = TVTextPrimary,
                fontWeight = FontWeight.SemiBold,
                fontSize = 20.sp
            )
            
            Spacer(modifier = Modifier.height(8.dp))
            
            Text(
                text = message,
                style = MaterialTheme.typography.bodyMedium,
                color = TVTextSecondary,
                fontSize = 13.sp
            )
            
            Spacer(modifier = Modifier.height(32.dp))
            
            Row(horizontalArrangement = Arrangement.spacedBy(16.dp)) {
                // Retry Button
                Surface(
                    onClick = onRetry,
                    color = if (isRetryFocused) TVPrimary else TVPrimary.copy(alpha = 0.8f),
                    shape = RoundedCornerShape(8.dp),
                    modifier = Modifier
                        .onFocusChanged { isRetryFocused = it.isFocused }
                        .border(
                            width = if (isRetryFocused) 2.dp else 0.dp,
                            color = if (isRetryFocused) Color.White.copy(alpha = 0.3f) else Color.Transparent,
                            shape = RoundedCornerShape(8.dp)
                        )
                ) {
                    Row(
                        modifier = Modifier.padding(horizontal = 24.dp, vertical = 12.dp),
                        verticalAlignment = Alignment.CenterVertically
                    ) {
                        Icon(
                            imageVector = Icons.Default.Refresh,
                            contentDescription = null,
                            tint = Color.White,
                            modifier = Modifier.size(18.dp)
                        )
                        Spacer(modifier = Modifier.width(10.dp))
                        Text(
                            text = "Try Again",
                            color = Color.White,
                            fontWeight = FontWeight.Medium,
                            fontSize = 14.sp
                        )
                    }
                }

                // Settings Button
                Surface(
                    onClick = onSettings,
                    color = if (isSettingsFocused) Color.White.copy(alpha = 0.1f) else Color.Transparent,
                    shape = RoundedCornerShape(8.dp),
                    modifier = Modifier
                        .onFocusChanged { isSettingsFocused = it.isFocused }
                        .border(
                            width = 1.dp,
                            color = if (isSettingsFocused) TVPrimary else Color.White.copy(alpha = 0.2f),
                            shape = RoundedCornerShape(8.dp)
                        )
                ) {
                    Row(
                        modifier = Modifier.padding(horizontal = 24.dp, vertical = 12.dp),
                        verticalAlignment = Alignment.CenterVertically
                    ) {
                        Icon(
                            imageVector = Icons.Default.Settings,
                            contentDescription = null,
                            tint = TVTextPrimary,
                            modifier = Modifier.size(18.dp)
                        )
                        Spacer(modifier = Modifier.width(10.dp))
                        Text(
                            text = "Settings",
                            color = TVTextPrimary,
                            fontWeight = FontWeight.Medium,
                            fontSize = 14.sp
                        )
                    }
                }
            }
        }
    }
}

/**
 * Modern empty state.
 */
@Composable
private fun ModernEmptyState() {
    Box(
        modifier = Modifier
            .fillMaxSize()
            .padding(top = 80.dp),
        contentAlignment = Alignment.TopCenter
    ) {
        Column(
            horizontalAlignment = Alignment.CenterHorizontally
        ) {
            Surface(
                color = TVPrimary.copy(alpha = 0.1f),
                shape = CircleShape,
                modifier = Modifier.size(80.dp)
            ) {
                Box(contentAlignment = Alignment.Center) {
                    Icon(
                        imageVector = Icons.Outlined.VideoLibrary,
                        contentDescription = null,
                        tint = TVPrimary.copy(alpha = 0.7f),
                        modifier = Modifier.size(40.dp)
                    )
                }
            }
            
            Spacer(modifier = Modifier.height(24.dp))
            
            Text(
                text = "Your Library is Empty",
                style = MaterialTheme.typography.titleLarge,
                color = TVTextPrimary,
                fontWeight = FontWeight.SemiBold,
                fontSize = 20.sp
            )
            
            Spacer(modifier = Modifier.height(8.dp))
            
            Text(
                text = "Send files via Telegram bot to get started",
                style = MaterialTheme.typography.bodyMedium,
                color = TVTextSecondary.copy(alpha = 0.6f),
                fontSize = 13.sp
            )
        }
    }
}
