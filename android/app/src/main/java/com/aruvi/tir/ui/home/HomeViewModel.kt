package com.aruvi.tir.ui.home

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.aruvi.tir.data.model.FileItem
import com.aruvi.tir.data.model.Folder
import com.aruvi.tir.data.model.TVBrowseResponse
import com.aruvi.tir.data.repository.FilesRepository
import com.aruvi.tir.data.repository.FoldersRepository
import com.aruvi.tir.data.repository.SettingsRepository
import com.aruvi.tir.ui.components.toUserFriendlyMessage
import dagger.hilt.android.lifecycle.HiltViewModel
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch
import javax.inject.Inject

/**
 * Home screen UI state.
 */
data class HomeUiState(
    val isLoading: Boolean = true,
    val continueWatching: List<FileItem> = emptyList(),
    val recentFiles: List<FileItem> = emptyList(),
    val folders: List<Folder> = emptyList(),
    val serverUrl: String = "",
    val error: String? = null
)

/**
 * ViewModel for the home screen.
 */
@HiltViewModel
class HomeViewModel @Inject constructor(
    private val filesRepository: FilesRepository,
    private val foldersRepository: FoldersRepository,
    private val settingsRepository: SettingsRepository
) : ViewModel() {

    private val _uiState = MutableStateFlow(HomeUiState())
    val uiState: StateFlow<HomeUiState> = _uiState.asStateFlow()

    private var autoRefreshJob: Job? = null
    private var lastBrowse: TVBrowseResponse? = null

    init {
        loadHomeData()
    }

    companion object {
        private const val AUTO_REFRESH_INTERVAL_MS = 10_000L
    }

    /**
     * Load all data for the home screen.
     */
    fun loadHomeData() {
        viewModelScope.launch {
            _uiState.value = _uiState.value.copy(isLoading = true, error = null)

            val serverUrl = settingsRepository.getServerUrl()
            _uiState.value = _uiState.value.copy(serverUrl = serverUrl)

            // Try to load TV browse data (combined endpoint)
            val browseResult = filesRepository.getTVBrowse()
            
            browseResult.fold(
                onSuccess = { browse ->
                    lastBrowse = browse
                    _uiState.value = _uiState.value.copy(
                        isLoading = false,
                        continueWatching = browse.continueWatching,
                        recentFiles = browse.recentFiles,
                        folders = browse.folders
                    )
                },
                onFailure = { e ->
                    lastBrowse = null
                    _uiState.value = _uiState.value.copy(
                        error = e.toUserFriendlyMessage()
                    )
                    // Fallback to individual calls if TV browse fails
                    loadDataFallback()
                }
            )
        }
    }

    /**
     * Fallback when TV browse endpoint is not available.
     */
    private suspend fun loadDataFallback() {
        // Load continue watching
        val continueResult = filesRepository.getContinueWatching()
        val continueWatching = continueResult.getOrDefault(emptyList())

        // Load recent files
        val recentResult = filesRepository.getRecentFiles(20)
        val recentFiles = recentResult.getOrDefault(emptyList())

        // Load folders
        val foldersResult = foldersRepository.getFolders()
        val folders = foldersResult.getOrDefault(emptyList())

        _uiState.value = _uiState.value.copy(
            isLoading = false,
            continueWatching = continueWatching,
            recentFiles = recentFiles,
            folders = folders,
            error = if (recentFiles.isEmpty() && folders.isEmpty()) {
                "Failed to load content"
            } else null
        )
    }

    /**
     * Refresh home data.
     */
    fun refresh() {
        loadHomeData()
    }

    /**
     * Start polling for background content updates while the screen is visible.
     */
    fun startAutoRefresh() {
        stopAutoRefresh()
        autoRefreshJob = viewModelScope.launch {
            // Only poll immediately if a browse already completed (lastBrowse != null).
            // While the initial load is in flight, lastBrowse is still null, so the
            // immediate poll is skipped to avoid a duplicate /tv/browse request
            // racing loadHomeData(); the periodic loop picks up after the delay.
            if (lastBrowse != null) {
                checkForUpdates()
            }
            while (isActive) {
                delay(AUTO_REFRESH_INTERVAL_MS)
                checkForUpdates()
            }
        }
    }

    /**
     * Stop the auto-refresh polling loop.
     */
    fun stopAutoRefresh() {
        autoRefreshJob?.cancel()
        autoRefreshJob = null
    }

    /**
     * Poll the backend and refresh the home data if it changed.
     * Background polls silently recover the UI from error/empty states: a
     * successful poll clears the error and shows the latest content without
     * touching the loading indicator mid-flight.
     * TODO: later swap to polling the backend /api/tv/revision endpoint and
     * only fetch the full browse payload when the revision changes.
     */
    private suspend fun checkForUpdates() {
        filesRepository.getTVBrowse().fold(
            onSuccess = { browse ->
                if (browse != lastBrowse) {
                    _uiState.value = _uiState.value.copy(
                        isLoading = false,
                        continueWatching = browse.continueWatching,
                        recentFiles = browse.recentFiles,
                        folders = browse.folders,
                        error = null
                    )
                    lastBrowse = browse
                }
            },
            onFailure = {
                // Silent: background polls must not disrupt the current UI.
            }
        )
    }

    override fun onCleared() {
        stopAutoRefresh()
        super.onCleared()
    }
}
