package com.aruvi.tir.ui.browse

import androidx.lifecycle.SavedStateHandle
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.aruvi.tir.data.model.FileItem
import com.aruvi.tir.data.model.Folder
import com.aruvi.tir.data.model.FolderDetail
import com.aruvi.tir.data.repository.FoldersRepository
import com.aruvi.tir.data.repository.SettingsRepository
import com.aruvi.tir.ui.components.toUserFriendlyMessage
import dagger.hilt.android.lifecycle.HiltViewModel
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch
import javax.inject.Inject

/**
 * Folder screen UI state.
 */
data class FolderUiState(
    val isLoading: Boolean = true,
    val folder: Folder? = null,
    val subfolders: List<Folder> = emptyList(),
    val files: List<FileItem> = emptyList(),
    val parentPath: List<Folder> = emptyList(),
    val serverUrl: String = "",
    val error: String? = null
)

/**
 * ViewModel for the folder browsing screen.
 */
@HiltViewModel
class FolderViewModel @Inject constructor(
    savedStateHandle: SavedStateHandle,
    private val foldersRepository: FoldersRepository,
    private val settingsRepository: SettingsRepository
) : ViewModel() {

    private val folderId: Int = savedStateHandle.get<Int>("folderId") ?: 0

    private val _uiState = MutableStateFlow(FolderUiState())
    val uiState: StateFlow<FolderUiState> = _uiState.asStateFlow()

    init {
        loadFolder()
    }

    /**
     * Load folder contents.
     */
    fun loadFolder() {
        viewModelScope.launch {
            _uiState.value = _uiState.value.copy(isLoading = true, error = null)

            val serverUrl = settingsRepository.getServerUrl()
            _uiState.value = _uiState.value.copy(serverUrl = serverUrl)

            val result = foldersRepository.getFolder(folderId)
            result.fold(
                onSuccess = { folderDetail ->
                    _uiState.value = _uiState.value.copy(
                        isLoading = false,
                        folder = folderDetail.folder,
                        subfolders = folderDetail.subfolders ?: emptyList(),
                        files = folderDetail.files ?: emptyList(),
                        parentPath = folderDetail.parentPath ?: emptyList()
                    )
                },
                onFailure = { e ->
                    _uiState.value = _uiState.value.copy(
                        isLoading = false,
                        error = e.toUserFriendlyMessage()
                    )
                }
            )
        }
    }

    /**
     * Refresh folder data.
     */
    fun refresh() {
        loadFolder()
    }
}
