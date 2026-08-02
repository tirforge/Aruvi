package com.aruvi.tir.ui.details

import android.app.DownloadManager
import androidx.compose.animation.animateColorAsState
import androidx.compose.animation.core.*
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.filled.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.graphics.graphicsLayer
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.draw.scale
import androidx.compose.ui.draw.shadow
import androidx.compose.ui.focus.FocusRequester
import androidx.compose.ui.focus.focusRequester
import androidx.compose.ui.focus.onFocusChanged
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.hilt.navigation.compose.hiltViewModel
import androidx.compose.foundation.lazy.LazyColumn
import coil.compose.AsyncImage
import com.aruvi.tir.ui.components.*
import com.aruvi.tir.ui.theme.*
import java.io.File

/**
 * Modern file details screen with hero layout and glassmorphic metadata.
 */
@Composable
fun DetailsScreen(
    fileId: Int,
    onPlayClick: (Int, Long) -> Unit,
    onBackClick: () -> Unit,
    viewModel: DetailsViewModel = hiltViewModel()
) {
    val uiState by viewModel.uiState.collectAsState()
    val playButtonFocus = remember { FocusRequester() }

    // Give the primary play button initial focus once details are loaded
    LaunchedEffect(uiState.file) {
        if (uiState.file != null) {
            kotlinx.coroutines.delay(150)
            try {
                playButtonFocus.requestFocus()
            } catch (e: IllegalStateException) {
                // Ignore
            }
        }
    }

    Box(
        modifier = Modifier
            .fillMaxSize()
            .background(TVBackground)
    ) {
        when {
            uiState.isLoading -> {
                LoadingIndicator(message = "Loading file details...")
            }

            uiState.error != null -> {
                ErrorState(
                    message = uiState.error!!,
                    onRetry = { viewModel.loadFileDetails() }
                )
            }

            uiState.file != null -> {
                val file = uiState.file!!
                val watchProgress = uiState.watchProgress
                val context = LocalContext.current

                // Background thumbnail with gradient
                Box(modifier = Modifier.fillMaxSize()) {
                    AsyncImage(
                        model = viewModel.getThumbnailUrl(),
                        contentDescription = null,
                        modifier = Modifier.fillMaxSize(),
                        contentScale = ContentScale.Crop,
                        alpha = 0.25f
                    )

                    // Gradient overlays
                    Box(
                        modifier = Modifier
                            .fillMaxSize()
                            .background(
                                Brush.horizontalGradient(
                                    colors = listOf(
                                        TVBackground,
                                        TVBackground.copy(alpha = 0.85f),
                                        Color.Transparent
                                    )
                                )
                            )
                    )
                    Box(
                        modifier = Modifier
                            .fillMaxSize()
                            .background(
                                Brush.verticalGradient(
                                    colors = listOf(
                                        Color.Transparent,
                                        TVBackground.copy(alpha = 0.6f)
                                    )
                                )
                            )
                    )
                }

                // Content
                Row(
                    modifier = Modifier
                        .fillMaxSize()
                        .padding(48.dp)
                ) {
                    // Left side - Info
                    LazyColumn(
                        modifier = Modifier
                            .weight(0.6f)
                            .fillMaxHeight()
                    ) {
                        item {
                            Spacer(modifier = Modifier.height(32.dp))
                        }

                        item {
                            Spacer(modifier = Modifier.height(32.dp))

                            // File name
                            Text(
                                text = file.fileName,
                                style = MaterialTheme.typography.displaySmall,
                                color = TVTextPrimary,
                                fontWeight = FontWeight.Bold
                            )
                        }

                        item {
                            Spacer(modifier = Modifier.height(20.dp))

                            // Glassmorphic metadata chips
                            Row(
                                horizontalArrangement = Arrangement.spacedBy(12.dp)
                            ) {
                                GlassMetadataChip(
                                    icon = Icons.Default.Storage,
                                    label = "Size",
                                    value = file.formattedSize
                                )
                                file.formattedDuration?.let {
                                    GlassMetadataChip(
                                        icon = Icons.Default.Timer,
                                        label = "Duration",
                                        value = it
                                    )
                                }
                                file.resolution?.let {
                                    GlassMetadataChip(
                                        icon = Icons.Default.HighQuality,
                                        label = "Quality",
                                        value = it,
                                        accent = true
                                    )
                                }
                                GlassMetadataChip(
                                    icon = Icons.Default.Description,
                                    label = "Type",
                                    value = file.fileType.uppercase()
                                )
                            }
                        }

                        item {
                            Spacer(modifier = Modifier.height(48.dp))

                            // Play buttons
                            Row(
                                horizontalArrangement = Arrangement.spacedBy(16.dp)
                            ) {
                                if (watchProgress != null && watchProgress.position > 0 && !watchProgress.completed) {
                                    FocusablePlayButton(
                                        text = "Resume from ${watchProgress.formattedPosition}",
                                        icon = Icons.Default.PlayArrow,
                                        isPrimary = true,
                                        onClick = { onPlayClick(fileId, watchProgress.position * 1000L) },
                                        modifier = Modifier.focusRequester(playButtonFocus)
                                    )

                                    FocusablePlayButton(
                                        text = "Play from Start",
                                        icon = Icons.Default.Replay,
                                        isPrimary = false,
                                        onClick = { onPlayClick(fileId, 0L) }
                                    )
                                } else {
                                    FocusablePlayButton(
                                        text = "Play",
                                        icon = Icons.Default.PlayArrow,
                                        isPrimary = true,
                                        onClick = { onPlayClick(fileId, 0L) },
                                        modifier = Modifier.focusRequester(playButtonFocus)
                                    )
                                }
                            }
                        }

                        item {
                            Spacer(modifier = Modifier.height(16.dp))

                            // Download section — separate row
                            when {
                                uiState.downloadStatus == DownloadManager.STATUS_RUNNING ||
                                uiState.downloadStatus == DownloadManager.STATUS_PENDING -> {
                                    DownloadProgressCard(
                                        progress = uiState.downloadProgress,
                                        status = uiState.downloadStatus!!,
                                        fileName = file.fileName,
                                        downloadedBytes = uiState.downloadedBytes,
                                        totalBytes = uiState.totalBytes,
                                        speed = uiState.downloadSpeed,
                                        formatBytes = { viewModel.formatBytes(it) }
                                    )
                                }
                                uiState.isFileLocal -> {
                                    // File is downloaded — show local file management
                                    LocalFileCard(
                                        fileName = file.fileName,
                                        filePath = uiState.localFilePath ?: "",
                                        fileSize = viewModel.formatBytes(
                                            uiState.totalBytes.takeIf { it > 0 }
                                                ?: run {
                                                    val localPath = uiState.localFilePath ?: ""
                                                    if (localPath.startsWith("content://")) {
                                                        try {
                                                            context.contentResolver.openFileDescriptor(android.net.Uri.parse(localPath), "r")?.use { it.statSize } ?: 0L
                                                        } catch (e: Exception) {
                                                            0L
                                                        }
                                                    } else {
                                                        val f = File(localPath)
                                                        if (f.exists()) f.length() else 0L
                                                    }
                                                }
                                        ),
                                        onPlayOffline = { onPlayClick(fileId, 0L) },
                                        onDelete = { viewModel.deleteLocalFile(context) }
                                    )
                                }
                                else -> {
                                    FocusablePlayButton(
                                        text = "Download",
                                        icon = Icons.Default.CloudDownload,
                                        isPrimary = false,
                                        onClick = { viewModel.startDownload(context) }
                                    )
                                }
                            }
                        }

                        item {
                            Spacer(modifier = Modifier.height(32.dp))
                        }
                    }

                    // Right side - Large thumbnail
                    Column(
                        modifier = Modifier
                            .weight(0.4f)
                            .fillMaxHeight(),
                        horizontalAlignment = Alignment.CenterHorizontally,
                        verticalArrangement = Arrangement.Center
                    ) {
                        Surface(
                            shape = RoundedCornerShape(16.dp),
                            shadowElevation = 12.dp,
                            modifier = Modifier
                                .fillMaxWidth(0.9f)
                                .aspectRatio(16f / 9f)
                        ) {
                            AsyncImage(
                                model = viewModel.getThumbnailUrl(),
                                contentDescription = file.fileName,
                                modifier = Modifier.fillMaxSize(),
                                contentScale = ContentScale.Crop
                            )
                        }

                        // Progress bar if watching
                        if (watchProgress != null && watchProgress.position > 0) {
                            Spacer(modifier = Modifier.height(12.dp))
                            LinearProgressIndicator(
                                progress = { watchProgress.progressPercent / 100f },
                                modifier = Modifier
                                    .fillMaxWidth(0.9f)
                                    .height(4.dp)
                                    .clip(RoundedCornerShape(2.dp)),
                                color = TVPrimary,
                                trackColor = TVProgressBackground
                            )
                            Spacer(modifier = Modifier.height(4.dp))
                            Text(
                                text = "${watchProgress.progressPercent.toInt()}% watched",
                                style = MaterialTheme.typography.labelSmall,
                                color = TVTextSecondary
                            )
                        }
                    }
                }
            }
        }
    }
}

