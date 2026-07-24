package com.aruvi.tir.ui.auth

import android.content.Context
import android.content.Intent
import android.graphics.Bitmap
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
            _uiState.value = _uiState.value.copy(serverUrl = url, botUsername = bot)

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
    }

    fun fetchBotInfo() {
        viewModelScope.launch {
            authRepository.getBotInfo().onSuccess { botInfo ->
                _uiState.value = _uiState.value.copy(botUsername = botInfo.username)
                settingsRepository.setBotUsername(botInfo.username)
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
                val intent = context.packageManager.getLaunchIntentForPackage(context.packageName)
                intent?.addFlags(Intent.FLAG_ACTIVITY_CLEAR_TOP or Intent.FLAG_ACTIVITY_NEW_TASK)
                context.startActivity(intent)
                Runtime.getRuntime().exit(0)
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
                        val bot = _uiState.value.botUsername.ifBlank { "Aaruvi_movie_bot" }
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
                        e.printStackTrace()
                        _uiState.value = _uiState.value.copy(
                            isLoading = false,
                            error = e.toUserFriendlyMessage(),
                            debugLog = _uiState.value.debugLog + "Failed: ${e.message}\n"
                        )
                    }
                )
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

            repeat(150) {
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
                if (msg.contains("expired") || msg.contains("already used")) {
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

                delay(2000)
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
        for (x in 0 until size) {
            for (y in 0 until size) {
                bitmap.setPixel(x, y, if (bitMatrix[x, y]) android.graphics.Color.BLACK else android.graphics.Color.WHITE)
            }
        }
        return bitmap
    }
}
