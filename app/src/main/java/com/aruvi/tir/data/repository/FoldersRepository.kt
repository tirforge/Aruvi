package com.aruvi.tir.data.repository

import com.aruvi.tir.data.api.TelePlayApi
import com.aruvi.tir.data.model.Folder
import com.aruvi.tir.data.model.FolderDetail
import com.aruvi.tir.data.model.FolderWithChildren
import com.aruvi.tir.data.model.FolderCreate
import com.aruvi.tir.data.model.FolderUpdate
import javax.inject.Inject
import javax.inject.Singleton

/**
 * Repository for folder operations.
 */
@Singleton
class FoldersRepository @Inject constructor(
    private val api: TelePlayApi
) {

    /**
     * Get folders, optionally by parent.
     */
    suspend fun getFolders(parentId: Int? = null): Result<List<Folder>> {
        return try {
            val response = api.getFolders(parentId)
            if (response.isSuccessful) {
                Result.success(response.body() ?: emptyList())
            } else {
                Result.failure(Exception("Failed to fetch folders: ${response.code()}"))
            }
        } catch (e: kotlinx.coroutines.CancellationException) {
            throw e
        } catch (e: Exception) {
            Result.failure(e)
        }
    }

    /**
     * Get folder details with files and subfolders.
     */
    suspend fun getFolder(folderId: Int): Result<FolderDetail> {
        return try {
            val response = api.getFolder(folderId)
            if (response.isSuccessful) {
                val body = response.body()
                if (body != null) Result.success(body) else Result.failure(Exception("Empty response from server"))
            } else {
                Result.failure(Exception("Folder not found"))
            }
        } catch (e: kotlinx.coroutines.CancellationException) {
            throw e
        } catch (e: Exception) {
            Result.failure(e)
        }
    }

    /**
     * Create a new folder.
     */
    suspend fun createFolder(name: String, parentId: Int? = null): Result<Folder> {
        return try {
            val create = FolderCreate(name, parentId)
            val response = api.createFolder(create)
            if (response.isSuccessful) {
                val body = response.body()
                if (body != null) Result.success(body) else Result.failure(Exception("Empty response from server"))
            } else {
                Result.failure(Exception("Failed to create folder"))
            }
        } catch (e: kotlinx.coroutines.CancellationException) {
            throw e
        } catch (e: Exception) {
            Result.failure(e)
        }
    }

    /**
     * Rename or move a folder.
     */
    suspend fun updateFolder(folderId: Int, name: String? = null, parentId: Int? = null): Result<Folder> {
        return try {
            val update = FolderUpdate(name, parentId)
            val response = api.updateFolder(folderId, update)
            if (response.isSuccessful) {
                val body = response.body()
                if (body != null) Result.success(body) else Result.failure(Exception("Empty response from server"))
            } else {
                Result.failure(Exception("Failed to update folder"))
            }
        } catch (e: kotlinx.coroutines.CancellationException) {
            throw e
        } catch (e: Exception) {
            Result.failure(e)
        }
    }

    /**
     * Delete a folder.
     */
    suspend fun deleteFolder(folderId: Int, moveFilesTo: Int? = null): Result<Unit> {
        return try {
            val response = api.deleteFolder(folderId, moveFilesTo)
            if (response.isSuccessful) {
                Result.success(Unit)
            } else {
                Result.failure(Exception("Failed to delete folder"))
            }
        } catch (e: kotlinx.coroutines.CancellationException) {
            throw e
        } catch (e: Exception) {
            Result.failure(e)
        }
    }

    /**
     * Get the complete folder tree.
     */
    suspend fun getFolderTree(): Result<List<FolderWithChildren>> {
        return try {
            val response = api.getFolderTree()
            if (response.isSuccessful) {
                Result.success(response.body() ?: emptyList())
            } else {
                Result.failure(Exception("Failed to fetch folder tree"))
            }
        } catch (e: kotlinx.coroutines.CancellationException) {
            throw e
        } catch (e: Exception) {
            Result.failure(e)
        }
    }
}
