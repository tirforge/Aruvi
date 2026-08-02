package com.aruvi.tir.ui.components

import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyRow
import androidx.compose.foundation.lazy.items
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import com.aruvi.tir.data.model.FileItem
import com.aruvi.tir.data.model.Folder
import com.aruvi.tir.ui.theme.TVTextPrimary

/**
 * Horizontal content row for the home screen.
 * Displays a title and horizontally scrolling items.
 */
@Composable
fun ContentRow(
    title: String,
    files: List<FileItem>,
    serverUrl: String,
    onFileClick: (Int) -> Unit,
    modifier: Modifier = Modifier,
    useLargeCards: Boolean = false
) {
    Column(modifier = modifier) {
        // Row title
        Text(
            text = title,
            style = MaterialTheme.typography.headlineSmall,
            color = TVTextPrimary,
            modifier = Modifier.padding(start = 48.dp, bottom = 16.dp)
        )

        // Horizontal scrollable items
        LazyRow(
            contentPadding = PaddingValues(horizontal = 48.dp),
            horizontalArrangement = Arrangement.spacedBy(16.dp)
        ) {
            items(files, key = { it.id }) { file ->
                val thumbnailUrl = "$serverUrl/api/stream/${file.id}/thumbnail"
                
                if (useLargeCards) {
                    LargeMediaCard(
                        file = file,
                        thumbnailUrl = thumbnailUrl,
                        onClick = { onFileClick(file.id) }
                    )
                } else {
                    MediaCard(
                        file = file,
                        thumbnailUrl = thumbnailUrl,
                        onClick = { onFileClick(file.id) }
                    )
                }
            }
        }
    }
}

/**
 * Horizontal folder row for the home screen.
 */
@Composable
fun FolderRow(
    title: String,
    folders: List<Folder>,
    onFolderClick: (Int) -> Unit,
    modifier: Modifier = Modifier
) {
    Column(modifier = modifier) {
        // Row title
        Text(
            text = title,
            style = MaterialTheme.typography.headlineSmall,
            color = TVTextPrimary,
            modifier = Modifier.padding(start = 48.dp, bottom = 16.dp)
        )

        // Horizontal scrollable folders
        LazyRow(
            contentPadding = PaddingValues(horizontal = 48.dp),
            horizontalArrangement = Arrangement.spacedBy(16.dp)
        ) {
            items(folders, key = { it.id }) { folder ->
                FolderCard(
                    folder = folder,
                    onClick = { onFolderClick(folder.id) }
                )
            }
        }
    }
}
