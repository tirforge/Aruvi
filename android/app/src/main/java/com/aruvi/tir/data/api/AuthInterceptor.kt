package com.aruvi.tir.data.api

import com.aruvi.tir.data.repository.AuthRepository
import kotlinx.coroutines.runBlocking
import okhttp3.Interceptor
import okhttp3.Protocol
import okhttp3.Response
import okhttp3.ResponseBody.Companion.toResponseBody
import javax.inject.Inject
import javax.inject.Singleton

/**
 * OkHttp Interceptor that adds JWT authentication header to requests.
 */
@Singleton
class AuthInterceptor @Inject constructor(
    private val authRepository: dagger.Lazy<AuthRepository>
) : Interceptor {

    override fun intercept(chain: Interceptor.Chain): Response {
        val originalRequest = chain.request()

        // Skip auth for public login endpoints (exact match — contains()
        // would also match unrelated paths such as /files/auth/refresh).
        val path = originalRequest.url.encodedPath
        if (path.endsWith("/auth/generate-code") ||
            path.endsWith("/auth/verify-code") ||
            path.endsWith("/auth/refresh") ||
            path.endsWith("/auth/logout") ||
            path.endsWith("/auth/bot/info")) {
            return chain.proceed(originalRequest)
        }

        // Get access token
        val accessToken = runBlocking { authRepository.get().getAccessToken() }
        
        if (accessToken.isNullOrBlank()) {
            return chain.proceed(originalRequest)
        }

        // Add Authorization header
        val authenticatedRequest = originalRequest.newBuilder()
            .header("Authorization", "Bearer $accessToken")
            .build()

        var response = chain.proceed(authenticatedRequest)

        // If 401, try to refresh token
        if (response.code == 401) {
            val failedResponse = response
            val newToken = runBlocking { authRepository.get().refreshAccessToken() }
            failedResponse.close()

            if (newToken != null) {
                // Retry with new token
                val retryRequest = originalRequest.newBuilder()
                    .header("Authorization", "Bearer $newToken")
                    .build()
                response = chain.proceed(retryRequest)
            } else {
                // Refresh failed — do NOT replay the request unauthenticated
                // (that doubles load and yields a confusing second 401).
                // Return a synthetic 401 built from the failed response.
                response = failedResponse.let {
                    Response.Builder()
                        .request(originalRequest)
                        .protocol(it.protocol)
                        .code(401)
                        .message("Unauthorized")
                        .body("".toResponseBody(null))
                        .build()
                }
            }
        }

        return response
    }
}
