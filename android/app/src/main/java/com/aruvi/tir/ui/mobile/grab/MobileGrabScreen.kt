package com.aruvi.tir.ui.mobile.grab

import android.content.ClipData
import android.content.ClipboardManager
import android.content.Context
import android.content.Intent
import android.net.Uri
import android.widget.Toast
import android.text.format.Formatter
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.grid.GridCells
import androidx.compose.foundation.lazy.grid.LazyVerticalGrid
import androidx.compose.foundation.lazy.grid.items
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.KeyboardActions
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.*
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.hilt.navigation.compose.hiltViewModel
import com.aruvi.tir.data.model.GrabSearchResult
import com.aruvi.tir.ui.theme.*

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun MobileGrabScreen(
onBackClick: () -> Unit,
onPlayStream: (String) -> Unit,
viewModel: GrabViewModel = hiltViewModel(),
) {
    val state by viewModel.state.collectAsState()
    val context = LocalContext.current

    Column(
        modifier = Modifier
            .fillMaxSize()
            .background(MobileBackground)
    ) {
        // Header with search field
        Box(
            modifier = Modifier
                .fillMaxWidth()
                .background(
                    Brush.verticalGradient(
                        colors = listOf(MobileHeaderGradientStart, MobileBackground)
                    )
                )
                .padding(16.dp)
                .statusBarsPadding()
        ) {
            Surface(
                modifier = Modifier
                    .fillMaxWidth()
                    .height(56.dp),
                shape = RoundedCornerShape(12.dp),
                color = MobileSurface,
                tonalElevation = 2.dp
            ) {
                Row(
                    modifier = Modifier
                        .fillMaxSize()
                        .padding(horizontal = 4.dp),
                    verticalAlignment = Alignment.CenterVertically
                ) {
                    IconButton(onClick = onBackClick) {
                        Icon(Icons.AutoMirrored.Filled.ArrowBack, "Back", tint = MobileTextSecondary)
                    }
                    Icon(Icons.Default.Movie, null, tint = MobileTextSecondary)
                    Spacer(Modifier.width(8.dp))
                    TextField(
                        value = state.query,
                        onValueChange = { viewModel.onQueryChange(it) },
                        placeholder = { Text("Search movies...", color = MobileTextSecondary) },
                        colors = TextFieldDefaults.colors(
                            focusedContainerColor = Color.Transparent,
                            unfocusedContainerColor = Color.Transparent,
                            disabledContainerColor = Color.Transparent,
                            focusedIndicatorColor = Color.Transparent,
                            unfocusedIndicatorColor = Color.Transparent,
                        ),
                        singleLine = true,
keyboardOptions = KeyboardOptions(imeAction = ImeAction.Search),
keyboardActions = KeyboardActions(onSearch = { viewModel.search() }),
                        modifier = Modifier.weight(1f),
                        textStyle = MaterialTheme.typography.bodyLarge.copy(color = MobileTextPrimary),
                    )
IconButton(onClick = { viewModel.search() }) {
    Icon(Icons.Default.Search, "Search", tint = MobileTextSecondary)
}
if (state.query.isNotEmpty()) {
                        IconButton(onClick = { viewModel.onQueryChange("") }) {
                            Icon(Icons.Default.Close, "Clear", tint = MobileTextSecondary)
                        }
                    }
                }
            }
        }

        when {
            state.isSearching -> {
                Box(Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
                    Column(horizontalAlignment = Alignment.CenterHorizontally) {
                        CircularProgressIndicator(color = MobilePrimary)
                        Spacer(Modifier.height(16.dp))
                        Text("Searching...", color = MobileTextSecondary)
                    }
                }
            }
            state.error != null -> {
                Box(Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
                    Column(horizontalAlignment = Alignment.CenterHorizontally) {
                        Box(
                            contentAlignment = Alignment.Center,
                            modifier = Modifier
                                .size(64.dp)
                                .background(TVError.copy(alpha = 0.1f), CircleShape)
                        ) {
                            Icon(Icons.Default.ErrorOutline, null, Modifier.size(36.dp), tint = TVError)
                        }
                        Spacer(Modifier.height(16.dp))
                        Text(
                            state.error!!,
                            color = MobileTextPrimary,
                            style = MaterialTheme.typography.bodyMedium,
                            fontWeight = FontWeight.Medium
                        )
                        Spacer(Modifier.height(16.dp))
                        TextButton(onClick = { viewModel.clearError() }) {
                            Text("Dismiss", color = MobilePrimary)
                        }
                    }
                }
            }
            state.hasSearched && state.results.isEmpty() -> {
                Box(Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
                    Column(horizontalAlignment = Alignment.CenterHorizontally) {
                        Box(
                            contentAlignment = Alignment.Center,
                            modifier = Modifier
                                .size(64.dp)
                                .background(MobilePrimary.copy(alpha = 0.08f), CircleShape)
                        ) {
                            Icon(Icons.Default.Movie, null, Modifier.size(36.dp), tint = MobilePrimary.copy(alpha = 0.5f))
                        }
                        Spacer(Modifier.height(16.dp))
                        Text("No movies found", color = MobileTextPrimary, fontWeight = FontWeight.Medium)
                        Spacer(Modifier.height(4.dp))
                        Text(
                            "Try a different search term",
                            color = MobileTextSecondary,
                            style = MaterialTheme.typography.bodySmall
                        )
                    }
                }
            }
            state.results.isNotEmpty() -> {
                Text(
                    "${state.results.size} results",
                    color = MobileTextSecondary,
                    modifier = Modifier.padding(horizontal = 16.dp, vertical = 8.dp),
                    style = MaterialTheme.typography.bodySmall
                )
                LazyVerticalGrid(
                    columns = GridCells.Adaptive(minSize = 160.dp),
                    contentPadding = PaddingValues(16.dp),
                    verticalArrangement = Arrangement.spacedBy(12.dp),
                    horizontalArrangement = Arrangement.spacedBy(12.dp),
                    modifier = Modifier.fillMaxSize(),
                ) {
items(state.results, key = { "${it.msgId}-${it.row}-${it.col}-${it.label}" }) { item ->
                        GrabMovieCard(
                            item = item,
                            isGrabbing = state.grabbingIdx == item.row * 100 + item.col + (item.msgId % 1000) * 100000,
                            onGrab = { viewModel.grabItem(item) }
                        )
                    }
                }
            }
            else -> {
                Box(Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
                    Column(horizontalAlignment = Alignment.CenterHorizontally) {
                        Box(
                            contentAlignment = Alignment.Center,
                            modifier = Modifier
                                .size(64.dp)
                                .background(MobilePrimary.copy(alpha = 0.08f), CircleShape)
                        ) {
                            Icon(Icons.Default.Movie, null, Modifier.size(36.dp), tint = MobilePrimary.copy(alpha = 0.5f))
                        }
                        Spacer(Modifier.height(16.dp))
                        Text("Search Telegram groups", color = MobileTextPrimary, fontWeight = FontWeight.Medium)
                        Spacer(Modifier.height(4.dp))
                        Text(
                            "for movies to watch",
                            color = MobileTextSecondary,
                            style = MaterialTheme.typography.bodySmall
                        )
                    }
                }
            }
        }
    }

    if (state.grabResult != null) {
        val result = state.grabResult!!
        AlertDialog(
            onDismissRequest = { viewModel.clearGrabResult() },
            containerColor = MobileSurface,
            titleContentColor = MobileTextPrimary,
            textContentColor = MobileTextSecondary,
            icon = {
                Box(
                    contentAlignment = Alignment.Center,
                    modifier = Modifier
                        .size(48.dp)
                        .background(TVSuccess.copy(alpha = 0.15f), CircleShape)
                ) {
                    Icon(Icons.Default.CheckCircle, null, Modifier.size(28.dp), tint = TVSuccess)
                }
            },
            title = {
                Text("Ready to Watch!", fontWeight = FontWeight.SemiBold)
            },
            text = {
                Column(modifier = Modifier.fillMaxWidth()) {
                    Text(result.name, fontWeight = FontWeight.Medium, color = MobileTextPrimary)
                    Spacer(Modifier.height(4.dp))
                    Text(
                        Formatter.formatFileSize(context, result.size),
                        style = MaterialTheme.typography.bodySmall,
                        color = MobileTextSecondary
                    )
                    Spacer(Modifier.height(12.dp))
                    Surface(
                        shape = RoundedCornerShape(8.dp),
                        color = MobileSurfaceVariant,
                    ) {
                        Row(
                            verticalAlignment = Alignment.CenterVertically,
                            modifier = Modifier.padding(horizontal = 12.dp, vertical = 8.dp)
                        ) {
                            Text(
                                result.streamUrl,
                                style = MaterialTheme.typography.bodySmall,
                                maxLines = 1,
                                overflow = TextOverflow.Ellipsis,
                                modifier = Modifier.weight(1f),
                                color = MobileTextSecondary
                            )
                            Spacer(Modifier.width(8.dp))
                            IconButton(
                                onClick = {
                                    val clip = ClipData.newPlainText("Stream URL", result.streamUrl)
                                    (context.getSystemService(Context.CLIPBOARD_SERVICE) as ClipboardManager)
                                        .setPrimaryClip(clip)
                                    Toast.makeText(context, "Copied!", Toast.LENGTH_SHORT).show()
                                },
modifier = Modifier.size(48.dp)
                            ) {
                                Icon(Icons.Default.ContentCopy, "Copy", Modifier.size(18.dp), tint = MobilePrimary)
                            }
                        }
                    }
                    Spacer(Modifier.height(16.dp))
                    val playInVlc = {
                        val vlcIntent = Intent(Intent.ACTION_VIEW).apply {
                            setDataAndType(Uri.parse(result.streamUrl), "video/*")
                            setPackage("org.videolan.vlc")
                            flags = Intent.FLAG_ACTIVITY_NEW_TASK
                        }
                        try {
                            context.startActivity(vlcIntent)
                        } catch (e: Exception) {
                            val genericIntent = Intent(Intent.ACTION_VIEW).apply {
                                setDataAndType(Uri.parse(result.streamUrl), "video/*")
                                flags = Intent.FLAG_ACTIVITY_NEW_TASK
                            }
                            try {
                                context.startActivity(genericIntent)
                            } catch (e2: Exception) {
                                Toast.makeText(context, "No player found", Toast.LENGTH_SHORT).show()
                            }
                        }
                    }
                    Row(
                        modifier = Modifier.fillMaxWidth(),
                        horizontalArrangement = Arrangement.spacedBy(8.dp)
                    ) {
FilledTonalButton(
onClick = playInVlc,
modifier = Modifier.weight(1f),
shape = RoundedCornerShape(8.dp)
) {
Icon(Icons.Default.PlayArrow, null, Modifier.size(18.dp))
Spacer(Modifier.width(8.dp))
Text("VLC")
}
                        FilledTonalButton(
                            onClick = {
                                viewModel.download(result)
                                Toast.makeText(context, "Download started", Toast.LENGTH_SHORT).show()
                            },
                            modifier = Modifier.weight(1f),
                            shape = RoundedCornerShape(8.dp)
                        ) {
                            Icon(Icons.Default.Download, null, Modifier.size(18.dp))
                            Spacer(Modifier.width(8.dp))
                            Text("Download")
                        }
                    }
                    Spacer(Modifier.height(8.dp))
                    Button(
                        onClick = {
                            onPlayStream(result.streamUrl)
                            viewModel.clearGrabResult()
                        },
                        modifier = Modifier.fillMaxWidth(),
                        colors = ButtonDefaults.buttonColors(containerColor = MobilePrimary),
                        shape = RoundedCornerShape(8.dp)
                    ) {
                        Icon(Icons.Default.PlayArrow, null, Modifier.size(18.dp))
                        Spacer(Modifier.width(8.dp))
                        Text("Watch Now")
                    }
}
            },
            confirmButton = {},
dismissButton = {
TextButton(onClick = { viewModel.clearGrabResult() }) {
Text("Back", color = MobileTextSecondary)
}
},
        )
    }
}

