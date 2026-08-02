package com.aruvi.tir.ui.search

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.text.BasicTextField
import androidx.compose.foundation.text.KeyboardActions
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.*
import androidx.compose.material.icons.filled.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.focus.FocusRequester
import androidx.compose.ui.focus.focusRequester
import androidx.compose.ui.focus.onFocusChanged
import androidx.compose.ui.graphics.SolidColor
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.unit.dp
import androidx.hilt.navigation.compose.hiltViewModel
import androidx.tv.foundation.lazy.grid.TvGridCells
import androidx.tv.foundation.lazy.grid.TvLazyVerticalGrid
import androidx.tv.foundation.lazy.grid.items
import com.aruvi.tir.ui.components.*
import com.aruvi.tir.ui.theme.*

/**
 * Search screen for finding files.
 */
@Composable
fun SearchScreen(
    onFileClick: (Int) -> Unit,
    onBackClick: () -> Unit,
    viewModel: SearchViewModel = hiltViewModel()
) {
    val uiState by viewModel.uiState.collectAsState()
    val searchFieldFocus = remember { FocusRequester() }
    val gridFocus = remember { FocusRequester() }

    Box(
        modifier = Modifier
            .fillMaxSize()
            .background(TVBackground)
    ) {
        Column(modifier = Modifier.fillMaxSize()) {
            // Search header
            SearchHeader(
                query = uiState.query,
                onQueryChange = { viewModel.onQueryChange(it) },
                onClear = { viewModel.clearSearch() },
                onBack = onBackClick,
                focusRequester = searchFieldFocus
            )

            // Search results
            when {
                uiState.isSearching -> {
                    LoadingIndicator(
                        message = "Searching...",
                        modifier = Modifier.weight(1f)
                    )
                }

                uiState.error != null -> {
                    ErrorState(
                        message = uiState.error!!,
                        onRetry = { viewModel.onQueryChange(uiState.query) },
                        modifier = Modifier.weight(1f)
                    )
                }

                uiState.hasSearched && uiState.results.isEmpty() -> {
                    EmptyState(
                        title = "No results found",
                        subtitle = "Try a different search term",
                        modifier = Modifier.weight(1f)
                    )
                }

                uiState.results.isNotEmpty() -> {
                    // Results count
                    Text(
                        text = "${uiState.results.size} results",
                        style = MaterialTheme.typography.bodyMedium,
                        color = TVTextSecondary,
                        modifier = Modifier.padding(horizontal = 48.dp, vertical = 8.dp)
                    )

                    // Results grid
                    TvLazyVerticalGrid(
                        columns = TvGridCells.Adaptive(200.dp),
                        modifier = Modifier
                            .fillMaxSize()
                            .focusRequester(gridFocus),
                        contentPadding = PaddingValues(horizontal = 48.dp, vertical = 16.dp),
                        horizontalArrangement = Arrangement.spacedBy(16.dp),
                        verticalArrangement = Arrangement.spacedBy(16.dp)
                    ) {
                        items(uiState.results, key = { it.id }) { file ->
                            val thumbnailUrl = "${uiState.serverUrl}/api/stream/${file.id}/thumbnail"
                            MediaCard(
                                file = file,
                                thumbnailUrl = thumbnailUrl,
                                onClick = { onFileClick(file.id) }
                            )
                        }
                    }
                }

                else -> {
                    // Initial state - no search yet
                    Box(
                        modifier = Modifier
                            .weight(1f)
                            .fillMaxWidth(),
                        contentAlignment = Alignment.Center
                    ) {
                        Column(horizontalAlignment = Alignment.CenterHorizontally) {
                            Icon(
                                imageVector = Icons.Default.Search,
                                contentDescription = null,
                                modifier = Modifier.size(64.dp),
                                tint = TVTextSecondary
                            )
                            Spacer(modifier = Modifier.height(16.dp))
                            Text(
                                text = "Search your files",
                                style = MaterialTheme.typography.titleMedium,
                                color = TVTextSecondary
                            )
                        }
                    }
                }
            }
        }
    }

    // Focus search field on launch
    LaunchedEffect(Unit) {
        try {
            searchFieldFocus.requestFocus()
        } catch (e: IllegalStateException) {
            // Ignore
        }
    }

    // Move focus to the results grid once search completes with results
    LaunchedEffect(uiState.hasSearched, uiState.results) {
        if (uiState.hasSearched && uiState.results.isNotEmpty()) {
            kotlinx.coroutines.delay(100)
            try {
                gridFocus.requestFocus()
            } catch (e: IllegalStateException) {
                // Ignore
            }
        }
    }
}

/**
 * Search header with input field.
 */
@Composable
private fun SearchHeader(
    query: String,
    onQueryChange: (String) -> Unit,
    onClear: () -> Unit,
    onBack: () -> Unit,
    focusRequester: FocusRequester
) {
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .padding(horizontal = 48.dp, vertical = 24.dp),
        verticalAlignment = Alignment.CenterVertically
    ) {
        // Back button
        TVIconButton(
            icon = {
                Icon(
                    imageVector = Icons.AutoMirrored.Filled.ArrowBack,
                    contentDescription = "Back",
                    tint = TVTextPrimary,
                    modifier = Modifier.size(24.dp)
                )
            },
            onClick = onBack,
            modifier = Modifier.size(48.dp)
        )

        Spacer(modifier = Modifier.width(24.dp))

        // Search input
        var searchFocused by remember { mutableStateOf(false) }
        Box(
            modifier = Modifier
                .weight(1f)
                .height(56.dp)
                .border(
                    width = if (searchFocused) 3.dp else 1.dp,
                    color = if (searchFocused) TVFocusRing else TVTextSecondary.copy(alpha = 0.15f),
                    shape = MaterialTheme.shapes.medium
                )
                .background(TVSurfaceVariant, MaterialTheme.shapes.medium)
                .onFocusChanged { searchFocused = it.isFocused }
                .padding(horizontal = 16.dp),
            contentAlignment = Alignment.CenterStart
        ) {
            Row(
                modifier = Modifier.fillMaxWidth(),
                verticalAlignment = Alignment.CenterVertically
            ) {
                Icon(
                    imageVector = Icons.Default.Search,
                    contentDescription = null,
                    tint = TVTextSecondary,
                    modifier = Modifier.size(24.dp)
                )

                Spacer(modifier = Modifier.width(12.dp))

                BasicTextField(
                    value = query,
                    onValueChange = onQueryChange,
                    modifier = Modifier
                        .weight(1f)
                        .focusRequester(focusRequester),
                    textStyle = MaterialTheme.typography.bodyLarge.copy(
                        color = TVTextPrimary
                    ),
                    singleLine = true,
                    cursorBrush = SolidColor(TVPrimary),
                    keyboardOptions = KeyboardOptions(imeAction = ImeAction.Search),
                    keyboardActions = KeyboardActions(
                        onSearch = { /* Already searching with debounce */ }
                    ),
                    decorationBox = { innerTextField ->
                        if (query.isEmpty()) {
                            Text(
                                text = "Search files...",
                                style = MaterialTheme.typography.bodyLarge,
                                color = TVTextSecondary
                            )
                        }
                        innerTextField()
                    }
                )

                if (query.isNotEmpty()) {
                    TVIconButton(
                        icon = {
                            Icon(
                                imageVector = Icons.Default.Clear,
                                contentDescription = "Clear",
                                tint = TVTextSecondary
                            )
                        },
                        onClick = onClear,
                        modifier = Modifier.size(48.dp)
                    )
                }
            }
        }
    }
}
