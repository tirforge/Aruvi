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

        // Skip auth for login endpoints (exact path match so future
        // routes like /auth/refresh-extra are not skipped by accident).
        val path = originalRequest.url.encodedPath
        if (path.endsWith("/auth/generate-code") ||
            path.endsWith("/auth/verify-code") ||
            path.endsWith("/auth/refresh")) {
            return chain.proceed(originalRequest)
        }

        // Get access token (DataStore read can throw on IO/corruption —
        // treat failure as "no token" instead of crashing the call).
        val accessToken = try {
            runBlocking { authRepository.get().getAccessToken() }
        } catch (_: Exception) {
            null
        }
        
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
            val newToken = try {
                runBlocking { authRepository.get().refreshAccessToken() }
            } catch (_: Exception) {
                null
            }
            failedResponse.close()

            if (newToken != null) {
                // Retry with new token
                val retryRequest = originalRequest.newBuilder()
                    .header("Authorization", "Bearer $newToken")
                    .build()
                response = chain.proceed(retryRequest)
            } else {
                // Refresh failed — return a synthetic 401 instead of
                // re-issuing the original request unauthenticated (which
                // would just 401 again and double the traffic). The failed
                // response above is already closed and cannot be returned.
                response = Response.Builder()
                    .request(originalRequest)
                    .protocol(Protocol.HTTP_1_1)
                    .code(401)
                    .message("Unauthorized")
                    .body("".toResponseBody())
                    .build()
            }
        }

        return response
    }
}
