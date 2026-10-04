package com.aruvi.tir.ui.components

import com.google.gson.JsonSyntaxException
import com.google.gson.stream.MalformedJsonException
import java.net.ConnectException
import java.net.SocketTimeoutException
import java.net.UnknownHostException

/**
 * Utility extension to convert technical network/parsing errors into user-friendly messages.
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
        else -> {
            val raw = this.message ?: return "An unexpected error occurred. Please try again."
            // Never surface tokens / auth material that may hide in messages.
            var safe = raw.replace(Regex("(?i)bearer\\s+[A-Za-z0-9._~-]+"), "Bearer <redacted>")
            safe = safe.replace(Regex("[?&]token=[^&\\s]+"), "")
            if (safe.length > 200) safe = safe.take(200) + "…"
            if (safe.isBlank()) "An unexpected error occurred. Please try again." else safe
        }
    }
}
