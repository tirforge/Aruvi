package com.aruvi.tir.ui.mobile.home

import android.text.format.Formatter
import androidx.activity.compose.BackHandler
import androidx.compose.foundation.ExperimentalFoundationApi
import androidx.compose.foundation.background
import androidx.compose.foundation.combinedClickable
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.LazyRow
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.DriveFileMove
import androidx.compose.material.icons.filled.*
import androidx.compose.material.icons.outlined.*
import androidx.compose.material.icons.automirrored.filled.ExitToApp
import androidx.compose.material3.*
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.pulltorefresh.PullToRefreshBox
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.hilt.navigation.compose.hiltViewModel
import coil.compose.AsyncImage
import coil.request.ImageRequest
import com.aruvi.tir.data.model.FileItem
import com.aruvi.tir.data.model.Folder
import com.aruvi.tir.ui.theme.*
import com.aruvi.tir.ui.mobile.components.*

@OptIn(ExperimentalFoundationApi::class, ExperimentalMaterial3Api::class)
@Composable
fun MobileHomeScreen(
    viewModel: MobileHomeViewModel = hiltViewModel(),
    onPlayFile: (Int) -> Unit,
    onLogout: () -> Unit,
    onSearchClick: () -> Unit
) {
    val uiState by viewModel.uiState.collectAsState()

    // Dialog States
    var showCreateFolderDialog by remember { mutableStateOf(false) }
    var showRenameFileDialog by remember { mutableStateOf<FileItem?>(null) }
    var showDeleteFileDialog by remember { mutableStateOf<FileItem?>(null) }
    var showDeleteFolderDialog by remember { mutableStateOf<Folder?>(null) }
    var showMoveFileDialog by remember { mutableStateOf<FileItem?>(null) }
    var showMoveFolderDialog by remember { mutableStateOf<Folder?>(null) }
    
    var showDeleteSelectedDialog by remember { mutableStateOf(false) }
    var showMoveSelectedDialog by remember { mutableStateOf(false) }
    var showLogoutDialog by remember { mutableStateOf(false) }

    // Back Handler
    BackHandler(enabled = uiState.currentFolderId != null) {
        viewModel.navigateBack()
    }

    PullToRefreshBox(
        isRefreshing = uiState.isLoading,
        onRefresh = { viewModel.refresh() },
        modifier = Modifier
            .fillMaxSize()
            .background(MaterialTheme.colorScheme.background)
    ) {
        LazyColumn(
            modifier = Modifier.fillMaxSize(),
            contentPadding = PaddingValues(top = if (uiState.isMultiSelectMode) 64.dp else 0.dp, bottom = 100.dp) // Space for CAB and bottom nav
        ) {
            // ... (rest of LazyColumn items)
            // 1. Header with Gradient
            item {
                HomeHeader(
                    folderName = uiState.currentFolderName,
                    userName = uiState.userName,
                    onSearchClick = onSearchClick,
                    onLogoutClick = { showLogoutDialog = true }
                )
            }

            // 2. Continue Watching (Only on Root)
            if (uiState.currentFolderId == null && uiState.continueWatching.isNotEmpty()) {
                item {
                    SectionHeader("Continue Watching")
                    LazyRow(
                        contentPadding = PaddingValues(horizontal = 16.dp),
                        horizontalArrangement = Arrangement.spacedBy(16.dp)
                    ) {
                        items(uiState.continueWatching) { file ->
                            ContinueWatchingCard(
                                file = file, 
                                serverUrl = uiState.serverUrl,
                                onClick = onPlayFile
                            )
                        }
                    }
                }
            }

            // 3. Recent Files (Only on Root)
            if (uiState.currentFolderId == null && uiState.recentFiles.isNotEmpty()) {
                item {
                    SectionHeader("Recently Added")
                    LazyRow(
                        contentPadding = PaddingValues(horizontal = 16.dp),
                        horizontalArrangement = Arrangement.spacedBy(16.dp)
                    ) {
                        items(uiState.recentFiles) { file ->
                            RecentFileCard(
                                file = file, 
                                serverUrl = uiState.serverUrl,
                                onClick = onPlayFile
                            )
                        }
                    }
                }
            }

            // 4. File Browser Header
            item {
                Row(
                    modifier = Modifier
                        .fillMaxWidth()
                        .padding(horizontal = 16.dp, vertical = 16.dp),
                    horizontalArrangement = Arrangement.SpaceBetween,
                    verticalAlignment = Alignment.CenterVertically
                ) {
                    Text(
                        text = if (uiState.currentFolderId == null) "Your Files" else uiState.currentFolderName,
                        style = MaterialTheme.typography.titleLarge,
                        color = MaterialTheme.colorScheme.onBackground,
                        fontWeight = FontWeight.Bold
                    )
                    
                    if (!uiState.isMultiSelectMode) {
                        IconButton(
                            onClick = { showCreateFolderDialog = true },
                            modifier = Modifier
                                .background(MaterialTheme.colorScheme.surface, CircleShape)
                                .size(32.dp)
                        ) {
                            Icon(
                                Icons.Default.CreateNewFolder,
                                contentDescription = "New Folder",
                                tint = MaterialTheme.colorScheme.primary,
                                modifier = Modifier.size(18.dp)
                            )
                        }
                    }
                }
            }

            // 5. Folders List
            items(uiState.folders) { folder ->
                FolderCard(
                    folder = folder,
                    isSelected = uiState.selectedFolderIds.contains(folder.id),
                    isMultiSelectMode = uiState.isMultiSelectMode,
                    onClick = { 
                        if (uiState.isMultiSelectMode) {
                            viewModel.toggleSelection(folder.id, true)
                        } else {
                            viewModel.navigateToFolder(it)
                        }
                    },
                    onLongClick = { viewModel.toggleSelection(folder.id, true) },
                    onDelete = { showDeleteFolderDialog = it },
                    onMove = { showMoveFolderDialog = it }
                )
            }

            // 6. Files List
            items(uiState.files) { file ->
                FileCard(
                    file = file,
                    serverUrl = uiState.serverUrl,
                    isSelected = uiState.selectedFileIds.contains(file.id),
                    isMultiSelectMode = uiState.isMultiSelectMode,
                    onClick = { 
                        if (uiState.isMultiSelectMode) {
                            viewModel.toggleSelection(file.id, false)
                        } else {
                            onPlayFile(file.id) 
                        }
                    },
                    onLongClick = { viewModel.toggleSelection(file.id, false) },
                    onRename = { showRenameFileDialog = it },
                    onDelete = { showDeleteFileDialog = it },
                    onMove = { showMoveFileDialog = it },
                    onDownload = { viewModel.downloadFile(it) },
                    onExternalPlayer = { viewModel.openInExternalPlayer(it) },
                    onCopyPublic = { viewModel.copyPublicLink(it) },
                    onRevokePublic = { viewModel.revokePublicLink(it) },
                    onCopyDownload = { viewModel.copyDownloadLink(it) }
                )
            }
            
            // Error State
            if (uiState.error != null) {
                item {
                    Box(
                        modifier = Modifier
                            .fillMaxWidth()
                            .padding(32.dp),
                        contentAlignment = Alignment.Center
                    ) {
                        Column(horizontalAlignment = Alignment.CenterHorizontally) {
                            Text(
                                text = uiState.error ?: "Failed to load content",
                                color = MaterialTheme.colorScheme.error,
                                style = MaterialTheme.typography.bodyMedium
                            )
                            Spacer(modifier = Modifier.height(8.dp))
                            TextButton(onClick = { viewModel.refresh() }) {
                                Text("Retry", color = MaterialTheme.colorScheme.primary)
                            }
                        }
                    }
                }
            }

            // Empty State
            if (uiState.error == null && uiState.folders.isEmpty() && uiState.files.isEmpty() && !uiState.isLoading) {
                item {
                    Box(modifier = Modifier.fillMaxWidth().padding(32.dp), contentAlignment = Alignment.Center) {
                        Text("No files here", color = MaterialTheme.colorScheme.onSurfaceVariant)
                    }
                }
            }
        }

        // Selection Action Bar
        if (uiState.isMultiSelectMode) {
            SelectionActionBar(
                selectedCount = uiState.selectedFileIds.size + uiState.selectedFolderIds.size,
                onClose = { viewModel.clearSelection() },
                onDelete = { showDeleteSelectedDialog = true },
                onMove = { showMoveSelectedDialog = true }
            )
        }
    }
    
    // --- DIALOGS ---
    if (showCreateFolderDialog) {
        InputDialog(
            title = "New Folder",
            onDismiss = { showCreateFolderDialog = false },
            onConfirm = { 
                viewModel.createFolder(it); showCreateFolderDialog = false 
            }
        )
    }
    
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
                    Text("Delete")
                }
            },
            dismissButton = {
                TextButton(onClick = { showDeleteFileDialog = null }) {
                    Text("Cancel")
                }
            }
        )
    }
    
    if (showDeleteFolderDialog != null) {
        AlertDialog(
            onDismissRequest = { showDeleteFolderDialog = null },
            title = { Text("Delete Folder") },
            text = { Text("Are you sure you want to delete '${showDeleteFolderDialog!!.name}'?") },
            confirmButton = {
                TextButton(onClick = {
                    viewModel.deleteFolder(showDeleteFolderDialog!!)
                    showDeleteFolderDialog = null
                }) {
                    Text("Delete")
                }
            },
            dismissButton = {
                TextButton(onClick = { showDeleteFolderDialog = null }) {
                    Text("Cancel")
                }
            }
        )
    }
    
    if (showMoveFileDialog != null) {
        MovePickerDialog(
            title = "Move File",
            currentFolderId = uiState.currentFolderId,
            onDismiss = { showMoveFileDialog = null },
            onConfirm = { targetId ->
                viewModel.moveFile(showMoveFileDialog!!, targetId)
                showMoveFileDialog = null
            },
            loadFolderTree = { viewModel.loadFolderTree() }
        )
    }
    
    if (showMoveFolderDialog != null) {
        MovePickerDialog(
            title = "Move Folder",
            currentFolderId = showMoveFolderDialog!!.id,
            onDismiss = { showMoveFolderDialog = null },
            onConfirm = { targetId ->
                viewModel.moveFolder(showMoveFolderDialog!!, targetId)
                showMoveFolderDialog = null
            },
            loadFolderTree = { viewModel.loadFolderTree() }
        )
    }

    if (showDeleteSelectedDialog) {
        AlertDialog(
            onDismissRequest = { showDeleteSelectedDialog = false },
            title = { Text("Delete Items") },
            text = { Text("Are you sure you want to delete ${uiState.selectedFileIds.size + uiState.selectedFolderIds.size} items?") },
            confirmButton = {
                TextButton(onClick = {
                    viewModel.deleteSelected()
                    showDeleteSelectedDialog = false
                }) {
                    Text("Delete", color = MaterialTheme.colorScheme.error)
                }
            },
            dismissButton = {
                TextButton(onClick = { showDeleteSelectedDialog = false }) {
                    Text("Cancel")
                }
            }
        )
    }

    if (showMoveSelectedDialog) {
        MovePickerDialog(
            title = "Move Items",
            currentFolderId = null,
            onDismiss = { showMoveSelectedDialog = false },
            onConfirm = { targetId ->
                viewModel.moveSelected(targetId)
                showMoveSelectedDialog = false
            },
            loadFolderTree = { viewModel.loadFolderTree() }
        )
    }

    if (showLogoutDialog) {
        AlertDialog(
            onDismissRequest = { showLogoutDialog = false },
            title = { Text("Logout") },
            text = { Text("Are you sure you want to logout?") },
            confirmButton = {
                TextButton(onClick = {
                    showLogoutDialog = false
                    viewModel.logout()
                    onLogout()
                }) {
                    Text("Logout")
                }
            },
            dismissButton = {
                TextButton(onClick = { showLogoutDialog = false }) {
                    Text("Cancel")
                }
            }
        )
    }
}

