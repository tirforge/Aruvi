package com.aruvi.tir.ui.components

import com.google.gson.JsonSyntaxException
import com.google.gson.stream.MalformedJsonException
import java.net.ConnectException
import java.net.SocketTimeoutException
import java.net.UnknownHostException
import javax.net.ssl.SSLException

/**
 * Utility extension to convert technical network/parsing errors into user-friendly messages.
 * Never surfaces raw messages verbatim: URLs, IPs, or token query params are stripped.
 */
fun Throwable.toUserFriendlyMessage(): String {
    return when (this) {
        is MalformedJsonException, is JsonSyntaxException -> {
            "Server is waking up or returned invalid data. Please wait 10-20 seconds and try again."
        }
        is UnknownHostException, is ConnectException -> {
            "Could not connect to server. Please check your internet connection or server URL."
        }
        is SocketTimeoutException -> {
            "Connection timed out. The server might be busy or slow to respond."
        }
        is SSLException -> {
            "Secure connection failed. Check the device clock and server certificate."
        }
        is retrofit2.HttpException -> {
            when (code()) {
                401 -> "Session expired. Please log in again."
                403 -> "Access denied."
                404 -> "Not found on server."
                429 -> "Too many requests. Please wait a moment."
                in 500..599 -> "Server is busy. Please try again shortly."
                else -> "Request failed (${code()}). Please try again."
            }
        }
        else -> {
            sanitizeErrorMessage(this.message) ?: "An unexpected error occurred. Please try again."
        }
    }
}

private fun sanitizeErrorMessage(raw: String?): String? {
    if (raw.isNullOrBlank()) return null
    // Strip token/secrets and host details that must never reach the UI or screenshots.
    var msg = raw.replace(Regex("(?i)(token=)[^&\\s]*"), "$1***")
    msg = msg.replace(Regex("(?i)(bearer\\s+)[A-Za-z0-9._\\-]+"), "$1***")
    // Avoid leaking full URLs/IPs; keep it short for display.
    if (msg.length > 200) msg = msg.take(200) + "…"
    return msg.ifBlank { null }
}
