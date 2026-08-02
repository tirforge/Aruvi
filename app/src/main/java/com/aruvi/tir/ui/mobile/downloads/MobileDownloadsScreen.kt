package com.aruvi.tir.ui.mobile.downloads

import android.text.format.Formatter
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Delete
import androidx.compose.material.icons.filled.Download
import androidx.compose.material.icons.filled.DownloadDone
import androidx.compose.material.icons.filled.Error
import androidx.compose.material.icons.filled.Folder
import androidx.compose.material.icons.filled.Pause
import androidx.compose.material.icons.filled.PlayArrow
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.hilt.navigation.compose.hiltViewModel
import com.aruvi.tir.download.DownloadStatus
import com.aruvi.tir.ui.theme.*

@Composable
fun MobileDownloadsScreen(
    viewModel: DownloadsViewModel = hiltViewModel()
) {
    val uiState by viewModel.uiState.collectAsState()
    var deleteId by remember { mutableStateOf<Long?>(null) }

    if (deleteId != null) {
        AlertDialog(
            onDismissRequest = { deleteId = null },
            title = { Text("Delete Download") },
            text = { Text("Are you sure you want to delete this downloaded file?") },
            confirmButton = {
                TextButton(onClick = {
                    deleteId?.let { viewModel.deleteDownload(it) }
                    deleteId = null
                }) {
                    Text("Delete", color = MaterialTheme.colorScheme.error)
                }
            },
            dismissButton = {
                TextButton(onClick = { deleteId = null }) {
                    Text("Cancel")
                }
            }
        )
    }

    Column(
        modifier = Modifier
            .fillMaxSize()
            .background(MaterialTheme.colorScheme.background)
    ) {
        // Header
        Box(
            modifier = Modifier
                .fillMaxWidth()
                .background(
                    Brush.verticalGradient(
                        colors = listOf(MaterialTheme.colorScheme.surfaceVariant, MaterialTheme.colorScheme.background)
                    )
                )
                .padding(16.dp)
                .statusBarsPadding()
        ) {
            Text(
                text = "Downloads",
                style = MaterialTheme.typography.headlineMedium,
                color = MaterialTheme.colorScheme.onBackground
            )
        }

        if (uiState.downloads.isEmpty()) {
            Box(modifier = Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
                Column(horizontalAlignment = Alignment.CenterHorizontally) {
                    Icon(
                        Icons.Default.Download,
                        contentDescription = null,
                        modifier = Modifier.size(64.dp),
                        tint = MaterialTheme.colorScheme.onSurfaceVariant.copy(alpha = 0.5f)
                    )
                    Spacer(modifier = Modifier.height(16.dp))
                    Text("No downloads yet", color = MaterialTheme.colorScheme.onSurfaceVariant)
                }
            }
        } else {
            LazyColumn(
                contentPadding = PaddingValues(16.dp),
                verticalArrangement = Arrangement.spacedBy(16.dp)
            ) {
                items(uiState.downloads, key = { it.id }) { item ->
                    DownloadItemCard(
                        item = item,
                        onDelete = { deleteId = item.id },
                        onPause = { viewModel.pauseDownload(item.id) },
                        onResume = { viewModel.resumeDownload(item.id) }
                    )
                }
            }
        }
    }
}