@Composable
fun SelectionActionBar(
    selectedCount: Int,
    onClose: () -> Unit,
    onDelete: () -> Unit,
    onMove: () -> Unit
) {
    Surface(
        modifier = Modifier
            .fillMaxWidth(),
        color = MaterialTheme.colorScheme.surfaceColorAtElevation(4.dp),
        tonalElevation = 4.dp
    ) {
        Row(
            modifier = Modifier
                .fillMaxWidth()
                .statusBarsPadding()
                .height(64.dp)
                .padding(horizontal = 16.dp),
            verticalAlignment = Alignment.CenterVertically
        ) {
            IconButton(onClick = onClose) {
                Icon(Icons.Default.Close, "Clear selection")
            }
            
            Text(
                text = "$selectedCount selected",
                style = MaterialTheme.typography.titleMedium,
                modifier = Modifier.weight(1f).padding(start = 16.dp)
            )
            
            IconButton(onClick = onMove) {
                Icon(Icons.AutoMirrored.Filled.DriveFileMove, "Move selected")
            }
            
            IconButton(onClick = onDelete) {
                Icon(Icons.Default.Delete, "Delete selected", tint = MaterialTheme.colorScheme.error)
            }
        }
    }
}

@Composable
fun HomeHeader(
    folderName: String,
    userName: String? = null,
    onSearchClick: () -> Unit,
    onLogoutClick: () -> Unit
) {
    // Dynamic greeting based on time of day
    val greeting = remember {
        val hour = java.util.Calendar.getInstance().get(java.util.Calendar.HOUR_OF_DAY)
        when (hour) {
            in 5..11 -> "Good Morning"
            in 12..16 -> "Good Afternoon"
            in 17..20 -> "Good Evening"
            else -> "Good Night"
        }
    }

    Box(
        modifier = Modifier
            .fillMaxWidth()
            .height(180.dp)
            .background(
                Brush.verticalGradient(
                    colors = listOf(
                        MaterialTheme.colorScheme.primary.copy(alpha = 0.8f),
                        MaterialTheme.colorScheme.background
                    )
                )
            )
    ) {
        Column(
            modifier = Modifier
                .align(Alignment.BottomStart)
                .padding(20.dp)
        ) {
            Text(
                text = if (folderName == "Home") {
                    if (userName != null) "$greeting, $userName" else "$greeting,"
                } else folderName,
                style = MaterialTheme.typography.headlineMedium,
                color = MaterialTheme.colorScheme.onBackground,
                fontWeight = FontWeight.Bold
            )
            if (folderName == "Home") {
                Text(
                    text = "Welcome back to Aruvi",
                    style = MaterialTheme.typography.bodyMedium,
                    color = MaterialTheme.colorScheme.onSurfaceVariant
                )
            }
        }
        
        Row(
            modifier = Modifier
                .align(Alignment.TopEnd)
                .padding(16.dp)
                // Add status bar top padding to keep buttons safe, but let background draw behind
                .padding(top = WindowInsets.statusBars.asPaddingValues().calculateTopPadding()),
            horizontalArrangement = Arrangement.spacedBy(12.dp)
        ) {
            IconButton(onClick = onSearchClick) {
                Icon(Icons.Default.Search, "Search", tint = MaterialTheme.colorScheme.onBackground)
            }
            IconButton(onClick = onLogoutClick) {
                Icon(Icons.AutoMirrored.Filled.ExitToApp, "Logout", tint = MaterialTheme.colorScheme.onBackground)
            }
        }
    }
}

