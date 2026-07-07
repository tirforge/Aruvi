package com.aruvi.tir.ui.mobile.home

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.aruvi.tir.data.model.FileItem
import com.aruvi.tir.data.model.Folder
import com.aruvi.tir.data.model.FolderWithChildren
import com.aruvi.tir.data.repository.FilesRepository
import com.aruvi.tir.data.repository.FoldersRepository
import dagger.hilt.android.lifecycle.HiltViewModel
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch
import javax.inject.Inject
import android.content.Context
import android.content.Intent
import android.net.Uri
import android.content.ClipboardManager
import android.content.ClipData
import android.widget.Toast

data class MobileHomeUiState(
    val currentFolderId: Int? = null,
    val currentFolderName: String = "Home",
    val folders: List<Folder> = emptyList(),
    val files: List<FileItem> = emptyList(),
    val continueWatching: List<FileItem> = emptyList(),
    val recentFiles: List<FileItem> = emptyList(),
    val serverUrl: String = "",
    val isLoading: Boolean = false,
    val error: String? = null,
    val parentFolderId: Int? = null,
    val selectedFileIds: Set<Int> = emptySet(),
    val selectedFolderIds: Set<Int> = emptySet(),
    val userName: String? = null
) {
    val isMultiSelectMode: Boolean get() = selectedFileIds.isNotEmpty() || selectedFolderIds.isNotEmpty()
}