/**
 * Glassmorphic metadata chip with icon.
 */
@Composable
private fun GlassMetadataChip(
    icon: ImageVector,
    label: String,
    value: String,
    accent: Boolean = false
) {
    Surface(
        color = Color.White.copy(alpha = 0.06f),
        shape = RoundedCornerShape(12.dp),
        modifier = Modifier.border(
            width = 1.dp,
            color = if (accent) TVPrimary.copy(alpha = 0.3f) else Color.White.copy(alpha = 0.08f),
            shape = RoundedCornerShape(12.dp)
        )
    ) {
        Row(
            modifier = Modifier.padding(horizontal = 14.dp, vertical = 10.dp),
            verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.spacedBy(8.dp)
        ) {
            Icon(
                imageVector = icon,
                contentDescription = null,
                tint = if (accent) TVPrimary else TVTextSecondary,
                modifier = Modifier.size(16.dp)
            )
            Column {
                Text(
                    text = label,
                    style = MaterialTheme.typography.labelSmall,
                    color = TVTextSecondary,
                    fontSize = 10.sp
                )
                Text(
                    text = value,
                    style = MaterialTheme.typography.bodyMedium,
                    color = if (accent) TVPrimaryLight else TVTextPrimary,
                    fontWeight = FontWeight.SemiBold
                )
            }
        }
    }
}

