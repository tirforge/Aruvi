package com.aruvi.tir.data.repository

import com.aruvi.tir.data.api.TelePlayApi
import com.aruvi.tir.data.model.*
import javax.inject.Inject
import javax.inject.Singleton

/**
 * Repository for file operations.
 */
@Singleton
class FilesRepository @Inject constructor(
    private val api: TelePlayApi
) {

    /**
     * Get paginated list of files.
     */
    suspend fun getFiles(
        folderId: Int? = null,
        page: Int = 1,
        perPage: Int = 20,
        fileType: String? = null
    ): Result<PaginatedResponse<FileItem>> {
        return try {
            val response = api.getFiles(folderId, page, perPage, fileType, includeAll = true)
            if (response.isSuccessful) {
                val body = response.body()
                if (body != null) {
                    Result.success(body)
                } else {
                    Result.failure(Exception("Empty response from server"))
                }
            } else {
                Result.failure(Exception("Failed to fetch files: ${response.code()}"))
            }
        } catch (e: kotlinx.coroutines.CancellationException) {
            throw e
        } catch (e: Exception) {
            Result.failure(e)
        }
    }

    /**
     * Get a single file by ID.
     */
    suspend fun getFile(fileId: Int): Result<FileItem> {
        return try {
            val response = api.getFile(fileId)
            if (response.isSuccessful) {
                val body = response.body()
                if (body != null) Result.success(body) else Result.failure(Exception("Empty response from server"))
            } else {
                Result.failure(Exception("File not found"))
            }
        } catch (e: kotlinx.coroutines.CancellationException) {
            throw e
        } catch (e: Exception) {
            Result.failure(e)
        }
    }

    /**
     * Search files by name.
     */
    suspend fun searchFiles(query: String, limit: Int = 50): Result<List<FileItem>> {
        return try {
            val response = api.searchFiles(query, limit)
            if (response.isSuccessful) {
                Result.success(response.body()?.items ?: emptyList())
            } else {
                Result.failure(Exception("Search failed: ${response.code()}"))
            }
        } catch (e: kotlinx.coroutines.CancellationException) {
            throw e
        } catch (e: Exception) {
            Result.failure(e)
        }
    }

    /**
     * Rename or move a file.
     */
    suspend fun updateFile(fileId: Int, name: String? = null, folderId: Int? = null): Result<FileItem> {
        return try {
            val update = FileUpdate(fileName = name, folderId = folderId)
            val response = api.updateFile(fileId, update)
            if (response.isSuccessful) {
                val body = response.body()
                if (body != null) Result.success(body) else Result.failure(Exception("Empty response from server"))
            } else {
                Result.failure(Exception("Failed to update file"))
            }
        } catch (e: kotlinx.coroutines.CancellationException) {
            throw e
        } catch (e: Exception) {
            Result.failure(e)
        }
    }

    /**
     * Delete a file.
     */
    suspend fun deleteFile(fileId: Int): Result<Unit> {
        return try {
            val response = api.deleteFile(fileId)
            if (response.isSuccessful) {
                Result.success(Unit)
            } else {
                Result.failure(Exception("Failed to delete file"))
            }
        } catch (e: kotlinx.coroutines.CancellationException) {
            throw e
        } catch (e: Exception) {
            Result.failure(e)
        }
    }

    /**
     * Get watch progress for a file.
     */
    suspend fun getWatchProgress(fileId: Int): Result<WatchProgress?> {
        return try {
            val response = api.getWatchProgress(fileId)
            if (response.isSuccessful) {
                Result.success(response.body())
            } else if (response.code() == 404) {
                Result.success(null)
            } else {
                Result.failure(Exception("Failed to get progress"))
            }
        } catch (e: kotlinx.coroutines.CancellationException) {
            throw e
        } catch (e: Exception) {
            Result.failure(e)
        }
    }

    /**
     * Update watch progress for a file.
     */
    suspend fun updateWatchProgress(
        fileId: Int,
        position: Int,
        duration: Int?,
        completed: Boolean = false
    ): Result<WatchProgress> {
        return try {
            val update = WatchProgressUpdate(position, duration, completed)
            val response = api.updateWatchProgress(fileId, update)
            if (response.isSuccessful) {
                val body = response.body()
                if (body != null) Result.success(body) else Result.failure(Exception("Empty response from server"))
            } else {
                Result.failure(Exception("Failed to update progress"))
            }
        } catch (e: kotlinx.coroutines.CancellationException) {
            throw e
        } catch (e: Exception) {
            Result.failure(e)
        }
    }

    /**
     * Get TV browse data (continue watching, recent, folders).
     */
    suspend fun getTVBrowse(): Result<TVBrowseResponse> {
        return try {
            val response = api.getTVBrowse()
            if (response.isSuccessful) {
                val body = response.body()
                if (body != null) Result.success(body) else Result.failure(Exception("Empty response from server"))
            } else {
                Result.failure(Exception("Failed to load home data"))
            }
        } catch (e: kotlinx.coroutines.CancellationException) {
            throw e
        } catch (e: Exception) {
            Result.failure(e)
        }
    }

    /**
     * Get continue watching list.
     */
    suspend fun getContinueWatching(): Result<List<FileItem>> {
        return try {
            val response = api.getContinueWatching()
            if (response.isSuccessful) {
                Result.success(response.body() ?: emptyList())
            } else {
                Result.failure(Exception("Failed to load continue watching"))
            }
        } catch (e: kotlinx.coroutines.CancellationException) {
            throw e
        } catch (e: Exception) {
            Result.failure(e)
        }
    }

    /**
     * Get recently added files.
     */
    suspend fun getRecentFiles(limit: Int = 20): Result<List<FileItem>> {
        return try {
            val response = api.getRecentFiles(limit)
            if (response.isSuccessful) {
                Result.success(response.body() ?: emptyList())
            } else {
                Result.failure(Exception("Failed to load recent files"))
            }
        } catch (e: kotlinx.coroutines.CancellationException) {
            throw e
        } catch (e: Exception) {
            Result.failure(e)
        }
    }

    /**
     * Search for TV.
     */
    suspend fun searchTV(query: String): Result<SearchResponse> {
        return try {
            val response = api.searchTV(query)
            if (response.isSuccessful) {
                val body = response.body()
                if (body != null) Result.success(body) else Result.failure(Exception("Empty response from server"))
            } else {
                Result.failure(Exception("Search failed"))
            }
        } catch (e: kotlinx.coroutines.CancellationException) {
            throw e
        } catch (e: Exception) {
            Result.failure(e)
        }
    }

    /**
     * Build streaming URL for a file.
     */
    fun getStreamUrl(fileId: Int, serverUrl: String): String {
        return "${serverUrl.trimEnd('/')}/api/stream/$fileId"
    }

    /**
     * Get a public streaming URL for a file.
     * This triggers the backend to generate a public hash if it doesn't exist.
     */
    suspend fun getPublicLink(fileId: Int, serverUrl: String): Result<String> {
        return try {
            val response = api.shareFile(fileId)
            if (response.isSuccessful) {
                val file = response.body()
                if (file?.publicHash != null) {
                    Result.success("${serverUrl.trimEnd('/')}/api/stream/s/${file.publicHash}")
                } else {
                    Result.failure(Exception("Failed to generate public hash"))
                }
            } else {
                Result.failure(Exception("Failed to share file: ${response.code()}"))
            }
        } catch (e: kotlinx.coroutines.CancellationException) {
            throw e
        } catch (e: Exception) {
            Result.failure(e)
        }
    }

    /**
     * Revoke a public link for a file.
     */
    suspend fun revokeShare(fileId: Int): Result<FileItem> {
        return try {
            val response = api.revokeShare(fileId)
            if (response.isSuccessful) {
                val body = response.body()
                if (body != null) Result.success(body) else Result.failure(Exception("Empty response from server"))
            } else {
                Result.failure(Exception("Failed to revoke share"))
            }
        } catch (e: kotlinx.coroutines.CancellationException) {
            throw e
        } catch (e: Exception) {
            Result.failure(e)
        }
    }

    /**
     * Build thumbnail URL for a file.
     */
    fun getThumbnailUrl(fileId: Int, serverUrl: String): String {
        return "${serverUrl.trimEnd('/')}/api/stream/$fileId/thumbnail"
    }
}
