package com.aruvi.tir.ui.browse

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.*
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.filled.ArrowBack
import androidx.compose.material.icons.filled.Folder
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.focus.FocusRequester
import androidx.compose.ui.focus.focusRequester
import androidx.compose.ui.unit.dp
import androidx.hilt.navigation.compose.hiltViewModel
import androidx.tv.foundation.lazy.grid.TvGridCells
import androidx.tv.foundation.lazy.grid.TvLazyVerticalGrid
import androidx.tv.foundation.lazy.grid.items
import androidx.tv.foundation.lazy.grid.rememberTvLazyGridState
import com.aruvi.tir.ui.components.*
import com.aruvi.tir.ui.theme.*

/**
 * Folder browsing screen showing subfolders and files.
 */
@Composable
fun FolderScreen(
    onFileClick: (Int) -> Unit,
    onFolderClick: (Int) -> Unit,
    onBackClick: () -> Unit,
    viewModel: FolderViewModel = hiltViewModel()
) {
    val uiState by viewModel.uiState.collectAsState()
    val focusRequester = remember { FocusRequester() }

    Box(
        modifier = Modifier
            .fillMaxSize()
            .background(TVBackground)
    ) {
        when {
            uiState.isLoading -> {
                LoadingIndicator(message = "Loading folder...")
            }

            uiState.error != null -> {
                ErrorState(
                    message = uiState.error!!,
                    onRetry = { viewModel.refresh() }
                )
            }

            else -> {
                Column(modifier = Modifier.fillMaxSize()) {
                    // Header
                    FolderHeader(
                        folderName = uiState.folder?.name ?: "Folder",
                        parentPath = uiState.parentPath,
                        onBackClick = onBackClick
                    )

                    // Content grid (state is saveable so scroll+focus survive back nav)
                    TvLazyVerticalGrid(
                        columns = TvGridCells.Adaptive(200.dp),
                        state = rememberTvLazyGridState(),
                        modifier = Modifier
                            .fillMaxSize()
                            .focusRequester(focusRequester),
                        contentPadding = PaddingValues(48.dp),
                        horizontalArrangement = Arrangement.spacedBy(16.dp),
                        verticalArrangement = Arrangement.spacedBy(16.dp)
                    ) {
                        // Subfolders first
                        items(uiState.subfolders, key = { "folder_${it.id}" }) { folder ->
                            FolderCard(
                                folder = folder,
                                onClick = { onFolderClick(folder.id) }
                            )
                        }

                        // Then files
                        items(uiState.files, key = { "file_${it.id}" }) { file ->
                            val thumbnailUrl = "${uiState.serverUrl}/api/stream/${file.id}/thumbnail"
                            MediaCard(
                                file = file,
                                thumbnailUrl = thumbnailUrl,
                                onClick = { onFileClick(file.id) }
                            )
                        }
                    }

                    // Empty state
                    if (uiState.subfolders.isEmpty() && uiState.files.isEmpty()) {
                        EmptyState(
                            title = "This folder is empty",
                            subtitle = "No files or subfolders here"
                        )
                    }
                }
            }
        }
    }

    // Request focus with safety
    LaunchedEffect(uiState.isLoading) {
        if (!uiState.isLoading) {
            // Small delay to ensure focusRequester is attached
            kotlinx.coroutines.delay(100)
            try {
                focusRequester.requestFocus()
            } catch (e: IllegalStateException) {
                // FocusRequester not yet attached, ignore
            }
        }
    }
}

/**
 * Folder header with back button and breadcrumb path.
 */
@Composable
private fun FolderHeader(
    folderName: String,
    parentPath: List<com.aruvi.tir.data.model.Folder>,
    onBackClick: () -> Unit
) {
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .padding(horizontal = 48.dp, vertical = 24.dp),
        verticalAlignment = Alignment.CenterVertically
    ) {
        // Back button
        TVIconButton(
            icon = {
                Icon(
                    imageVector = Icons.AutoMirrored.Filled.ArrowBack,
                    contentDescription = "Back",
                    tint = TVTextPrimary,
                    modifier = Modifier.size(24.dp)
                )
            },
            onClick = onBackClick,
            modifier = Modifier.size(48.dp)
        )

        Spacer(modifier = Modifier.width(16.dp))

        // Folder icon
        Icon(
            imageVector = Icons.Default.Folder,
            contentDescription = null,
            tint = TVSecondary,
            modifier = Modifier.size(32.dp)
        )

        Spacer(modifier = Modifier.width(12.dp))

        // Breadcrumb path
        Row(verticalAlignment = Alignment.CenterVertically) {
            if (parentPath.isNotEmpty()) {
                parentPath.forEach { folder ->
                    Text(
                        text = folder.name,
                        style = MaterialTheme.typography.bodyMedium,
                        color = TVTextSecondary
                    )
                    Text(
                        text = " / ",
                        style = MaterialTheme.typography.bodyMedium,
                        color = TVTextSecondary
                    )
                }
            }
            Text(
                text = folderName,
                style = MaterialTheme.typography.headlineSmall,
                color = TVTextPrimary
            )
        }
    }
}