/**
 * Focusable play/action button with glow on focus.
 */
@Composable
private fun FocusablePlayButton(
    text: String,
    icon: ImageVector,
    isPrimary: Boolean,
    onClick: () -> Unit,
    enabled: Boolean = true,
    modifier: Modifier = Modifier
) {
    var isFocused by remember { mutableStateOf(false) }
    val scale by animateFloatAsState(
        targetValue = if (isFocused) 1.05f else 1f,
        animationSpec = spring(stiffness = Spring.StiffnessMedium),
        label = "btnScale"
    )

    Surface(
        onClick = onClick,
        enabled = enabled,
        color = when {
            !enabled -> TVCardBackground.copy(alpha = 0.5f)
            isPrimary && isFocused -> TVPrimary
            isPrimary -> TVPrimary.copy(alpha = 0.85f)
            isFocused -> TVCardFocused
            else -> Color.Transparent
        },
        shape = RoundedCornerShape(14.dp),
        modifier = modifier
            .graphicsLayer {
                scaleX = scale
                scaleY = scale
            }
            .onFocusChanged { isFocused = it.isFocused }
            .then(
                if (isFocused && isPrimary) Modifier.shadow(
                    elevation = 12.dp,
                    shape = RoundedCornerShape(14.dp),
                    ambientColor = TVPrimary.copy(alpha = 0.3f)
                ) else Modifier
            )
            .border(
                width = if (isFocused) 2.dp else 1.dp,
                color = when {
                    isFocused -> TVFocusRing
                    isPrimary -> Color.Transparent
                    else -> TVTextSecondary.copy(alpha = 0.15f)
                },
                shape = RoundedCornerShape(14.dp)
            )
    ) {
        Row(
            modifier = Modifier.padding(horizontal = 28.dp, vertical = 16.dp),
            verticalAlignment = Alignment.CenterVertically
        ) {
            Icon(
                imageVector = icon,
                contentDescription = null,
                tint = when {
                    !enabled -> TVTextDisabled
                    isPrimary -> Color.White
                    isFocused -> Color.White
                    else -> TVTextPrimary
                },
                modifier = Modifier.size(22.dp)
            )
            Spacer(modifier = Modifier.width(10.dp))
            Text(
                text = text,
                color = when {
                    !enabled -> TVTextDisabled
                    isPrimary -> Color.White
                    isFocused -> Color.White
                    else -> TVTextPrimary
                },
                fontWeight = FontWeight.SemiBold,
                fontSize = 15.sp
            )
        }
    }
}

/**
 * Modern download progress card with animated gradient bar.
 */
