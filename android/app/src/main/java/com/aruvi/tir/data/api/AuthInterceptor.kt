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

        // Skip auth for login endpoints (exact end-of-path match: a broad
        // contains() would also skip auth for unrelated routes that merely
        // mention these segments).
        val path = originalRequest.url.encodedPath
        if (path.endsWith("/auth/generate-code") ||
            path.endsWith("/auth/verify-code") ||
            path.endsWith("/auth/refresh")) {
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
            val newToken = runBlocking { authRepository.get().refreshAccessToken() }

            if (newToken != null) {
                // Retry with new token; close the failed response first so its
                // connection is released back to the pool.
                response.close()
                // Retry with new token
                val retryRequest = originalRequest.newBuilder()
                    .header("Authorization", "Bearer $newToken")
                    .build()
                response = chain.proceed(retryRequest)
            }
            // Else refresh failed — return the ORIGINAL 401 response as-is.
            // (The old code closed it and re-fired the request unauthenticated,
            // costing one extra network round-trip for the same 401.)
        }

        return response
    }
}