@HiltViewModel
class MobileHomeViewModel @Inject constructor(
    @dagger.hilt.android.qualifiers.ApplicationContext private val context: android.content.Context,
    private val filesRepository: FilesRepository,
    private val foldersRepository: FoldersRepository,
    private val settingsRepository: com.aruvi.tir.data.repository.SettingsRepository,
    private val authRepository: com.aruvi.tir.data.repository.AuthRepository,
    private val fileDownloader: com.aruvi.tir.download.FileDownloader,
    savedStateHandle: androidx.lifecycle.SavedStateHandle
) : ViewModel() {

    private val _uiState = MutableStateFlow(MobileHomeUiState())
    val uiState: StateFlow<MobileHomeUiState> = _uiState.asStateFlow()

    // Navigation stack for folders
    private val folderStack = ArrayDeque<Pair<Int?, String>>()

    init {
        // Observe folderId and folderName from SavedStateHandle to handle deep links and navigation arguments
        viewModelScope.launch {
            savedStateHandle.getStateFlow<Int?>("folderId", null).collect { folderId ->
                val id = if (folderId == -1) null else folderId
                val name = savedStateHandle.get<String>("folderName") ?: "Home"
                
                // If the folderId changed and it's not the current one, load it
                if (id != _uiState.value.currentFolderId) {
                    loadContent(id, name)
                }
            }
        }
        
        // Initial load for things that don't depend on folderId (like serverUrl)
        refresh()

        // Load user name
        viewModelScope.launch {
            authRepository.userName.collect { name ->
                _uiState.value = _uiState.value.copy(userName = name)
            }
        }
    }

    fun loadContent(folderId: Int? = null, folderName: String = "Home") {
        viewModelScope.launch {
            _uiState.value = _uiState.value.copy(
                isLoading = true,
                currentFolderId = folderId,
                currentFolderName = folderName,
                error = null
            )

            // Fetch server URL first if empty
            if (_uiState.value.serverUrl.isEmpty()) {
                val url = settingsRepository.getServerUrl()
                _uiState.value = _uiState.value.copy(serverUrl = url)
            }
            
            if (folderId == null) {
                // Root
                val foldersResult = foldersRepository.getFolders(parentId = null)
                val filesResult = filesRepository.getFiles(folderId = null)
                
                // Fetch extra home content
                val continueResult = filesRepository.getContinueWatching()
                val recentResult = filesRepository.getRecentFiles()

                if (foldersResult.isSuccess && filesResult.isSuccess) {
                    val allFiles = filesResult.getOrNull()?.items ?: emptyList()
                    // Filter: Only show files that have NO folderId (truly in root)
                    val rootFiles = allFiles.filter { it.folderId == null }

                    _uiState.value = _uiState.value.copy(
                        isLoading = false,
                        folders = foldersResult.getOrNull() ?: emptyList(),
                        files = rootFiles,
                        continueWatching = continueResult.getOrNull() ?: emptyList(),
                        recentFiles = recentResult.getOrNull() ?: emptyList()
                    )
                } else {
                    _uiState.value = _uiState.value.copy(
                        isLoading = false,
                        error = "Failed to load content"
                    )
                }
            } else {
                // Subfolder
                val folderResult = foldersRepository.getFolder(folderId)
                if (folderResult.isSuccess) {
                    val detail = folderResult.getOrThrow()
                    _uiState.value = _uiState.value.copy(
                        isLoading = false,
                        folders = detail.subfolders ?: emptyList(),
                        files = detail.files ?: emptyList()
                    )
                } else {
                     _uiState.value = _uiState.value.copy(
                        isLoading = false,
                        error = "Failed to load folder"
                    )
                }
            }
        }
    }

    fun navigateToFolder(folder: Folder) {
        folderStack.addLast(_uiState.value.currentFolderId to _uiState.value.currentFolderName)
        loadContent(folder.id, folder.name)
    }

    fun navigateBack(): Boolean {
        if (folderStack.isEmpty()) return false
        val (prevId, prevName) = folderStack.removeLast()
        loadContent(prevId, prevName)
        return true
    }

    fun refresh() {
        loadContent(_uiState.value.currentFolderId, _uiState.value.currentFolderName)
    }

    suspend fun loadFolderTree(): List<FolderWithChildren> =
        foldersRepository.getFolderTree().getOrNull() ?: emptyList()

    // Selection management
    fun toggleSelection(id: Int, isFolder: Boolean) {
        val currentState = _uiState.value
        if (isFolder) {
            val newSelected = if (currentState.selectedFolderIds.contains(id)) {
                currentState.selectedFolderIds - id
            } else {
                currentState.selectedFolderIds + id
            }
            _uiState.value = currentState.copy(selectedFolderIds = newSelected)
        } else {
            val newSelected = if (currentState.selectedFileIds.contains(id)) {
                currentState.selectedFileIds - id
            } else {
                currentState.selectedFileIds + id
            }
            _uiState.value = currentState.copy(selectedFileIds = newSelected)
        }
    }

    fun clearSelection() {
        _uiState.value = _uiState.value.copy(
            selectedFileIds = emptySet(),
            selectedFolderIds = emptySet()
        )
    }

    fun deleteSelected() {
        val currentState = _uiState.value
        viewModelScope.launch {
            // Delete folders first
            currentState.selectedFolderIds.forEach { id ->
                foldersRepository.deleteFolder(id)
            }
            // Delete files
            currentState.selectedFileIds.forEach { id ->
                filesRepository.deleteFile(id)
            }
            clearSelection()
            refresh()
        }
    }

    fun moveSelected(targetFolderId: Int?) {
        val currentState = _uiState.value
        viewModelScope.launch {
            // Move folders
            currentState.selectedFolderIds.forEach { id ->
                foldersRepository.updateFolder(id, parentId = targetFolderId)
            }
            // Move files
            currentState.selectedFileIds.forEach { id ->
                filesRepository.updateFile(id, folderId = targetFolderId)
            }
            clearSelection()
            refresh()
        }
    }
    
    // File Operations
    fun deleteFile(file: FileItem) {
        viewModelScope.launch {
            filesRepository.deleteFile(file.id)
            refresh()
        }
    }
    
     fun deleteFolder(folder: Folder) {
        viewModelScope.launch {
            foldersRepository.deleteFolder(folder.id)
            refresh()
        }
    }
    
    fun createFolder(name: String) {
         viewModelScope.launch {
            foldersRepository.createFolder(name, _uiState.value.currentFolderId)
            refresh()
        }
    }
    
    fun renameFile(file: FileItem, newName: String) {
         viewModelScope.launch {
            filesRepository.updateFile(file.id, name = newName)
            refresh()
        }
    }
    
    fun moveFile(file: FileItem, targetFolderId: Int?) {
        viewModelScope.launch {
            filesRepository.updateFile(file.id, folderId = targetFolderId)
            refresh()
        }
    }

    fun moveFolder(folder: Folder, targetFolderId: Int?) {
        viewModelScope.launch {
            foldersRepository.updateFolder(folder.id, parentId = targetFolderId)
            refresh()
        }
    }

    fun downloadFile(file: FileItem) {
        viewModelScope.launch {
            val serverUrl = settingsRepository.getServerUrl()
            val url = "$serverUrl/api/stream/${file.id}"
            fileDownloader.enqueue(file.id, file.fileName, url, file.mimeType)
        }
    }
    
    fun logout() {
        viewModelScope.launch {
            authRepository.clearAuth()
        }
    }

    fun openInExternalPlayer(file: FileItem) {
        viewModelScope.launch {
            val serverUrl = settingsRepository.getServerUrl()
            val publicLinkResult = filesRepository.getPublicLink(file.id, serverUrl)
            val streamUrl = publicLinkResult.getOrElse {
                val token = authRepository.getAccessToken()
                if (token != null) {
                    "$serverUrl/api/stream/${file.id}?token=$token"
                } else {
                    "$serverUrl/api/stream/${file.id}"
                }
            }
            
            try {
                val intent = Intent(Intent.ACTION_VIEW).apply {
                    setDataAndType(Uri.parse(streamUrl), "video/*")
                    flags = Intent.FLAG_ACTIVITY_NEW_TASK
                }
                context.startActivity(intent)
            } catch (e: Exception) {
                Toast.makeText(context, "No external player found", Toast.LENGTH_SHORT).show()
            }
        }
    }

    fun copyPublicLink(file: FileItem) {
        viewModelScope.launch {
            val serverUrl = settingsRepository.getServerUrl()
            val publicLinkResult = filesRepository.getPublicLink(file.id, serverUrl)
            
            publicLinkResult.onSuccess { url ->
                copyToClipboard("Public Link", url)
                Toast.makeText(context, "Public link copied to clipboard", Toast.LENGTH_SHORT).show()
            }.onFailure {
                Toast.makeText(context, "Failed to generate public link", Toast.LENGTH_SHORT).show()
            }
        }
    }

    fun revokePublicLink(file: FileItem) {
        viewModelScope.launch {
            filesRepository.revokeShare(file.id).onSuccess {
                Toast.makeText(context, "Public link revoked", Toast.LENGTH_SHORT).show()
                refresh()
            }.onFailure {
                Toast.makeText(context, "Failed to revoke public link", Toast.LENGTH_SHORT).show()
            }
        }
    }

    fun copyDownloadLink(file: FileItem) {
        viewModelScope.launch {
            val serverUrl = settingsRepository.getServerUrl()
            val token = authRepository.getAccessToken()
            val downloadUrl = if (token != null) {
                "$serverUrl/api/stream/${file.id}?token=$token"
            } else {
                "$serverUrl/api/stream/${file.id}"
            }
            copyToClipboard("Download Link", downloadUrl)
            Toast.makeText(context, "Download link copied to clipboard", Toast.LENGTH_SHORT).show()
        }
    }

    private fun copyToClipboard(label: String, text: String) {
        val clipboard = context.getSystemService(Context.CLIPBOARD_SERVICE) as ClipboardManager
        val clip = ClipData.newPlainText(label, text)
        clipboard.setPrimaryClip(clip)
    }
}