@Composable
private fun DownloadProgressCard(
    progress: Int,
    status: Int,
    fileName: String,
    downloadedBytes: Long = 0L,
    totalBytes: Long = -1L,
    speed: Long = 0L,
    formatBytes: (Long) -> String = { "$it B" }
) {
    val animatedProgress by animateFloatAsState(
        targetValue = progress / 100f,
        animationSpec = tween(durationMillis = 600, easing = FastOutSlowInEasing),
        label = "dlProgress"
    )

    // Pulsing glow for the progress bar
    val infiniteTransition = rememberInfiniteTransition(label = "dlPulse")
    val glowAlpha by infiniteTransition.animateFloat(
        initialValue = 0.4f,
        targetValue = 0.8f,
        animationSpec = infiniteRepeatable(
            animation = tween(1200, easing = FastOutSlowInEasing),
            repeatMode = RepeatMode.Reverse
        ),
        label = "glowAlpha"
    )

    // Shimmer offset for pending state
    val shimmerOffset by infiniteTransition.animateFloat(
        initialValue = -1f,
        targetValue = 2f,
        animationSpec = infiniteRepeatable(
            animation = tween(1500, easing = LinearEasing)
        ),
        label = "shimmer"
    )

    Surface(
        color = Color.White.copy(alpha = 0.04f),
        shape = RoundedCornerShape(16.dp),
        modifier = Modifier
            .fillMaxWidth()
            .border(
                width = 1.dp,
                brush = Brush.linearGradient(
                    colors = listOf(
                        TVPrimary.copy(alpha = 0.3f),
                        TVSecondary.copy(alpha = 0.15f),
                        TVPrimary.copy(alpha = 0.3f)
                    )
                ),
                shape = RoundedCornerShape(16.dp)
            )
    ) {
        Column(
            modifier = Modifier.padding(20.dp)
        ) {
            // Header row: icon + status + percentage
            Row(
                modifier = Modifier.fillMaxWidth(),
                verticalAlignment = Alignment.CenterVertically
            ) {
                // Animated download icon
                if (status == DownloadManager.STATUS_PENDING) {
                    CircularProgressIndicator(
                        modifier = Modifier.size(20.dp),
                        strokeWidth = 2.dp,
                        color = TVSecondary
                    )
                } else {
                    Icon(
                        imageVector = Icons.Default.CloudDownload,
                        contentDescription = null,
                        tint = TVPrimary,
                        modifier = Modifier.size(20.dp)
                    )
                }

                Spacer(modifier = Modifier.width(12.dp))

                Column(modifier = Modifier.weight(1f)) {
                    Text(
                        text = if (status == DownloadManager.STATUS_PENDING) "Preparing download..." else "Downloading",
                        style = MaterialTheme.typography.bodyMedium,
                        color = TVTextPrimary,
                        fontWeight = FontWeight.SemiBold
                    )
                    Text(
                        text = fileName,
                        style = MaterialTheme.typography.labelSmall,
                        color = TVTextSecondary,
                        maxLines = 1,
                        overflow = androidx.compose.ui.text.style.TextOverflow.Ellipsis
                    )
                }

                // Percentage
                Text(
                    text = "$progress%",
                    style = MaterialTheme.typography.headlineSmall,
                    color = TVPrimary,
                    fontWeight = FontWeight.Bold
                )
            }

            Spacer(modifier = Modifier.height(8.dp))

            // Speed and size row
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.SpaceBetween
            ) {
                Text(
                    text = if (speed > 0) "${formatBytes(speed)}/s" else "Calculating...",
                    style = MaterialTheme.typography.labelSmall,
                    color = TVSecondary
                )
                Text(
                    text = if (totalBytes > 0) "${formatBytes(downloadedBytes)} / ${formatBytes(totalBytes)}" else formatBytes(downloadedBytes),
                    style = MaterialTheme.typography.labelSmall,
                    color = TVTextSecondary
                )
            }

            Spacer(modifier = Modifier.height(16.dp))

            // Progress bar track
            Box(
                modifier = Modifier
                    .fillMaxWidth()
                    .height(8.dp)
                    .clip(RoundedCornerShape(4.dp))
                    .background(TVSurfaceVariant)
            ) {
                if (status == DownloadManager.STATUS_PENDING) {
                    // Shimmer bar for pending
                    Box(
                        modifier = Modifier
                            .fillMaxHeight()
                            .fillMaxWidth(0.3f)
                            .offset(
                                x = (shimmerOffset * 300).dp.coerceIn(0.dp, 600.dp)
                            )
                            .clip(RoundedCornerShape(4.dp))
                            .background(
                                Brush.horizontalGradient(
                                    colors = listOf(
                                        Color.Transparent,
                                        TVSecondary.copy(alpha = 0.4f),
                                        Color.Transparent
                                    )
                                )
                            )
                    )
                } else {
                    // Filled progress with gradient
                    Box(
                        modifier = Modifier
                            .fillMaxHeight()
                            .fillMaxWidth(animatedProgress.coerceIn(0f, 1f))
                            .clip(RoundedCornerShape(4.dp))
                            .background(
                                Brush.horizontalGradient(
                                    colors = listOf(
                                        TVPrimary,
                                        TVSecondary
                                    )
                                )
                            )
                    )

                    // Glow at the leading edge
                    if (animatedProgress > 0.02f) {
                        Box(
                            modifier = Modifier
                                .fillMaxHeight()
                                .width(12.dp)
                                .offset(x = (animatedProgress * 100).dp)
                                .background(
                                    Brush.horizontalGradient(
                                        colors = listOf(
                                            Color.White.copy(alpha = glowAlpha * 0.6f),
                                            Color.Transparent
                                        )
                                    )
                                )
                        )
                    }
                }
            }
        }
    }
}

