package com.aruvi.tir.ui.grab

import androidx.compose.animation.core.animateFloatAsState
import androidx.compose.animation.core.spring
import androidx.compose.animation.core.Spring
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.BasicTextField
import androidx.compose.foundation.text.KeyboardActions
import androidx.compose.foundation.text.KeyboardOptions

import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.filled.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.draw.shadow
import androidx.compose.ui.focus.FocusRequester
import androidx.compose.ui.focus.focusRequester
import androidx.compose.ui.focus.onFocusChanged
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.SolidColor
import androidx.compose.ui.graphics.graphicsLayer
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.hilt.navigation.compose.hiltViewModel
import androidx.tv.foundation.lazy.grid.TvGridCells
import androidx.tv.foundation.lazy.grid.TvLazyVerticalGrid
import androidx.tv.foundation.lazy.grid.items
import com.aruvi.tir.data.model.GrabSearchResult
import com.aruvi.tir.ui.theme.*

@Composable
fun TvGrabScreen(
    onBackClick: () -> Unit,
    onPlayStream: (String) -> Unit,
    viewModel: TvGrabViewModel = hiltViewModel(),
) {
    val state by viewModel.state.collectAsState()
    val searchFieldFocus = remember { FocusRequester() }
    val gridFocus = remember { FocusRequester() }

        Box(
            modifier = Modifier
                .fillMaxSize()
                .background(
                    Brush.verticalGradient(
                        colors = listOf(TVBackground, TVSurface, TVBackground)
                    )
                )
        ) {
        Column(modifier = Modifier.fillMaxSize()) {
            TvGrabSearchHeader(
                query = state.query,
onQueryChange = { viewModel.onQueryChange(it) },
onSearch = { viewModel.search() },
                onClear = { viewModel.onQueryChange("") },
                onBack = onBackClick,
                focusRequester = searchFieldFocus,
            )

            when {
                state.isSearching -> {
                    Box(Modifier.weight(1f).fillMaxWidth(), contentAlignment = Alignment.Center) {
                        Column(horizontalAlignment = Alignment.CenterHorizontally) {
                            CircularProgressIndicator(
                                modifier = Modifier.size(64.dp),
                                color = TVPrimary,
                                strokeWidth = 4.dp,
                                trackColor = TVPrimary.copy(alpha = 0.12f)
                            )
                            Spacer(Modifier.height(24.dp))
                            Text(
                                "Searching...",
                                style = MaterialTheme.typography.titleMedium,
                                color = TVTextSecondary
                            )
                        }
                    }
                }
                state.error != null -> {
                    Box(Modifier.weight(1f).fillMaxWidth(), contentAlignment = Alignment.Center) {
                        Column(horizontalAlignment = Alignment.CenterHorizontally) {
                            Box(
                                contentAlignment = Alignment.Center,
                                modifier = Modifier
                                    .size(80.dp)
                                    .background(TVError.copy(alpha = 0.1f), CircleShape)
                            ) {
                                Icon(
                                    Icons.Default.ErrorOutline, null,
                                    Modifier.size(48.dp),
                                    tint = TVError
                                )
                            }
                            Spacer(Modifier.height(24.dp))
                            Text(
                                state.error!!,
                                style = MaterialTheme.typography.titleMedium,
                                color = TVTextPrimary,
                                fontWeight = FontWeight.Medium
                            )
                            Spacer(Modifier.height(32.dp))
                            Surface(
onClick = { viewModel.search() },
color = TVPrimary,

                                shape = RoundedCornerShape(8.dp)
                            ) {
                                Text(
                                    "Retry",
                                    modifier = Modifier.padding(horizontal = 24.dp, vertical = 12.dp),
                                    color = Color.White,
                                    style = MaterialTheme.typography.labelLarge
                                )
                            }
                        }
                    }
                }
                state.hasSearched && state.results.isEmpty() -> {
                    Box(Modifier.weight(1f).fillMaxWidth(), contentAlignment = Alignment.Center) {
                        Column(horizontalAlignment = Alignment.CenterHorizontally) {
                            Box(
                                contentAlignment = Alignment.Center,
                                modifier = Modifier
                                    .size(80.dp)
                                    .background(TVPrimary.copy(alpha = 0.08f), CircleShape)
                            ) {
                                Icon(
                                    Icons.Default.Movie, null,
                                    Modifier.size(48.dp),
                                    tint = TVPrimary.copy(alpha = 0.5f)
                                )
                            }
                            Spacer(Modifier.height(24.dp))
                            Text(
                                "No movies found",
                                style = MaterialTheme.typography.titleLarge,
                                color = TVTextPrimary,
                                fontWeight = FontWeight.Medium
                            )
                            Spacer(Modifier.height(8.dp))
                            Text(
                                "Try a different search term",
                                style = MaterialTheme.typography.bodyMedium,
                                color = TVTextSecondary
                            )
                        }
                    }
                }
                state.results.isNotEmpty() -> {
                    Text(
                        text = "${state.results.size} results",
                        style = MaterialTheme.typography.bodyMedium,
                        color = TVTextSecondary,
                        modifier = Modifier.padding(horizontal = 48.dp, vertical = 8.dp),
                    )
                    TvLazyVerticalGrid(
                        columns = TvGridCells.Adaptive(200.dp),
                        modifier = Modifier
                            .fillMaxSize()
                            .focusRequester(gridFocus),
                        contentPadding = PaddingValues(horizontal = 48.dp, vertical = 16.dp),
                        horizontalArrangement = Arrangement.spacedBy(16.dp),
                        verticalArrangement = Arrangement.spacedBy(16.dp),
                    ) {
items(state.results, key = { "${it.msgId}-${it.row}-${it.col}-${it.label}" }) { item ->
                            TvGrabCard(
                                item = item,
                                isGrabbing = state.grabbingIdx == item.row * 100 + item.col,
                                onGrab = { viewModel.grabItem(item) },
                            )
                        }
                    }
                }
                else -> {
                    Box(Modifier.weight(1f).fillMaxWidth(), contentAlignment = Alignment.Center) {
                        Column(horizontalAlignment = Alignment.CenterHorizontally) {
                            Box(
                                contentAlignment = Alignment.Center,
                                modifier = Modifier
                                    .size(80.dp)
                                    .background(TVPrimary.copy(alpha = 0.08f), CircleShape)
                            ) {
                                Icon(
                                    Icons.Default.Movie, null,
                                    Modifier.size(48.dp),
                                    tint = TVPrimary.copy(alpha = 0.5f)
                                )
                            }
                            Spacer(Modifier.height(24.dp))
                            Text(
                                "Search Telegram groups",
                                style = MaterialTheme.typography.titleLarge,
                                color = TVTextPrimary,
                                fontWeight = FontWeight.Medium
                            )
                            Spacer(Modifier.height(8.dp))
                            Text(
                                "for movies to watch",
                                style = MaterialTheme.typography.bodyMedium,
                                color = TVTextSecondary
                            )
                        }
                    }
                }
            }
        }
    }

    LaunchedEffect(Unit) {
        try {
            searchFieldFocus.requestFocus()
        } catch (e: IllegalStateException) {
            // Ignore - focus requester not yet attached
        }
    }

    // Move focus to the results grid once search completes with results
    LaunchedEffect(state.hasSearched, state.results) {
        if (state.hasSearched && state.results.isNotEmpty()) {
            kotlinx.coroutines.delay(100)
            try {
                gridFocus.requestFocus()
            } catch (e: IllegalStateException) {
                // Ignore
            }
        }
    }

    if (state.grabResult != null) {
        val result = state.grabResult!!
        AlertDialog(
            onDismissRequest = { viewModel.clearGrabResult() },
            containerColor = TVSurface,
            titleContentColor = TVTextPrimary,
            textContentColor = TVTextSecondary,
            icon = {
                Box(
                    contentAlignment = Alignment.Center,
                    modifier = Modifier
                        .size(56.dp)
                        .background(TVSuccess.copy(alpha = 0.15f), CircleShape)
                ) {
                    Icon(Icons.Default.CheckCircle, null, Modifier.size(32.dp), tint = TVSuccess)
                }
            },
            title = {
                Text("Ready to Watch!", fontWeight = FontWeight.SemiBold)
            },
            text = {
                Column {
                    Text(result.name, fontWeight = FontWeight.Medium, color = TVTextPrimary)
                    Spacer(Modifier.height(4.dp))
                    Text(formatFileSize(result.size), color = TVTextSecondary)
                }
            },
            confirmButton = {
                Button(
                    onClick = {
                        onPlayStream(result.streamUrl)
                        viewModel.clearGrabResult()
                    },
                    colors = ButtonDefaults.buttonColors(containerColor = TVPrimary),
                    shape = RoundedCornerShape(8.dp)
                ) {
                    Icon(Icons.Default.PlayArrow, null, Modifier.size(18.dp))
                    Spacer(Modifier.width(8.dp))
                    Text("Watch Now")
                }
            },
            dismissButton = {
                TextButton(onClick = { viewModel.clearGrabResult() }) {
                    Text("Close", color = TVTextSecondary)
                }
            },
        )
    }
}

