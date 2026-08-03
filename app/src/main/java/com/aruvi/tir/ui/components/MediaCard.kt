package com.aruvi.tir.ui.components

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.basicMarquee
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.*
import androidx.compose.material3.Icon
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import coil.compose.AsyncImage
import com.aruvi.tir.data.model.FileItem
import com.aruvi.tir.ui.theme.*

/**
 * TV-optimized media card with focus-trail glow, 3D tilt, and type badges.
 */
@Composable
fun MediaCard(
    file: FileItem,
    thumbnailUrl: String,
    onClick: () -> Unit,
    modifier: Modifier = Modifier
) {
    FocusedCard(
        onClick = onClick,
        modifier = modifier
            .width(220.dp)
            .height(180.dp),
        cornerRadius = 16.dp,
        focusScale = 1.08f
    ) { isFocused ->
        Box(modifier = Modifier.fillMaxSize()) {
            // Placeholder layer (visible while loading or on image error)
            Box(
                modifier = Modifier
                    .fillMaxWidth()
                    .aspectRatio(16f / 9f)
                    .background(TVCardBackground),
                contentAlignment = Alignment.Center
            ) {
                Icon(
                    imageVector = Icons.Filled.Movie,
                    contentDescription = null,
                    modifier = Modifier.size(48.dp),
                    tint = TVTextDisabled.copy(alpha = 0.5f)
                )
            }

            // Thumbnail
            AsyncImage(
                model = thumbnailUrl,
                contentDescription = file.fileName,
                modifier = Modifier
                    .fillMaxWidth()
                    .aspectRatio(16f / 9f),
                contentScale = ContentScale.Crop
            )

            // Gradient overlay
            Box(
                modifier = Modifier
                    .fillMaxWidth()
                    .height(90.dp)
                    .align(Alignment.BottomCenter)
                    .background(
                        Brush.verticalGradient(
                            colors = listOf(
                                Color.Transparent,
                                Color.Black.copy(alpha = 0.85f)
                            )
                        )
                    )
            )

            // File type badge (top-right)
            FileTypeBadge(
                fileName = file.fileName,
                modifier = Modifier
                    .align(Alignment.TopEnd)
                    .padding(8.dp)
            )

            // Resume badge (top-left) for in-progress content
            if (file.progressPercent > 0f) {
                ResumeBadge(
                    modifier = Modifier
                        .align(Alignment.TopStart)
                        .padding(8.dp)
                )
            }

            // File info
            Column(
                modifier = Modifier
                    .align(Alignment.BottomStart)
                    .padding(12.dp)
            ) {
                Text(
                    text = file.fileName,
                    style = MaterialTheme.typography.bodyMedium,
                    color = TVTextPrimary,
                    fontWeight = if (isFocused) FontWeight.SemiBold else FontWeight.Normal,
                    maxLines = if (isFocused) 1 else 2,
                    overflow = if (isFocused) TextOverflow.Clip else TextOverflow.Ellipsis,
                    modifier = if (isFocused) Modifier.basicMarquee() else Modifier
                )

                Spacer(modifier = Modifier.height(4.dp))

                Row(
                    modifier = Modifier.fillMaxWidth(),
                    horizontalArrangement = Arrangement.SpaceBetween
                ) {
                    Text(
                        text = file.formattedSize,
                        style = MaterialTheme.typography.labelSmall,
                        color = TVTextSecondary
                    )
                    file.formattedDuration?.let { duration ->
                        Text(
                            text = duration,
                            style = MaterialTheme.typography.labelSmall,
                            color = TVTextSecondary
                        )
                    }
                }
            }

            // Watch progress bar
            if (file.progressPercent > 0f) {
                LinearProgressIndicator(
                    progress = { file.progressPercent / 100f },
                    modifier = Modifier
                        .fillMaxWidth()
                        .height(3.dp)
                        .align(Alignment.BottomCenter),
                    color = TVPrimary,
                    trackColor = TVProgressBackground
                )
            }
        }
    }
}

/**
 * File type badge showing 🎬 video, 🎵 audio, etc.
 */
@Composable
private fun FileTypeBadge(
    fileName: String,
    modifier: Modifier = Modifier
) {
    val extension = fileName.substringAfterLast('.', "").lowercase()
    val (icon, color) = when (extension) {
        "mp4", "mkv", "avi", "mov", "wmv", "flv", "webm", "m4v" ->
            Icons.Default.Movie to TVPrimary
        "mp3", "flac", "aac", "ogg", "wav", "m4a", "wma" ->
            Icons.Default.MusicNote to TVSecondary
        "srt", "ass", "sub", "ssa", "vtt" ->
            Icons.Default.Subtitles to TVWarning
        "jpg", "jpeg", "png", "gif", "bmp", "webp" ->
            Icons.Default.Image to TVSuccess
        else -> return // no badge for unknown types
    }

    Box(
        modifier = modifier
            .size(28.dp)
            .background(
                color = Color.Black.copy(alpha = 0.65f),
                shape = CircleShape
            ),
        contentAlignment = Alignment.Center
    ) {
        Icon(
            imageVector = icon,
            contentDescription = null,
            tint = color,
            modifier = Modifier.size(16.dp)
        )
    }
}