/**
 * Card for managing a locally downloaded file.
 */
@Composable
private fun LocalFileCard(
    fileName: String,
    filePath: String,
    fileSize: String,
    onPlayOffline: () -> Unit,
    onDelete: () -> Unit
) {
    var showDeleteConfirm by remember { mutableStateOf(false) }

    Surface(
        color = Color.White.copy(alpha = 0.04f),
        shape = RoundedCornerShape(16.dp),
        modifier = Modifier
            .fillMaxWidth()
            .border(
                width = 1.dp,
                brush = Brush.linearGradient(
                    colors = listOf(
                        Color(0xFF4CAF50).copy(alpha = 0.3f),
                        Color(0xFF81C784).copy(alpha = 0.15f),
                        Color(0xFF4CAF50).copy(alpha = 0.3f)
                    )
                ),
                shape = RoundedCornerShape(16.dp)
            )
    ) {
        Column(
            modifier = Modifier.padding(20.dp)
        ) {
            // Header
            Row(
                modifier = Modifier.fillMaxWidth(),
                verticalAlignment = Alignment.CenterVertically
            ) {
                Icon(
                    imageVector = Icons.Default.CheckCircle,
                    contentDescription = null,
                    tint = Color(0xFF4CAF50),
                    modifier = Modifier.size(20.dp)
                )
                Spacer(modifier = Modifier.width(12.dp))
                Column(modifier = Modifier.weight(1f)) {
                    Text(
                        text = "Downloaded",
                        style = MaterialTheme.typography.bodyMedium,
                        color = Color(0xFF4CAF50),
                        fontWeight = FontWeight.SemiBold
                    )
                    Text(
                        text = fileName,
                        style = MaterialTheme.typography.labelSmall,
                        color = TVTextSecondary,
                        maxLines = 1,
                        overflow = androidx.compose.ui.text.style.TextOverflow.Ellipsis
                    )
                }
                Text(
                    text = fileSize,
                    style = MaterialTheme.typography.labelMedium,
                    color = TVTextSecondary
                )
            }

            Spacer(modifier = Modifier.height(8.dp))

            // Path
            Text(
                text = filePath,
                style = MaterialTheme.typography.labelSmall,
                color = TVTextSecondary.copy(alpha = 0.6f),
                maxLines = 1,
                overflow = androidx.compose.ui.text.style.TextOverflow.Ellipsis
            )

            Spacer(modifier = Modifier.height(16.dp))

            // Action buttons
            Row(
                horizontalArrangement = Arrangement.spacedBy(12.dp)
            ) {
                FocusablePlayButton(
                    text = "Play Offline",
                    icon = Icons.Default.PlayArrow,
                    isPrimary = true,
                    onClick = onPlayOffline
                )
                FocusablePlayButton(
                    text = if (showDeleteConfirm) "Confirm Delete" else "Delete",
                    icon = Icons.Default.Delete,
                    isPrimary = false,
                    onClick = {
                        if (showDeleteConfirm) {
                            onDelete()
                            showDeleteConfirm = false
                        } else {
                            showDeleteConfirm = true
                        }
                    }
                )
            }
        }
    }
}
