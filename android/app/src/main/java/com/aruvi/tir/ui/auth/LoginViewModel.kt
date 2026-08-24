package com.aruvi.tir.ui.auth

import android.content.Context
import android.content.Intent
import android.graphics.Bitmap
import android.util.Log
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.aruvi.tir.data.model.AuthResponse
import com.aruvi.tir.data.model.LoginCodeResponse
import com.aruvi.tir.data.repository.AuthRepository
import com.aruvi.tir.data.repository.SettingsRepository
import com.aruvi.tir.ui.components.toUserFriendlyMessage
import com.google.zxing.BarcodeFormat
import com.google.zxing.qrcode.QRCodeWriter
import dagger.hilt.android.lifecycle.HiltViewModel
import dagger.hilt.android.qualifiers.ApplicationContext
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import javax.inject.Inject

data class LoginUiState(
    val loginCode: String? = null,
    val loginUrl: String? = null,
    val qrCodeBitmap: Bitmap? = null,
    val expiresAt: String? = null,
    val isLoading: Boolean = true,
    val isPolling: Boolean = false,
    val isLoggedIn: Boolean = false,
    val error: String? = null,
    val debugLog: String = "",
    val serverUrl: String = "",
    val botUsername: String = "",
    val botName: String = "",
    val showServerConfig: Boolean = false
)

