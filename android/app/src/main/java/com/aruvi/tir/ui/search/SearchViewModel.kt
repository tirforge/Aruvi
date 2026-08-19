package com.aruvi.tir.ui.search

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.aruvi.tir.data.model.FileItem
import com.aruvi.tir.data.model.FolderWithChildren
import com.aruvi.tir.data.repository.FilesRepository
import com.aruvi.tir.data.repository.SettingsRepository
import dagger.hilt.android.lifecycle.HiltViewModel
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch
import javax.inject.Inject

/**
 * Search screen UI state.
 */
data class SearchUiState(
    val query: String = "",
    val isSearching: Boolean = false,
    val results: List<FileItem> = emptyList(),
    val hasSearched: Boolean = false,
    val serverUrl: String = "",
    val folders: List<com.aruvi.tir.data.model.Folder> = emptyList(),
    val error: String? = null
)

/**
 * ViewModel for the search screen.
 */
@HiltViewModel
class SearchViewModel @Inject constructor(
    @dagger.hilt.android.qualifiers.ApplicationContext private val context: android.content.Context,
    private val filesRepository: FilesRepository,
    private val foldersRepository: com.aruvi.tir.data.repository.FoldersRepository,
    private val settingsRepository: SettingsRepository,
    private val authRepository: com.aruvi.tir.data.repository.AuthRepository,
    private val fileDownloader: com.aruvi.tir.download.FileDownloader
) : ViewModel() {

    private val _uiState = MutableStateFlow(SearchUiState())
    val uiState: StateFlow<SearchUiState> = _uiState.asStateFlow()

    private var searchJob: Job? = null

    init {
        loadServerUrl()
        loadFolders()
    }

    private fun loadFolders() {
        viewModelScope.launch {
            foldersRepository.getFolders(null).onSuccess { folders ->
                _uiState.value = _uiState.value.copy(folders = folders)
            }
        }
    }

    suspend fun loadFolderTree(): List<FolderWithChildren> =
        foldersRepository.getFolderTree().getOrNull() ?: emptyList()

    private fun loadServerUrl() {
        viewModelScope.launch {
            val serverUrl = settingsRepository.getServerUrl()
            _uiState.value = _uiState.value.copy(serverUrl = serverUrl)
        }
    }

    /**
     * Update search query with debounce.
     */
    fun onQueryChange(query: String) {
        _uiState.value = _uiState.value.copy(query = query)
        
        // Debounce search
        searchJob?.cancel()
        searchJob = viewModelScope.launch {
            delay(300)
            if (query.length >= 2) {
                search(query)
            } else {
                _uiState.value = _uiState.value.copy(
                    results = emptyList(),
                    hasSearched = false
                )
            }
        }
    }

    /**
     * Execute search.
     */
    private suspend fun search(query: String) {
        _uiState.value = _uiState.value.copy(isSearching = true, error = null)

        val result = filesRepository.searchFiles(query, limit = 50)
        result.fold(
            onSuccess = { files ->
                _uiState.value = _uiState.value.copy(
                    isSearching = false,
                    results = files,
                    hasSearched = true
                )
            },
            onFailure = { e ->
                _uiState.value = _uiState.value.copy(
                    isSearching = false,
                    error = e.message ?: "Search failed",
                    hasSearched = true
                )
            }
        )
    }

    /**
     * Clear search.
     */
    fun clearSearch() {
        _uiState.value = _uiState.value.copy(
            query = "",
            results = emptyList(),
            hasSearched = false
        )
    }

    // --- File Operations (Mirrored from MobileHomeViewModel) ---
    
    fun deleteFile(file: FileItem) {
        viewModelScope.launch {
            filesRepository.deleteFile(file.id).onSuccess {
                _uiState.value = _uiState.value.copy(
                    results = _uiState.value.results.filter { it.id != file.id }
                )
            }
        }
    }
    
    fun renameFile(file: FileItem, newName: String) {
        viewModelScope.launch {
            filesRepository.updateFile(file.id, name = newName).onSuccess { updatedFile ->
                _uiState.value = _uiState.value.copy(
                    results = _uiState.value.results.map { if (it.id == file.id) updatedFile else it }
                )
            }
        }
    }
    
    fun moveFile(file: FileItem, targetFolderId: Int?) {
        viewModelScope.launch {
            filesRepository.updateFile(file.id, folderId = targetFolderId).onSuccess {
                // If moved, we can optionally remove it from search results or just keep it
                // Usually search results are global, so keeping it is fine, but it moved folders.
                // Let's keep it for now as moving doesn't invalidate the search match.
            }
        }
    }

    fun downloadFile(file: FileItem) {
        viewModelScope.launch {
            val serverUrl = _uiState.value.serverUrl
            if (serverUrl.isEmpty()) return@launch
            val url = "$serverUrl/api/stream/${file.id}"
            fileDownloader.enqueue(file.id, file.fileName, url, file.mimeType)
        }
    }

    fun openInExternalPlayer(file: FileItem) {
        viewModelScope.launch {
            val serverUrl = _uiState.value.serverUrl
            if (serverUrl.isEmpty()) return@launch
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
                val intent = android.content.Intent(android.content.Intent.ACTION_VIEW).apply {
                    setDataAndType(android.net.Uri.parse(streamUrl), "video/*")
                    flags = android.content.Intent.FLAG_ACTIVITY_NEW_TASK
                }
                context.startActivity(intent)
            } catch (e: Exception) {
                android.widget.Toast.makeText(context, "No external player found", android.widget.Toast.LENGTH_SHORT).show()
            }
        }
    }

    fun copyPublicLink(file: FileItem) {
        viewModelScope.launch {
            val serverUrl = _uiState.value.serverUrl
            if (serverUrl.isEmpty()) return@launch
            val publicLinkResult = filesRepository.getPublicLink(file.id, serverUrl)
            
            publicLinkResult.onSuccess { url ->
                val clipboard = context.getSystemService(android.content.Context.CLIPBOARD_SERVICE) as android.content.ClipboardManager
                val clip = android.content.ClipData.newPlainText("Public Link", url)
                clipboard.setPrimaryClip(clip)
                android.widget.Toast.makeText(context, "Public link copied", android.widget.Toast.LENGTH_SHORT).show()
                // Update result to show hash icon
                filesRepository.getFile(file.id).onSuccess { updated ->
                    _uiState.value = _uiState.value.copy(
                        results = _uiState.value.results.map { if (it.id == file.id) updated else it }
                    )
                }
            }
        }
    }

    fun revokePublicLink(file: FileItem) {
        viewModelScope.launch {
            filesRepository.revokeShare(file.id).onSuccess {
                android.widget.Toast.makeText(context, "Public link revoked", android.widget.Toast.LENGTH_SHORT).show()
                filesRepository.getFile(file.id).onSuccess { updated ->
                    _uiState.value = _uiState.value.copy(
                        results = _uiState.value.results.map { if (it.id == file.id) updated else it }
                    )
                }
            }
        }
    }

    fun copyDownloadLink(file: FileItem) {
        viewModelScope.launch {
            val serverUrl = _uiState.value.serverUrl
            if (serverUrl.isEmpty()) return@launch
            val token = authRepository.getAccessToken()
            val downloadUrl = if (token != null) {
                "$serverUrl/api/stream/${file.id}?token=$token"
            } else {
                "$serverUrl/api/stream/${file.id}"
            }
            val clipboard = context.getSystemService(android.content.Context.CLIPBOARD_SERVICE) as android.content.ClipboardManager
            val clip = android.content.ClipData.newPlainText("Download Link", downloadUrl)
            clipboard.setPrimaryClip(clip)
            android.widget.Toast.makeText(context, "Download link copied", android.widget.Toast.LENGTH_SHORT).show()
        }
    }
}