/**
 * Resume badge shown on in-progress content.
 */
@Composable
private fun ResumeBadge(modifier: Modifier = Modifier) {
    Row(
        modifier = modifier
            .clip(RoundedCornerShape(12.dp))
            .background(Color.Black.copy(alpha = 0.7f))
            .padding(horizontal = 8.dp, vertical = 4.dp),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(4.dp)
    ) {
        Icon(
            imageVector = Icons.Default.PlayArrow,
            contentDescription = null,
            modifier = Modifier.size(14.dp),
            tint = TVPrimaryLight
        )
        Text(
            text = "Resume",
            style = MaterialTheme.typography.labelMedium,
            color = TVTextPrimary
        )
    }
}

/**
 * Large media card variant for featured content.
 */
@Composable
fun LargeMediaCard(
    file: FileItem,
    thumbnailUrl: String,
    onClick: () -> Unit,
    modifier: Modifier = Modifier
) {
    FocusedCard(
        onClick = onClick,
        modifier = modifier
            .width(320.dp)
            .height(220.dp),
        cornerRadius = 16.dp,
        focusScale = 1.05f
    ) { isFocused ->
        Box(modifier = Modifier.fillMaxSize()) {
            // Placeholder layer (visible while loading or on image error)
            Box(
                modifier = Modifier
                    .fillMaxSize()
                    .background(TVCardBackground),
                contentAlignment = Alignment.Center
            ) {
                Icon(
                    imageVector = Icons.Filled.Movie,
                    contentDescription = null,
                    modifier = Modifier.size(64.dp),
                    tint = TVTextDisabled.copy(alpha = 0.5f)
                )
            }

            AsyncImage(
                model = thumbnailUrl,
                contentDescription = file.fileName,
                modifier = Modifier.fillMaxSize(),
                contentScale = ContentScale.Crop
            )

            // Gradient overlay
            Box(
                modifier = Modifier
                    .fillMaxWidth()
                    .height(110.dp)
                    .align(Alignment.BottomCenter)
                    .background(
                        Brush.verticalGradient(
                            colors = listOf(
                                Color.Transparent,
                                Color.Black.copy(alpha = 0.92f)
                            )
                        )
                    )
            )

            // File type badge
            FileTypeBadge(
                fileName = file.fileName,
                modifier = Modifier
                    .align(Alignment.TopEnd)
                    .padding(10.dp)
            )

            // Resume badge (top-left) for in-progress content
            if (file.progressPercent > 0f) {
                ResumeBadge(
                    modifier = Modifier
                        .align(Alignment.TopStart)
                        .padding(10.dp)
                )
            }

            // File info
            Column(
                modifier = Modifier
                    .align(Alignment.BottomStart)
                    .padding(16.dp)
            ) {
                Text(
                    text = file.fileName,
                    style = MaterialTheme.typography.titleMedium,
                    color = TVTextPrimary,
                    fontWeight = if (isFocused) FontWeight.Bold else FontWeight.SemiBold,
                    maxLines = if (isFocused) 1 else 2,
                    overflow = if (isFocused) TextOverflow.Clip else TextOverflow.Ellipsis,
                    modifier = if (isFocused) Modifier.basicMarquee() else Modifier
                )

                Spacer(modifier = Modifier.height(6.dp))

                Row(horizontalArrangement = Arrangement.spacedBy(16.dp)) {
                    Text(
                        text = file.formattedSize,
                        style = MaterialTheme.typography.bodySmall,
                        color = TVTextSecondary
                    )
                    file.formattedDuration?.let { duration ->
                        Text(
                            text = duration,
                            style = MaterialTheme.typography.bodySmall,
                            color = TVTextSecondary
                        )
                    }
                    file.resolution?.let { res ->
                        Text(
                            text = res,
                            style = MaterialTheme.typography.bodySmall,
                            color = TVPrimaryLight
                        )
                    }
                }
            }

            // Progress bar
            if (file.progressPercent > 0f) {
                LinearProgressIndicator(
                    progress = { file.progressPercent / 100f },
                    modifier = Modifier
                        .fillMaxWidth()
                        .height(4.dp)
                        .align(Alignment.BottomCenter),
                    color = TVPrimary,
                    trackColor = TVProgressBackground
                )
            }
        }
    }
}