@Composable
fun SectionHeader(title: String) {
    Text(
        text = title,
        style = MaterialTheme.typography.titleMedium,
        color = MaterialTheme.colorScheme.onBackground,
        fontWeight = FontWeight.SemiBold,
        modifier = Modifier.padding(horizontal = 16.dp, vertical = 12.dp)
    )
}

@Composable
fun ContinueWatchingCard(file: FileItem, serverUrl: String, onClick: (Int) -> Unit) {
    Card(
        modifier = Modifier
            .width(280.dp)
            .height(160.dp)
            .clickable { onClick(file.id) },
        shape = RoundedCornerShape(12.dp),
        colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surface)
    ) {
        Box(modifier = Modifier.fillMaxSize()) {
            AsyncImage(
                model = ImageRequest.Builder(LocalContext.current)
                    .data("$serverUrl/api/stream/${file.id}/thumbnail")
                    .crossfade(true)
                    .build(),
                contentDescription = null,
                contentScale = ContentScale.Crop,
                modifier = Modifier.fillMaxSize()
            )
            
            // Overlay
            Box(
                modifier = Modifier
                    .fillMaxSize()
                    .background(Color.Black.copy(alpha = 0.3f))
            )
            
            // Play Icon
            Icon(
                Icons.Default.PlayCircle,
                contentDescription = "Play",
                tint = Color.White,
                modifier = Modifier.align(Alignment.Center).size(48.dp)
            )
            
            // Progress Bar (Fake for now or use real data)
            LinearProgressIndicator(
                progress = { 0.5f },
                modifier = Modifier.fillMaxWidth().align(Alignment.BottomCenter),
                color = MaterialTheme.colorScheme.primary,
                trackColor = Color.Transparent
            )
            
            Text(
                text = file.fileName,
                color = Color.White,
                style = MaterialTheme.typography.labelMedium,
                maxLines = 1,
                overflow = TextOverflow.Ellipsis,
                modifier = Modifier.align(Alignment.BottomStart).padding(8.dp).padding(bottom = 8.dp)
            )
        }
    }
}

