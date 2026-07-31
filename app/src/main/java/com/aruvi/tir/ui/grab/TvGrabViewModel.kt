package com.aruvi.tir.ui.grab

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.aruvi.tir.data.api.TelePlayApi
import com.aruvi.tir.data.model.GrabSearchRequest
import com.aruvi.tir.data.model.GrabSearchResult
import com.aruvi.tir.data.model.GrabSelectRequest
import com.aruvi.tir.data.model.GrabSelectResponse
import com.aruvi.tir.data.repository.SettingsRepository
import dagger.hilt.android.lifecycle.HiltViewModel
import kotlinx.coroutines.Job

import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch
import javax.inject.Inject

data class TvGrabUiState(
    val query: String = "",
    val isSearching: Boolean = false,
    val results: List<GrabSearchResult> = emptyList(),
    val hasSearched: Boolean = false,
    val error: String? = null,
    val grabbingIdx: Int = -1,
    val grabResult: GrabSelectResponse? = null,
    val serverUrl: String = "",
)

@HiltViewModel
class TvGrabViewModel @Inject constructor(
    private val api: TelePlayApi,
    private val settingsRepository: SettingsRepository,
) : ViewModel() {

    private val _state = MutableStateFlow(TvGrabUiState())
    val state: StateFlow<TvGrabUiState> = _state.asStateFlow()
    private var searchJob: Job? = null
    private var grabJob: Job? = null

    init { loadServerUrl() }

    private fun loadServerUrl() {
        viewModelScope.launch {
            _state.value = _state.value.copy(serverUrl = settingsRepository.getServerUrl())
        }
    }

fun onQueryChange(q: String) {
    _state.value = _state.value.copy(query = q, grabResult = null)
    if (q.length < 2) {
        _state.value = _state.value.copy(results = emptyList(), hasSearched = false)
    }
}

fun search() {
    val q = _state.value.query
    if (q.length < 2) return
    searchJob?.cancel()
    searchJob = viewModelScope.launch {
        _state.value = _state.value.copy(isSearching = true, error = null)
        try {
            val resp = api.grabSearch(GrabSearchRequest(query = q))
            if (resp.isSuccessful) {
                val body = resp.body()
                if (body != null) {
                    _state.value = _state.value.copy(
                        results = body.results, isSearching = false, hasSearched = true
                    )
                } else {
                    _state.value = _state.value.copy(
                        error = "Empty response from server", isSearching = false, hasSearched = true
                    )
                }
            } else {
                _state.value = _state.value.copy(
                    error = "Search failed (${resp.code()})", isSearching = false, hasSearched = true
                )
            }
        } catch (e: Exception) {
            _state.value = _state.value.copy(
                error = e.message ?: "Network error", isSearching = false, hasSearched = true
            )
        }
    }
}

    fun grabItem(item: GrabSearchResult) {
        val idx = item.row * 100 + item.col
        _state.value = _state.value.copy(grabbingIdx = idx, grabResult = null)
        grabJob?.cancel()
        grabJob = viewModelScope.launch {
            try {
                val resp = api.grabSelect(GrabSelectRequest(
                    query = _state.value.query,
                    row = item.row,
                    col = item.col,
                    msgId = item.msgId,
                ))
                if (resp.isSuccessful) {
                    val body = resp.body()
                    if (body != null) {
                        _state.value = _state.value.copy(grabResult = body, grabbingIdx = -1)
                    } else {
                        _state.value = _state.value.copy(error = "Empty response from server", grabbingIdx = -1)
                    }
                } else {
                    _state.value = _state.value.copy(error = "Grab failed (${resp.code()})", grabbingIdx = -1)
                }
            } catch (e: kotlinx.coroutines.CancellationException) {
                throw e
            } catch (e: Exception) {
                _state.value = _state.value.copy(error = e.message ?: "Network error", grabbingIdx = -1)
            }
        }
    }

    fun clearGrabResult() { _state.value = _state.value.copy(grabResult = null) }
    fun clearError() { _state.value = _state.value.copy(error = null) }
}
