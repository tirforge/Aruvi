package com.aruvi.tir.ui.components

import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.graphicsLayer

/**
 * Tilts the card in 3D toward the nearest edge when focused, using a safe
 * camera distance so the effect stays stable (an extreme `cameraDistance`
 * previously caused screen shake).
 */
fun Modifier.tiltOnFocus(
    isFocused: Boolean,
    maxDegrees: Float = 2f
): Modifier = graphicsLayer {
    val degrees = if (isFocused) maxDegrees.coerceIn(0f, 8f) else 0f
    rotationX = degrees
    rotationY = -degrees
    cameraDistance = 12f * density
}