@Composable
fun RecentFileCard(file: FileItem, serverUrl: String, onClick: (Int) -> Unit) {
    Column(
        modifier = Modifier.width(140.dp).clickable { onClick(file.id) }
    ) {
        Card(
            modifier = Modifier.size(140.dp, 100.dp),
            shape = RoundedCornerShape(12.dp),
            colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surface)
        ) {
              AsyncImage(
                model = ImageRequest.Builder(LocalContext.current)
                    .data("$serverUrl/api/stream/${file.id}/thumbnail")
                    .crossfade(true)
                    .build(),
                contentDescription = null,
                contentScale = ContentScale.Crop,
                modifier = Modifier.fillMaxSize()
            )
        }
        Spacer(modifier = Modifier.height(8.dp))
        Text(
            text = file.fileName,
            color = MaterialTheme.colorScheme.onSurface,
            style = MaterialTheme.typography.bodySmall,
            maxLines = 2,
            overflow = TextOverflow.Ellipsis
        )
    }
}

@OptIn(ExperimentalFoundationApi::class)
@Composable
fun FolderCard(
    folder: Folder, 
    isSelected: Boolean,
    isMultiSelectMode: Boolean,
    onClick: (Folder) -> Unit, 
    onLongClick: () -> Unit,
    onDelete: (Folder) -> Unit, 
    onMove: (Folder) -> Unit
) {
     GlassmorphismSurface(
        modifier = Modifier
            .fillMaxWidth()
            .padding(horizontal = 16.dp, vertical = 4.dp)
            .height(72.dp)
            .combinedClickable(
                onClick = { onClick(folder) },
                onLongClick = onLongClick
            ),
        borderColor = if (isSelected) MaterialTheme.colorScheme.primary else Color.White.copy(alpha = 0.1f)
    ) {
        Row(
            modifier = Modifier.padding(12.dp),
            verticalAlignment = Alignment.CenterVertically
        ) {
            Box(
                modifier = Modifier
                    .size(48.dp)
                    .background(
                        if (isSelected) MaterialTheme.colorScheme.primary.copy(alpha = 0.1f) 
                        else MaterialTheme.colorScheme.primary.copy(alpha = 0.2f), 
                        RoundedCornerShape(8.dp)
                    ),
                contentAlignment = Alignment.Center
            ) {
                if (isSelected) {
                    Icon(Icons.Default.CheckCircle, "Selected", tint = MaterialTheme.colorScheme.primary)
                } else {
                    Icon(Icons.Default.Folder, "Folder", tint = MaterialTheme.colorScheme.primary)
                }
            }
            
            Spacer(modifier = Modifier.width(16.dp))
            
            Column(modifier = Modifier.weight(1f)) {
                Text(
                    text = folder.name,
                    color = MaterialTheme.colorScheme.onSurface,
                    style = MaterialTheme.typography.titleSmall
                )
                Text(
                    text = "Folder",
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    style = MaterialTheme.typography.bodySmall
                )
            }
            
            if (!isMultiSelectMode) {
                FolderOptionsButton(onDelete = { onDelete(folder) }, onMove = { onMove(folder) })
            }
        }
    }
}