@HiltViewModel
class LoginViewModel @Inject constructor(
    @ApplicationContext private val context: Context,
    private val authRepository: AuthRepository,
    private val settingsRepository: SettingsRepository
) : ViewModel() {

    private val _uiState = MutableStateFlow(LoginUiState())
    val uiState: StateFlow<LoginUiState> = _uiState.asStateFlow()

    private var pollingJob: kotlinx.coroutines.Job? = null

    init {
        loadServerUrl()
    }

    private fun loadServerUrl() {
        viewModelScope.launch {
            val url = settingsRepository.serverUrl.first()
            val bot = settingsRepository.botUsername.first()
            val botName = settingsRepository.botName.first()
            _uiState.value = _uiState.value.copy(serverUrl = url, botUsername = bot, botName = botName)

            if (url.isNotEmpty()) {
                fetchBotInfo()
                generateLoginCode()
            }
        }
    }

    fun updateServerUrl(url: String) {
        _uiState.value = _uiState.value.copy(serverUrl = url)

        if (url.startsWith("http") && url.length > 10) {
            fetchBotInfo()
        }
    }    fun fetchBotInfo() {
        viewModelScope.launch {
            authRepository.getBotInfo().onSuccess { botInfo ->
                val username = botInfo.username.takeIf { it.isNotBlank() }
                    ?: _uiState.value.botUsername
                _uiState.value = _uiState.value.copy(
                    botUsername = username,
                    botName = botInfo.name.orEmpty()
                )
                if (botInfo.username.isNotBlank()) {
                    settingsRepository.setBotUsername(botInfo.username)
                }
                if (!botInfo.name.isNullOrBlank()) {
                    settingsRepository.setBotName(botInfo.name)
                }
            }.onFailure { e ->
                _uiState.value = _uiState.value.copy(
                    error = e.toUserFriendlyMessage()
                )
            }
        }
    }

    fun updateBotUsername(username: String) {
        _uiState.value = _uiState.value.copy(botUsername = username)
        viewModelScope.launch {
            settingsRepository.setBotUsername(username)
        }
    }

    fun toggleServerConfig() {
        _uiState.value = _uiState.value.copy(
            showServerConfig = !_uiState.value.showServerConfig
        )
    }

    fun saveAndRestart() {
        viewModelScope.launch {
            val url = _uiState.value.serverUrl
            if (url.isNotEmpty()) {
                settingsRepository.setServerUrl(url)
                // DynamicBaseUrlInterceptor picks the new server up on the
                // very next request — no process restart needed anymore (the
                // old Runtime.exit(0) hack killed the app to rebuild Retrofit).
                fetchBotInfo()
                generateLoginCode()
            }
        }
    }

    fun generateLoginCode() {
        stopPolling()

        viewModelScope.launch {
            settingsRepository.setServerUrl(_uiState.value.serverUrl)

            _uiState.value = _uiState.value.copy(
                isLoading = true,
                error = null,
                qrCodeBitmap = null,
                debugLog = "Starting generateLoginCode...\n"
            )

            try {
                val result = authRepository.generateLoginCode()

                result.fold(
                    onSuccess = { response ->
                        // The code response carries the bot username/name from the
                        // backend, so the login button/deep link always reflect the
                        // live server (no hardcoded bot, no race with a separate fetch).
                        val bot =
                            response.botUsername?.takeIf { it.isNotBlank() }
                                ?: _uiState.value.botUsername.ifBlank { "telegram" }
                        if (response.botUsername?.isNotBlank() == true) {
                            settingsRepository.setBotUsername(response.botUsername)
                            settingsRepository.setBotName(response.botName.orEmpty())
                        }
                        _uiState.value = _uiState.value.copy(
                            botUsername = bot,
                            botName = response.botName ?: _uiState.value.botName
                        )
                        val url = "https://t.me/$bot?start=${response.code}"
                        val qrBitmap = withContext(Dispatchers.Default) {
                            generateQrCode(url, 600)
                        }
                        _uiState.value = _uiState.value.copy(
                            loginCode = response.code,
                            loginUrl = url,
                            qrCodeBitmap = qrBitmap,
                            expiresAt = response.expiresAt,
                            isLoading = false,
                            debugLog = _uiState.value.debugLog + "Success! Code: ${response.code}\n"
                        )
                        startPolling(response.code)
                    },
                    onFailure = { e ->
                        Log.w("LoginViewModel", "login request failed", e)
                        _uiState.value = _uiState.value.copy(
                            isLoading = false,
                            error = e.toUserFriendlyMessage(),
                            debugLog = _uiState.value.debugLog + "Failed: ${e.message}\n"
                        )
                    }
                )
            } catch (e: kotlinx.coroutines.CancellationException) {
                throw e
            } catch (e: Exception) {
                 _uiState.value = _uiState.value.copy(
                    isLoading = false,
                    error = e.toUserFriendlyMessage(),
                    debugLog = _uiState.value.debugLog + "Crash: ${e.message}\n"
                )
            }
        }
    }

    private fun startPolling(code: String) {
        stopPolling()

        pollingJob = viewModelScope.launch {
            _uiState.value = _uiState.value.copy(isPolling = true)

            // Each call long-polls ~8s server-side; 75 cycles comfortably
            // outlives the 10-minute code expiry.
            repeat(75) {
                val result = authRepository.verifyLoginCode(code)
                result.fold(
                    onSuccess = { _ ->
                        _uiState.value = _uiState.value.copy(
                            isPolling = false,
                            isLoggedIn = true
                        )
                        return@launch
                    },
            onFailure = { e ->
                val msg = e.message.orEmpty()
                if (msg.contains("expired") || msg.contains("already used") || msg.contains("no longer valid")) {
                    _uiState.value = _uiState.value.copy(
                        isPolling = false,
                        error = if (msg.contains("already used")) {
                            "This code was already used on another device. Generate a new one."
                        } else {
                            "Code expired. Please generate a new one."
                        }
                    )
                    return@launch
                }
            }


                )

                delay(500)
            }

            _uiState.value = _uiState.value.copy(
                isPolling = false,
                error = "Login timeout. Please try again."
            )
        }
    }

    fun stopPolling() {
        pollingJob?.cancel()
        pollingJob = null
        _uiState.value = _uiState.value.copy(isPolling = false)
    }

    override fun onCleared() {
        super.onCleared()
        stopPolling()
    }

    private fun generateQrCode(content: String, size: Int): Bitmap {
        val writer = QRCodeWriter()
        val bitMatrix = writer.encode(content, BarcodeFormat.QR_CODE, size, size)
        val bitmap = Bitmap.createBitmap(size, size, Bitmap.Config.RGB_565)
        // One bulk setPixels call instead of 360k setPixel round-trips
        val pixels = IntArray(size * size)
        var i = 0
        for (y in 0 until size) {
            for (x in 0 until size) {
                pixels[i++] = if (bitMatrix[x, y]) android.graphics.Color.BLACK else android.graphics.Color.WHITE
            }
        }
        bitmap.setPixels(pixels, 0, size, 0, 0, size, size)
        return bitmap
    }
}