@Composable
private fun TvGrabSearchHeader(
query: String, onQueryChange: (String) -> Unit,
onSearch: () -> Unit,

    onClear: () -> Unit, onBack: () -> Unit,
    focusRequester: FocusRequester,
) {
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .padding(horizontal = 48.dp, vertical = 24.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        var backFocused by remember { mutableStateOf(false) }
        val backScale by animateFloatAsState(
            targetValue = if (backFocused) 1.1f else 1f,
            animationSpec = spring(dampingRatio = Spring.DampingRatioNoBouncy, stiffness = Spring.StiffnessHigh),
            label = "backScale"
        )
        Surface(
            onClick = onBack,
            color = if (backFocused) TVCardFocused else TVSurface.copy(alpha = 0.6f),
            shape = RoundedCornerShape(12.dp),
            modifier = Modifier
                .size(48.dp)
                .graphicsLayer { scaleX = backScale; scaleY = backScale }
                .onFocusChanged { backFocused = it.isFocused },
        ) {
            Box(contentAlignment = Alignment.Center) {
                Icon(Icons.AutoMirrored.Filled.ArrowBack, "Back", tint = TVTextPrimary, modifier = Modifier.size(24.dp))
            }
        }
        Spacer(Modifier.width(24.dp))

        var searchFocused by remember { mutableStateOf(false) }
        Box(
            modifier = Modifier
                .weight(1f)
                .height(56.dp)
                .shadow(4.dp, MaterialTheme.shapes.medium)
                .border(
                    width = if (searchFocused) 3.dp else 1.dp,
                    color = if (searchFocused) TVFocusRing else TVTextSecondary.copy(alpha = 0.15f),
                    shape = MaterialTheme.shapes.medium
                )
                .background(TVSurfaceVariant, MaterialTheme.shapes.medium)
                .onFocusChanged { searchFocused = it.isFocused }
                .padding(horizontal = 16.dp),
            contentAlignment = Alignment.CenterStart,
        ) {
            Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
                Icon(Icons.Default.Search, null, tint = TVTextSecondary, modifier = Modifier.size(24.dp))
                Spacer(Modifier.width(12.dp))
                BasicTextField(
                    value = query, onValueChange = onQueryChange,
                    modifier = Modifier
                        .weight(1f)
                        .focusRequester(focusRequester),
                    textStyle = MaterialTheme.typography.bodyLarge.copy(color = TVTextPrimary),
                    singleLine = true, cursorBrush = SolidColor(TVPrimary),
keyboardOptions = KeyboardOptions(imeAction = ImeAction.Search),
keyboardActions = KeyboardActions(onSearch = { onSearch() }),
                    decorationBox = { inner ->
                        if (query.isEmpty()) Text(
                            "Search movies...",
                            style = MaterialTheme.typography.bodyLarge,
                            color = TVTextSecondary
                        )
                        inner()
                    },
                )
                if (query.isNotEmpty()) {
                    IconButton(onClick = onClear) {
                        Icon(Icons.Default.Clear, "Clear", tint = TVTextSecondary)
                    }
                }
            }
        }
    }
}

