package com.aruvi.tir.data.api

import com.aruvi.tir.data.model.*
import retrofit2.Response
import retrofit2.http.*

/**
 * TelePlay API interface for Retrofit.
 */
interface TelePlayApi {

    // ============ Authentication ============

    /**
     * Generate a login code for TV authentication.
     * User will enter this code in the Telegram bot.
     */
    @POST("auth/generate-code")
    suspend fun generateLoginCode(): Response<LoginCodeResponse>

    /**
     * Verify if the login code has been confirmed via Telegram bot.
     * Poll this endpoint after showing the code to the user.
     */
    @POST("auth/verify-code")
    suspend fun verifyCode(@Body request: VerifyCodeRequest): Response<AuthResponse>

    /**
     * Refresh the access token using the refresh token.
     */
    @POST("auth/refresh")
    suspend fun refreshToken(@Body request: RefreshRequest): Response<RefreshResponse>

    /**
     * Logout and invalidate tokens.
     */
    @POST("auth/logout")
    suspend fun logout(): Response<Unit>

    /**
     * Get current user info.
     */
    @GET("auth/me")
    suspend fun getCurrentUser(): Response<User>
    
    /**
     * Get bot info (username, version) for the login screen.
     */
    @GET("auth/bot/info")
    suspend fun getBotInfo(): Response<BotInfo>


    // ============ Files ============

    /**
     * Get list of files with optional folder filter.
     */
    @GET("files")
    suspend fun getFiles(
        @Query("folder_id") folderId: Int? = null,
        @Query("page") page: Int = 1,
        @Query("per_page") perPage: Int = 20,
        @Query("file_type") fileType: String? = null,
        @Query("search") search: String? = null,
        @Query("include_all") includeAll: Boolean = true
    ): Response<PaginatedResponse<FileItem>>

    /**
     * Get a single file by ID.
     */
    @GET("files/{id}")
    suspend fun getFile(@Path("id") fileId: Int): Response<FileItem>

    /**
     * Search files by name (Legacy wrapper for list_files with search query).
     */
    @GET("files")
    suspend fun searchFiles(
        @Query("search") query: String,
        @Query("per_page") limit: Int = 50
    ): Response<PaginatedResponse<FileItem>>

    /**
     * Rename or move a file.
     */
    @PATCH("files/{id}")
    suspend fun updateFile(
        @Path("id") fileId: Int,
        @Body body: FileUpdate
    ): Response<FileItem>

    /**
     * Delete a file.
     */
    @DELETE("files/{id}")
    suspend fun deleteFile(@Path("id") fileId: Int): Response<Unit>

    /**
     * Generate a permanent public link for a file.
     */
    @POST("files/{id}/share")
    suspend fun shareFile(@Path("id") fileId: Int): Response<FileItem>

    /**
     * Revoke the public link for a file.
     */
    @DELETE("files/{id}/share")
    suspend fun revokeShare(@Path("id") fileId: Int): Response<FileItem>


    // ============ Folders ============

    /**
     * Get all folders, optionally filtered by parent folder ID.
     */
    @GET("folders")
    suspend fun getFolders(
        @Query("parent_id") parentId: Int? = null
    ): Response<List<Folder>>

    /**
     * Get the complete folder tree for the user.
     */
    @GET("folders/tree")
    suspend fun getFolderTree(): Response<List<FolderWithChildren>>

    /**
     * Get folder details including files and subfolders.
     */
    @GET("tv/folder/{id}")
    suspend fun getFolder(@Path("id") folderId: Int): Response<FolderDetail>

    /**
     * Create a new folder.
     */
    @POST("folders")
    suspend fun createFolder(@Body body: FolderCreate): Response<Folder>

    /**
     * Rename or move a folder.
     */
    @PATCH("folders/{id}")
    suspend fun updateFolder(
        @Path("id") folderId: Int,
        @Body body: FolderUpdate
    ): Response<Folder>

    /**
     * Delete a folder.
     */
    @DELETE("folders/{id}")
    suspend fun deleteFolder(
        @Path("id") folderId: Int,
        @Query("move_files_to") moveFilesTo: Int? = null
    ): Response<Unit>


    // ============ Watch Progress ============

    /**
     * Get watch progress for a file.
     */
    @GET("files/{id}/progress")
    suspend fun getWatchProgress(@Path("id") fileId: Int): Response<WatchProgress>

    /**
     * Update watch progress for a file.
     */
    @PUT("files/{id}/progress")
    suspend fun updateWatchProgress(
        @Path("id") fileId: Int,
        @Body progress: WatchProgressUpdate
    ): Response<WatchProgress>


    // ============ TV-Specific Endpoints ============

    /**
     * Get TV browse data (continue watching, recent, folders) in one call.
     */
    @GET("tv/browse")
    suspend fun getTVBrowse(): Response<TVBrowseResponse>

    /**
     * Get continue watching list.
     */
    @GET("tv/continue")
    suspend fun getContinueWatching(): Response<List<FileItem>>

    /**
     * Get recently added files.
     */
    @GET("tv/recent")
    suspend fun getRecentFiles(
        @Query("limit") limit: Int = 20
    ): Response<List<FileItem>>

    /**
     * Search for TV (returns optimized results).
     */
    @GET("tv/search")
    suspend fun searchTV(
        @Query("q") query: String,
        @Query("limit") limit: Int = 30
    ): Response<SearchResponse>

@POST("grab/search")
suspend fun grabSearch(@Body request: GrabSearchRequest): Response<GrabSearchResponse>

@POST("grab/select")
suspend fun grabSelect(@Body request: GrabSelectRequest): Response<GrabSelectResponse>


}
