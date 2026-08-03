package com.aruvi.tir.ui.components

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.basicMarquee
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Folder
import androidx.compose.material.icons.filled.FolderOpen
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import com.aruvi.tir.data.model.Folder
import com.aruvi.tir.ui.theme.*

/**
 * TV-optimized folder card with gradient background, animated icon,
 * focus-trail glow, and 3D tilt.
 */
@Composable
fun FolderCard(
    folder: Folder,
    onClick: () -> Unit,
    modifier: Modifier = Modifier
) {
    FocusedCard(
        onClick = onClick,
        modifier = modifier
            .width(180.dp)
            .height(120.dp),
        cornerRadius = 16.dp,
        focusScale = 1.08f
    ) { isFocused ->
        Box(
            modifier = Modifier
                .fillMaxSize()
                .background(
                    if (isFocused) Brush.linearGradient(
                        listOf(
                            TVPrimary.copy(alpha = 0.08f),
                            TVSecondary.copy(alpha = 0.04f)
                        )
                    ) else Brush.linearGradient(
                        listOf(
                            TVCardBackground,
                            TVCardBackground
                        )
                    )
                )
                .padding(16.dp)
        ) {
            Column(
                modifier = Modifier.fillMaxSize(),
                horizontalAlignment = Alignment.CenterHorizontally,
                verticalArrangement = Arrangement.Center
            ) {
                Icon(
                    imageVector = if (isFocused) Icons.Default.FolderOpen else Icons.Default.Folder,
                    contentDescription = folder.name,
                    modifier = Modifier.size(48.dp),
                    tint = if (isFocused) TVSecondary else TVTextSecondary
                )

                Spacer(modifier = Modifier.height(12.dp))

                Text(
                    text = folder.name,
                    style = MaterialTheme.typography.bodyMedium,
                    color = TVTextPrimary,
                    fontWeight = if (isFocused) FontWeight.SemiBold else FontWeight.Normal,
                    maxLines = 1,
                    overflow = androidx.compose.ui.text.style.TextOverflow.Clip,
                    modifier = if (isFocused) Modifier.basicMarquee() else Modifier
                )

                folder.fileCount?.let { count ->
                    Text(
                        text = "$count files",
                        style = MaterialTheme.typography.labelSmall,
                        color = if (isFocused) TVSecondary else TVTextSecondary
                    )
                }
            }
        }
    }
}

/**
 * Horizontal folder card for list view.
 */
@Composable
fun FolderListItem(
    folder: Folder,
    onClick: () -> Unit,
    modifier: Modifier = Modifier
) {
    FocusedCard(
        onClick = onClick,
        modifier = modifier
            .fillMaxWidth()
            .height(64.dp),
        cornerRadius = 12.dp,
        focusScale = 1.03f,
        contentPadding = 8.dp,
        trailPadding = 8.dp
    ) { isFocused ->
        Row(
            modifier = Modifier
                .fillMaxSize()
                .padding(horizontal = 16.dp),
            verticalAlignment = Alignment.CenterVertically
        ) {
            Icon(
                imageVector = if (isFocused) Icons.Default.FolderOpen else Icons.Default.Folder,
                contentDescription = folder.name,
                modifier = Modifier.size(32.dp),
                tint = if (isFocused) TVSecondary else TVTextSecondary
            )

            Spacer(modifier = Modifier.width(16.dp))

            Column(modifier = Modifier.weight(1f)) {
                Text(
                    text = folder.name,
                    style = MaterialTheme.typography.bodyLarge,
                    color = TVTextPrimary,
                    fontWeight = if (isFocused) FontWeight.SemiBold else FontWeight.Normal,
                    maxLines = 1,
                    overflow = androidx.compose.ui.text.style.TextOverflow.Clip,
                    modifier = if (isFocused) Modifier.basicMarquee() else Modifier
                )
                folder.fileCount?.let { count ->
                    Text(
                        text = "$count files",
                        style = MaterialTheme.typography.labelSmall,
                        color = if (isFocused) TVSecondary else TVTextSecondary
                    )
                }
            }
        }
    }
}
