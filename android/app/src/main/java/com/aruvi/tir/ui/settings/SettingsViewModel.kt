package com.aruvi.tir.ui.settings

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.aruvi.tir.data.repository.AuthRepository
import com.aruvi.tir.data.repository.SettingsRepository
import dagger.hilt.android.lifecycle.HiltViewModel
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.launch
import javax.inject.Inject

/**
 * Settings screen UI state.
 */
data class SettingsUiState(
    val autoPlayNext: Boolean = true,
    val preferredQuality: String = "auto",
    val userName: String? = null,
    val isSaving: Boolean = false,
    val showLogoutConfirm: Boolean = false
)

/**
 * ViewModel for the settings screen.
 */
@HiltViewModel
class SettingsViewModel @Inject constructor(
    private val settingsRepository: SettingsRepository,
    private val authRepository: AuthRepository
) : ViewModel() {

    private val _uiState = MutableStateFlow(SettingsUiState())
    val uiState: StateFlow<SettingsUiState> = _uiState.asStateFlow()

    init {
        loadSettings()
    }

    /**
     * Load current settings.
     */
    private fun loadSettings() {
        viewModelScope.launch {
            val autoPlayNext = settingsRepository.autoPlayNext.first()
            val preferredQuality = settingsRepository.preferredQuality.first()
            val userName = authRepository.userName.first()

            _uiState.value = _uiState.value.copy(
                autoPlayNext = autoPlayNext,
                preferredQuality = preferredQuality,
                userName = userName
            )
        }
    }

    /**
     * Toggle auto-play next setting.
     */
    fun toggleAutoPlayNext() {
        viewModelScope.launch {
            val newValue = !_uiState.value.autoPlayNext
            _uiState.value = _uiState.value.copy(autoPlayNext = newValue)
            settingsRepository.setAutoPlayNext(newValue)
        }
    }

    /**
     * Set preferred quality.
     */
    fun setPreferredQuality(quality: String) {
        viewModelScope.launch {
            _uiState.value = _uiState.value.copy(preferredQuality = quality)
            settingsRepository.setPreferredQuality(quality)
        }
    }

    /**
     * Show logout confirmation.
     */
    fun showLogoutConfirm() {
        _uiState.value = _uiState.value.copy(showLogoutConfirm = true)
    }

    /**
     * Hide logout confirmation.
     */
    fun hideLogoutConfirm() {
        _uiState.value = _uiState.value.copy(showLogoutConfirm = false)
    }

    /**
     * Logout user.
     */
    fun logout(onComplete: () -> Unit) {
        viewModelScope.launch {
            authRepository.logout()
            onComplete()
        }
    }
}