@Composable
private fun TvGrabCard(
    item: GrabSearchResult,
    isGrabbing: Boolean,
    onGrab: () -> Unit,
) {
    var isFocused by remember { mutableStateOf(false) }
    val scale by animateFloatAsState(
        targetValue = if (isFocused) 1.08f else 1f,
        animationSpec = spring(
            dampingRatio = Spring.DampingRatioNoBouncy,
            stiffness = Spring.StiffnessHigh
        ),
        label = "cardScale"
    )
    val cardAlpha by animateFloatAsState(
        targetValue = if (isFocused) 1f else 0.88f,
        animationSpec = spring(
            dampingRatio = Spring.DampingRatioNoBouncy,
            stiffness = Spring.StiffnessHigh
        ),
        label = "cardAlpha"
    )

    Surface(
        onClick = onGrab,
        color = if (isFocused) TVCardFocused else TVCardBackground,
        shape = MaterialTheme.shapes.medium,
        modifier = Modifier
            .width(200.dp)
            .graphicsLayer {
                scaleX = scale
                scaleY = scale
                alpha = cardAlpha
            }
            .onFocusChanged { isFocused = it.isFocused }
            .then(
                if (isFocused) Modifier.shadow(
                    elevation = 16.dp,
                    shape = RoundedCornerShape(12.dp),
                    ambientColor = TVAccentGlow,
                    spotColor = TVPrimary.copy(alpha = 0.4f)
                ) else Modifier
            ),
    ) {
        Column(Modifier.padding(12.dp)) {
            // Thumbnail placeholder with gradient overlay
            Box(
                Modifier
                    .fillMaxWidth()
                    .aspectRatio(16f / 9f)
                    .clip(MaterialTheme.shapes.small)
                    .background(TVSurfaceVariant),
                contentAlignment = Alignment.Center,
            ) {
                Icon(Icons.Default.Movie, null, Modifier.size(36.dp), tint = TVTextDisabled)

                // Gradient overlay
                Box(
                    modifier = Modifier
                        .matchParentSize()
                        .background(
                            Brush.verticalGradient(
                                colors = listOf(
                                    Color.Transparent,
                                    Color.Black.copy(alpha = 0.4f)
                                )
                            )
                        )
                )

                // Grab overlay button (decorative - card handles the click so this
                // stays a single D-pad focus target)
                Box(
                    modifier = Modifier
                        .align(Alignment.BottomEnd)
                        .padding(8.dp)
                ) {
                    if (isGrabbing) {
                        CircularProgressIndicator(
                            modifier = Modifier.size(32.dp),
                            strokeWidth = 3.dp,
                            color = TVPrimary
                        )
                    } else {
                        Box(
                            modifier = Modifier
                                .size(40.dp)
                                .background(TVPrimary, CircleShape),
                            contentAlignment = Alignment.Center
                        ) {
                            Icon(Icons.Default.Download, "Grab", tint = Color.White, modifier = Modifier.size(20.dp))
                        }
                    }
                }
            }

            Spacer(Modifier.height(8.dp))
            Text(
                item.fileName,
                color = if (isFocused) TVTextPrimary else TVTextPrimary.copy(alpha = 0.9f),
                maxLines = 2,
                overflow = TextOverflow.Ellipsis,
                style = MaterialTheme.typography.bodyMedium,
                fontWeight = if (isFocused) FontWeight.SemiBold else FontWeight.Normal,
            )
            Spacer(Modifier.height(4.dp))
            Text(
                formatFileSize(item.fileSize),
                color = TVTextSecondary,
                style = MaterialTheme.typography.bodySmall,
            )
        }
    }
}

private fun formatFileSize(bytes: Long): String {
    return when {
        bytes >= 1_073_741_824 -> String.format("%.1f GB", bytes / 1_073_741_824.0)
        bytes >= 1_048_576 -> String.format("%.0f MB", bytes / 1_048_576.0)
        bytes >= 1_024 -> String.format("%.0f KB", bytes / 1_024.0)
        else -> "$bytes B"
    }
}
