package com.aruvi.tir.data.api

import com.aruvi.tir.data.repository.SettingsRepository
import okhttp3.HttpUrl.Companion.toHttpUrlOrNull
import okhttp3.Interceptor
import okhttp3.Response
import javax.inject.Inject
import javax.inject.Singleton

/**
 * Rewrites every request's scheme/host/port to the CURRENT saved server URL.
 *
 * Retrofit freezes its base URL when the singleton is built, so before this
 * interceptor changing the server in the UI only took effect after a full
 * process restart (LoginViewModel worked around it with Runtime.exit(0), and
 * "Generate Code" fired at the OLD server). Requests keep the path the Retrofit
 * call produced ("api/..."), so only the origin is replaced.
 */
@Singleton
class DynamicBaseUrlInterceptor @Inject constructor(
    private val settingsRepository: SettingsRepository
) : Interceptor {

    override fun intercept(chain: Interceptor.Chain): Response {
        val request = chain.request()
        val base = settingsRepository.peekServerUrl().toHttpUrlOrNull()
            ?: return chain.proceed(request)
        val rewritten = request.url.newBuilder()
            .scheme(base.scheme)
            .host(base.host)
            .port(base.port)
            .build()
        return chain.proceed(request.newBuilder().url(rewritten).build())
    }
}