@Composable
private fun GrabMovieCard(
    item: GrabSearchResult,
    isGrabbing: Boolean,
    onGrab: () -> Unit,
) {
    Card(
        modifier = Modifier
            .fillMaxWidth()
            .clickable(enabled = !isGrabbing) { onGrab() },
        shape = RoundedCornerShape(12.dp),
        colors = CardDefaults.cardColors(containerColor = MobileSurface),
        elevation = CardDefaults.cardElevation(defaultElevation = 4.dp)
    ) {
        Column(modifier = Modifier.padding(12.dp)) {
            Box(
                modifier = Modifier
                    .fillMaxWidth()
                    .aspectRatio(16f / 9f)
                    .background(MobileSurfaceVariant, RoundedCornerShape(8.dp)),
                contentAlignment = Alignment.Center,
            ) {
                Icon(Icons.Default.Movie, null, Modifier.size(32.dp), tint = MobileTextSecondary)
            }
            Spacer(Modifier.height(8.dp))
            Text(
                item.fileName,
                color = MobileTextPrimary,
                maxLines = 2,
                overflow = TextOverflow.Ellipsis,
                style = MaterialTheme.typography.bodyMedium
            )
            Spacer(Modifier.height(4.dp))
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.SpaceBetween,
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Text(
                    Formatter.formatFileSize(LocalContext.current, item.fileSize),
                    color = MobileTextSecondary,
                    style = MaterialTheme.typography.bodySmall
                )
                if (isGrabbing) {
                    CircularProgressIndicator(
                        modifier = Modifier.size(20.dp),
                        strokeWidth = 2.dp,
                        color = MobilePrimary
                    )
                } else {
                    FilledTonalButton(
                        onClick = onGrab,
                        contentPadding = PaddingValues(horizontal = 12.dp, vertical = 4.dp),
                        colors = ButtonDefaults.filledTonalButtonColors(
                            containerColor = MobilePrimary.copy(alpha = 0.15f),
                            contentColor = MobilePrimary
                        )
                    ) {
                        Icon(Icons.Default.Download, null, Modifier.size(14.dp))
                        Spacer(Modifier.width(4.dp))
                        Text("Grab", style = MaterialTheme.typography.labelSmall)
                    }
                }
            }
        }
    }
}
