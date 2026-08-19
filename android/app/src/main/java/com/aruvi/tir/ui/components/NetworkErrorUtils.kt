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
            this.message ?: "An unexpected error occurred. Please try again."
        }
    }
}
