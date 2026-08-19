package com.aruvi.tir.ui.mobile.search

import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.grid.GridCells
import androidx.compose.foundation.lazy.grid.LazyVerticalGrid
import androidx.compose.foundation.lazy.grid.items
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.KeyboardActions
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Close
import androidx.compose.material.icons.filled.Search
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.ExperimentalComposeUiApi
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.LocalSoftwareKeyboardController
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.unit.dp
import androidx.hilt.navigation.compose.hiltViewModel
import com.aruvi.tir.ui.search.SearchViewModel
import com.aruvi.tir.ui.theme.*
import com.aruvi.tir.ui.mobile.components.*
import com.aruvi.tir.data.model.FileItem
import android.util.Log

@OptIn(ExperimentalMaterial3Api::class, ExperimentalComposeUiApi::class)
@Composable
fun MobileSearchScreen(
    viewModel: SearchViewModel = hiltViewModel(),
    onPlayFile: (Int) -> Unit,
    onGoToFolder: (Int, String) -> Unit
) {
    val uiState by viewModel.uiState.collectAsState()
    val keyboardController = LocalSoftwareKeyboardController.current

    var showRenameFileDialog by remember { mutableStateOf<FileItem?>(null) }
    var showDeleteFileDialog by remember { mutableStateOf<FileItem?>(null) }
    var showMoveFileDialog by remember { mutableStateOf<FileItem?>(null) }

    Column(
        modifier = Modifier
            .fillMaxSize()
            .background(MobileBackground)
    ) {
        // Search Header
        Box(
            modifier = Modifier
                .fillMaxWidth()
                .background(
                    Brush.verticalGradient(
                        colors = listOf(MobileHeaderGradientStart, MobileBackground)
                    )
                )
                .padding(16.dp)
                .statusBarsPadding()
        ) {
            GlassmorphismSurface(
                modifier = Modifier
                    .fillMaxWidth()
                    .height(56.dp)
            ) {
                Row(
                    modifier = Modifier
                        .fillMaxSize()
                        .padding(horizontal = 16.dp),
                    verticalAlignment = Alignment.CenterVertically
                ) {
                    Icon(
                        Icons.Default.Search,
                        contentDescription = "Search",
                        tint = MobileTextSecondary
                    )
                    
                    Spacer(modifier = Modifier.width(12.dp))
                    
                TextField(
            value = uiState.query,
            onValueChange = { 
                Log.d("MobileSearchScreen", "Query changed: $it")
                viewModel.onQueryChange(it) 
            },
            placeholder = { Text("Search files...", color = MobileTextSecondary) },
            colors = TextFieldDefaults.colors(
                focusedContainerColor = Color.Transparent,
                unfocusedContainerColor = Color.Transparent,
                disabledContainerColor = Color.Transparent,
                focusedIndicatorColor = Color.Transparent,
                unfocusedIndicatorColor = Color.Transparent
            ),
            singleLine = true,
            keyboardOptions = KeyboardOptions(imeAction = ImeAction.Search),
            keyboardActions = KeyboardActions(onSearch = { keyboardController?.hide() }),
            modifier = Modifier.weight(1f),
            textStyle = MaterialTheme.typography.bodyLarge.copy(color = MobileTextPrimary)
        )
                    
                    if (uiState.query.isNotEmpty()) {
                        IconButton(onClick = { viewModel.onQueryChange("") }) {
                            Icon(Icons.Default.Close, "Clear", tint = MobileTextSecondary)
                        }
                    }
                }
            }
        }

        if (uiState.isSearching) {
            Box(modifier = Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
                CircularProgressIndicator(color = MobilePrimary)
            }
        } else if (uiState.error != null) {
            Box(modifier = Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
                Text(uiState.error!!, color = MaterialTheme.colorScheme.error)
            }
        } else if (uiState.results.isEmpty()) {
             Box(modifier = Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
                if (uiState.query.isNotEmpty()) {
                    Text("No results found for \"${uiState.query}\"", color = MobileTextSecondary)
                } else {
                    Text("Type to search", color = MobileTextSecondary)
                }
            }
        } else {
            Log.d("MobileSearchScreen", "Showing ${uiState.results.size} results")
            LazyVerticalGrid(
                columns = GridCells.Adaptive(minSize = 150.dp),
                contentPadding = PaddingValues(16.dp),
                verticalArrangement = Arrangement.spacedBy(16.dp),
                horizontalArrangement = Arrangement.spacedBy(16.dp),
                modifier = Modifier.fillMaxSize()
            ) {
                items(uiState.results) { file ->
                     SearchFileCard(
                        file = file, 
                        serverUrl = uiState.serverUrl, 
                        onClick = onPlayFile,
                        onRename = { showRenameFileDialog = it },
                        onDelete = { showDeleteFileDialog = it },
                        onMove = { showMoveFileDialog = it },
                        onDownload = { viewModel.downloadFile(it) },
                        onExternalPlayer = { viewModel.openInExternalPlayer(it) },
                        onCopyPublic = { viewModel.copyPublicLink(it) },
                        onRevokePublic = { viewModel.revokePublicLink(it) },
                        onCopyDownload = { viewModel.copyDownloadLink(it) },
                        onGoToFolder = { 
                            // folderId might be null for root files, but user wants to 'go to folder'
                            // Let's assume folderName is "Home" if folderId is null
                            onGoToFolder(file.folderId ?: -1, "Files") 
                        }
                    )
                }
            }
        }
    }

    // --- Dialogs ---
    if (showRenameFileDialog != null) {
        InputDialog(
            title = "Rename File",
            initialValue = showRenameFileDialog!!.fileName,
            onDismiss = { showRenameFileDialog = null },
            onConfirm = { newName ->
                viewModel.renameFile(showRenameFileDialog!!, newName)
                showRenameFileDialog = null
            }
        )
    }

    if (showDeleteFileDialog != null) {
        AlertDialog(
            onDismissRequest = { showDeleteFileDialog = null },
            title = { Text("Delete File") },
            text = { Text("Are you sure you want to delete '${showDeleteFileDialog!!.fileName}'?") },
            confirmButton = {
                TextButton(onClick = {
                    viewModel.deleteFile(showDeleteFileDialog!!)
                    showDeleteFileDialog = null
                }) {
                    Text("Delete", color = MaterialTheme.colorScheme.error)
                }
            },
            dismissButton = {
                TextButton(onClick = { showDeleteFileDialog = null }) {
                    Text("Cancel")
                }
            }
        )
    }

    if (showMoveFileDialog != null) {
        MovePickerDialog(
            title = "Move File",
            currentFolderId = showMoveFileDialog!!.folderId,
            onDismiss = { showMoveFileDialog = null },
            onConfirm = { targetId ->
                viewModel.moveFile(showMoveFileDialog!!, targetId)
                showMoveFileDialog = null
            },
            loadFolderTree = { viewModel.loadFolderTree() }
        )
    }
}

