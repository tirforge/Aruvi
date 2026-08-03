package com.aruvi.tir.ui.components

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.BoxScope
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.focus.onFocusChanged
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import dev.holtchas.focustrail.compose.FocusTrailBox
import dev.holtchas.focustrail.compose.FocusTrailDefaults
import dev.holtchas.focustrail.compose.FocusTrailShape

/**
 * TV card wrapper matching the HoltChas focus-trail demo style:
 * white moving highlight trail + white resting border + soft outer glow
 * + scale, applied by the library itself.
 *
 * Deliberately NO tv-material3 Card (it draws its own white focus border +
 * glow), NO 3D tilt (extreme `cameraDistance` caused screen shake), and NO
 * alpha dim — the demo does none of these.
 */
@Composable
fun FocusedCard(
    onClick: () -> Unit,
    modifier: Modifier = Modifier,
    cornerRadius: Dp = 20.dp,
    contentCornerRadius: Dp = 16.dp,
    contentPadding: Dp = 16.dp,
    focusScale: Float = 1.08f,
    trailPadding: Dp = 12.dp,
    cardContent: @Composable BoxScope.(isFocused: Boolean) -> Unit
) {
    val context = LocalContext.current
    var isFocused by remember { mutableStateOf(false) }

    val style = FocusTrailDefaults.tvCardStyle(
        shape = FocusTrailShape.ROUND_RECT,
        durationMs = 10_000L,
        startDelayMs = 1_000L,
        cornerRadius = cornerRadius,
        borderWidth = 2.8.dp,
        staticBorderWidth = 2.8.dp,
        trailPadding = trailPadding,
        glowWidth = 12.dp,
        staticColor = android.graphics.Color.WHITE,
        trailColor = android.graphics.Color.WHITE,
        baseAlpha = 126,
        glowAlpha = 50,
        highlightAlpha = 255,
        trailLengthRatio = 0.16f,
        minTrailLength = 42.dp,
        drawOppositeTrail = true,
        focusScale = focusScale
    )

    FocusTrailBox(
        modifier = modifier,
        active = isFocused,
        style = style
    ) {
        Box(
            modifier = Modifier
                .fillMaxSize()
                .clickable {
                    TvSound.click(context)
                    onClick()
                }
                .onFocusChanged { state ->
                    if (state.isFocused && !isFocused) {
                        TvSound.navigate(context)
                    }
                    isFocused = state.isFocused
                }
        ) {
            Box(
                modifier = Modifier
                    .fillMaxSize()
                    .padding(contentPadding)
                    .clip(RoundedCornerShape(contentCornerRadius))
            ) {
                cardContent(this, isFocused)
            }
        }
    }
}
