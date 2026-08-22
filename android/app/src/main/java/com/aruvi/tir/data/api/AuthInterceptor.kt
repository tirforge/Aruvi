package com.aruvi.tir.data.api

import com.aruvi.tir.data.repository.AuthRepository
import kotlinx.coroutines.runBlocking
import okhttp3.Interceptor
import okhttp3.Response
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

        // Skip auth for login endpoints
        val path = originalRequest.url.encodedPath
        if (path.contains("/auth/generate-code") ||
            path.contains("/auth/verify-code") ||
            path.contains("/auth/refresh")) {
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
                // Refresh failed — return a FRESH unauthenticated response.
                // Returning the closed one would make Retrofit throw
                // "IllegalStateException: closed" instead of a clean 401.
                response = chain.proceed(originalRequest)
            }
        }

        return response
    }
}
