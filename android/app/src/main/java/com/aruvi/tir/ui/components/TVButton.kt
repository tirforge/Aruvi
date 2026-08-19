package com.aruvi.tir.ui.components

import androidx.compose.animation.core.animateFloatAsState
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.scale
import androidx.compose.ui.focus.onFocusChanged
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.unit.dp
import androidx.tv.material3.Button
import androidx.tv.material3.ButtonDefaults
import androidx.compose.ui.graphics.graphicsLayer
import androidx.tv.material3.ExperimentalTvMaterial3Api
import com.aruvi.tir.ui.theme.*

/**
 * TV-optimized button with focus states.
 */
@OptIn(ExperimentalTvMaterial3Api::class)
@Composable
fun TVButton(
    text: String,
    onClick: () -> Unit,
    modifier: Modifier = Modifier,
    enabled: Boolean = true,
    isPrimary: Boolean = true
) {
    var isFocused by remember { mutableStateOf(false) }
    val scale by animateFloatAsState(
        targetValue = if (isFocused) 1.05f else 1f,
        label = "buttonScale"
    )

    Button(
        onClick = onClick,
        enabled = enabled,
        modifier = modifier
            .graphicsLayer {
                scaleX = scale
                scaleY = scale
            }
            .onFocusChanged { isFocused = it.isFocused },
        colors = ButtonDefaults.colors(
            containerColor = if (isPrimary) TVPrimary else Color.White.copy(alpha = 0.08f),
            contentColor = if (isPrimary) Color.White else TVTextPrimary,
            focusedContainerColor = if (isPrimary) TVPrimaryVariant else TVCardFocused,
            focusedContentColor = Color.White,
            disabledContainerColor = TVSurfaceVariant.copy(alpha = 0.5f),
            disabledContentColor = TVTextDisabled
        ),
        shape = ButtonDefaults.shape(shape = RoundedCornerShape(8.dp))
    ) {
        Text(
            text = text,
            style = MaterialTheme.typography.labelLarge,
            color = if (isFocused) Color.White else if (isPrimary) Color.White else TVTextPrimary,
            modifier = Modifier.padding(horizontal = 16.dp, vertical = 8.dp)
        )
    }
}

/**
 * Icon button for TV (e.g., in player controls).
 */
@OptIn(ExperimentalTvMaterial3Api::class)
@Composable
fun TVIconButton(
    icon: @Composable () -> Unit,
    onClick: () -> Unit,
    modifier: Modifier = Modifier,
    enabled: Boolean = true
) {
    var isFocused by remember { mutableStateOf(false) }
    val scale by animateFloatAsState(
        targetValue = if (isFocused) 1.15f else 1f,
        label = "iconButtonScale"
    )

    Button(
        onClick = onClick,
        enabled = enabled,
        modifier = modifier
            .size(64.dp)
            .graphicsLayer {
                scaleX = scale
                scaleY = scale
            }
            .onFocusChanged { isFocused = it.isFocused },
        colors = ButtonDefaults.colors(
            containerColor = if (isFocused) TVCardFocused else TVSurface.copy(alpha = 0.6f),
            focusedContainerColor = TVCardFocused
        ),
        shape = ButtonDefaults.shape(shape = RoundedCornerShape(50))
    ) {
        Box(
            modifier = Modifier.fillMaxSize(),
            contentAlignment = Alignment.Center
        ) {
            icon()
        }
    }
}