@Composable
fun SearchFileCard(
    file: com.aruvi.tir.data.model.FileItem,
    serverUrl: String,
    onClick: (Int) -> Unit,
    onRename: (FileItem) -> Unit,
    onDelete: (FileItem) -> Unit,
    onMove: (FileItem) -> Unit,
    onDownload: (FileItem) -> Unit,
    onExternalPlayer: (FileItem) -> Unit,
    onCopyPublic: (FileItem) -> Unit,
    onRevokePublic: (FileItem) -> Unit,
    onCopyDownload: (FileItem) -> Unit,
    onGoToFolder: () -> Unit
) {
    Column(
        modifier = Modifier
            .fillMaxWidth()
            .clickable { onClick(file.id) }
    ) {
        Box(modifier = Modifier.fillMaxWidth()) {
            Card(
                modifier = Modifier
                    .fillMaxWidth()
                    .aspectRatio(16f / 9f),
                shape = RoundedCornerShape(12.dp),
                colors = CardDefaults.cardColors(containerColor = MobileSurface)
            ) {
                 coil.compose.AsyncImage(
                    model = coil.request.ImageRequest.Builder(LocalContext.current)
                        .data("$serverUrl/api/stream/${file.id}/thumbnail")
                        .crossfade(true)
                        .build(),
                    contentDescription = null,
                    contentScale = androidx.compose.ui.layout.ContentScale.Crop,
                    modifier = Modifier.fillMaxSize()
                )
            }
            
            // Context Menu Overlay
            Box(
                modifier = Modifier
                    .align(Alignment.TopEnd)
                    .padding(4.dp)
            ) {
                FileOptionsButton(
                    file = file,
                    onRename = { onRename(file) },
                    onDelete = { onDelete(file) },
                    onMove = { onMove(file) },
                    onDownload = { onDownload(file) },
                    onExternalPlayer = { onExternalPlayer(file) },
                    onCopyPublic = { onCopyPublic(file) },
                    onRevokePublic = { onRevokePublic(file) },
                    onCopyDownload = { onCopyDownload(file) },
                    onGoToFolder = onGoToFolder
                )
            }
        }
        
        Spacer(modifier = Modifier.height(8.dp))
        Text(
            text = file.fileName,
            color = MobileTextPrimary,
            style = MaterialTheme.typography.bodyMedium,
            maxLines = 2,
            overflow = androidx.compose.ui.text.style.TextOverflow.Ellipsis,
            modifier = Modifier.padding(horizontal = 4.dp)
        )
    }
}