@Composable
fun DownloadItemCard(
    item: DownloadItem,
    onDelete: () -> Unit,
    onPause: () -> Unit,
    onResume: () -> Unit
) {
    val context = LocalContext.current
    
    GlassmorphismSurface(
        modifier = Modifier.fillMaxWidth()
    ) {
        Row(
            modifier = Modifier
                .padding(16.dp)
                .fillMaxWidth(),
            verticalAlignment = Alignment.CenterVertically
        ) {
            // Icon based on status
            val icon = when (item.status) {
                DownloadStatus.COMPLETED -> Icons.Default.DownloadDone
                DownloadStatus.FAILED -> Icons.Default.Error
                DownloadStatus.PAUSED -> Icons.Default.Pause
                DownloadStatus.RUNNING -> Icons.Default.Download
                DownloadStatus.PENDING -> Icons.Default.Download
                DownloadStatus.CANCELLED -> Icons.Default.Error
            }
            
            val iconColor = when (item.status) {
                DownloadStatus.COMPLETED -> MaterialTheme.colorScheme.primary
                DownloadStatus.FAILED, DownloadStatus.CANCELLED -> MaterialTheme.colorScheme.error
                DownloadStatus.PAUSED -> MobilePrimary
                else -> MaterialTheme.colorScheme.onSurfaceVariant
            }

            Icon(icon, contentDescription = null, tint = iconColor, modifier = Modifier.size(32.dp))
            
            Spacer(modifier = Modifier.width(16.dp))
            
            Column(modifier = Modifier.weight(1f)) {
                Text(
                    text = item.title,
                    color = MaterialTheme.colorScheme.onBackground,
                    style = MaterialTheme.typography.titleSmall,
                    maxLines = 1,
                    overflow = TextOverflow.Ellipsis
                )
                Spacer(modifier = Modifier.height(4.dp))
                
                // Progress & Speed for running downloads
                if (item.status == DownloadStatus.RUNNING) {
                     val progress = if (item.totalSize > 0) item.downloadedSize.toFloat() / item.totalSize else 0f
                     LinearProgressIndicator(
                         progress = { progress },
                         modifier = Modifier.fillMaxWidth().height(4.dp),
                         color = MobilePrimary,
                         trackColor = MaterialTheme.colorScheme.surfaceVariant
                     )
                     Spacer(modifier = Modifier.height(4.dp))
                     
                     Row(
                         modifier = Modifier.fillMaxWidth(),
                         horizontalArrangement = Arrangement.SpaceBetween
                     ) {
                         Text(
                             text = "${(progress * 100).toInt()}% • ${Formatter.formatFileSize(context, item.speed)}/s",
                             style = MaterialTheme.typography.labelSmall,
                             color = MobilePrimary
                         )
                         Text(
                             text = "${Formatter.formatFileSize(context, item.downloadedSize)} / ${Formatter.formatFileSize(context, item.totalSize)}",
                             style = MaterialTheme.typography.labelSmall,
                             color = Color.White.copy(alpha = 0.5f)
                         )
                     }
                } else if (item.status == DownloadStatus.PAUSED && item.totalSize > 0) {
                    // Show progress bar for paused items
                    val progress = item.downloadedSize.toFloat() / item.totalSize
                    LinearProgressIndicator(
                        progress = { progress },
                        modifier = Modifier.fillMaxWidth().height(4.dp),
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                        trackColor = MaterialTheme.colorScheme.surfaceVariant
                    )
                    Spacer(modifier = Modifier.height(4.dp))
                    Text(
                        text = "Paused • ${(progress * 100).toInt()}% • ${Formatter.formatFileSize(context, item.downloadedSize)} / ${Formatter.formatFileSize(context, item.totalSize)}",
                        style = MaterialTheme.typography.labelSmall,
                        color = MobilePrimary
                    )
                } else {
                    Text(
                        text = when(item.status) {
                            DownloadStatus.PENDING -> "Pending"
                            DownloadStatus.PAUSED -> "Paused"
                            DownloadStatus.COMPLETED -> "Completed • ${Formatter.formatFileSize(context, item.totalSize)}"
                            DownloadStatus.FAILED -> "Failed"
                            DownloadStatus.CANCELLED -> "Cancelled"
                            else -> ""
                        },
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                        style = MaterialTheme.typography.bodySmall
                    )
                }
            }

            // Pause button for running/pending downloads
            if (item.status == DownloadStatus.RUNNING || item.status == DownloadStatus.PENDING) {
                IconButton(onClick = onPause) {
                    Icon(Icons.Default.Pause, "Pause", tint = MaterialTheme.colorScheme.primary)
                }
            }

            // Resume button for paused/failed downloads
            if (item.status == DownloadStatus.PAUSED || item.status == DownloadStatus.FAILED) {
                IconButton(onClick = onResume) {
                    Icon(Icons.Default.PlayArrow, "Resume", tint = MaterialTheme.colorScheme.primary)
                }
            }

            // Open file button for completed downloads
            if (item.status == DownloadStatus.COMPLETED) {
                IconButton(onClick = {
                    try {
                        val path = item.localPath
                        val contentUri = if (path != null && path.startsWith("content://")) {
                            android.net.Uri.parse(path)
                        } else if (path != null) {
                            val file = java.io.File(path)
                            if (file.exists()) {
                                androidx.core.content.FileProvider.getUriForFile(
                                    context,
                                    "${context.packageName}.provider",
                                    file
                                )
                            } else {
                                null
                            }
                        } else {
                            null
                        }

                        if (contentUri != null) {
                            val intent = android.content.Intent(android.content.Intent.ACTION_VIEW).apply {
                                setDataAndType(contentUri, item.mimeType ?: "video/*")
                                addFlags(android.content.Intent.FLAG_GRANT_READ_URI_PERMISSION)
                            }
                            context.startActivity(android.content.Intent.createChooser(intent, "Open with"))
                        } else {
                            android.widget.Toast.makeText(context, "File not found", android.widget.Toast.LENGTH_SHORT).show()
                        }
                    } catch (e: Exception) {
                        android.widget.Toast.makeText(context, "Cannot open file: ${e.message}", android.widget.Toast.LENGTH_SHORT).show()
                    }
                }) {
                    Icon(
                        imageVector = Icons.Default.Folder,
                        contentDescription = "Open File",
                        tint = MaterialTheme.colorScheme.primary
                    )
                }
            }
            
            IconButton(onClick = onDelete) {
                Icon(Icons.Default.Delete, "Delete", tint = MaterialTheme.colorScheme.onSurfaceVariant)
            }
        }
    }
}
