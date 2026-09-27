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
        is java.io.IOException -> {
            "Network error. Please check your connection and try again."
        }
        is retrofit2.HttpException -> {
            when (code()) {
                401 -> "Session expired. Please log in again."
                403 -> "Access denied."
                404 -> "Not found on server."
                in 500..599 -> "Server error. Please try again later."
                else -> "Request failed. Please try again."
            }
        }
        else -> {
            // Never surface raw technical text (may contain URLs/tokens/HTML).
            "An unexpected error occurred. Please try again."
        }
    }
}