@OptIn(ExperimentalFoundationApi::class)
@Composable
fun FileCard(
    file: FileItem, 
    serverUrl: String,
    isSelected: Boolean,
    isMultiSelectMode: Boolean,
    onClick: () -> Unit, 
    onLongClick: () -> Unit,
    onRename: (FileItem) -> Unit,
    onDelete: (FileItem) -> Unit,
    onMove: (FileItem) -> Unit,
    onDownload: (FileItem) -> Unit,
    onExternalPlayer: (FileItem) -> Unit,
    onCopyPublic: (FileItem) -> Unit,
    onRevokePublic: (FileItem) -> Unit,
    onCopyDownload: (FileItem) -> Unit
) {
     GlassmorphismSurface(
        modifier = Modifier
            .fillMaxWidth()
            .padding(horizontal = 16.dp, vertical = 4.dp)
            .height(72.dp)
            .combinedClickable(
                onClick = onClick,
                onLongClick = onLongClick
            ),
        borderColor = if (isSelected) MaterialTheme.colorScheme.primary else Color.White.copy(alpha = 0.1f)
    ) {
        Row(
            modifier = Modifier.padding(12.dp),
            verticalAlignment = Alignment.CenterVertically
        ) {
            Box(
                modifier = Modifier
                    .size(48.dp)
                    .background(MaterialTheme.colorScheme.surface, RoundedCornerShape(8.dp)),
                contentAlignment = Alignment.Center
            ) {
                if (isSelected) {
                    Icon(Icons.Default.CheckCircle, "Selected", tint = MaterialTheme.colorScheme.primary)
                } else {
                    AsyncImage(
                        model = ImageRequest.Builder(LocalContext.current)
                            .data("$serverUrl/api/stream/${file.id}/thumbnail")
                            .crossfade(true)
                            .build(),
                        contentDescription = null,
                        contentScale = ContentScale.Crop,
                        modifier = Modifier.fillMaxSize().clip(RoundedCornerShape(8.dp))
                    )
                }
            }
            
            Spacer(modifier = Modifier.width(16.dp))
            
            Column(modifier = Modifier.weight(1f)) {
                Text(
                    text = file.fileName,
                    color = MaterialTheme.colorScheme.onSurface,
                    style = MaterialTheme.typography.titleSmall,
                    maxLines = 1,
                    overflow = TextOverflow.Ellipsis
                )
                Text(
                    text = Formatter.formatFileSize(LocalContext.current, file.fileSize),
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    style = MaterialTheme.typography.bodySmall
                )
            }
            
            if (!isMultiSelectMode) {
                FileOptionsButton(
                    file = file,
                    onRename = { onRename(file) },
                    onDelete = { onDelete(file) },
                    onMove = { onMove(file) },
                    onDownload = { onDownload(file) },
                    onExternalPlayer = { onExternalPlayer(file) },
                    onCopyPublic = { onCopyPublic(file) },
                    onRevokePublic = { onRevokePublic(file) },
                    onCopyDownload = { onCopyDownload(file) }
                )
            }
        }
    }
}
