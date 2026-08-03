package com.aruvi.tir.ui.components

import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.BoxScope
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.focus.onFocusChanged
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.toArgb
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import com.aruvi.tir.ui.theme.TVCardBackground
import com.aruvi.tir.ui.theme.TVFocusRing
import dev.holtchas.focustrail.compose.FocusTrailBox
import dev.holtchas.focustrail.compose.FocusTrailDefaults
import dev.holtchas.focustrail.compose.FocusTrailShape

/**
 * TV card wrapper: blue focus-trail (moving highlight + resting border +
 * soft glow) from the HoltChas library, 3D tilt, and a material3 Card whose
 * border lights up in [TVFocusRing] while focused.
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
    tiltDegrees: Float = 2f,
    trailColor: Color = TVFocusRing,
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
        staticColor = trailColor.toArgb(),
        trailColor = trailColor.toArgb(),
        baseAlpha = 126,
        glowAlpha = 50,
        highlightAlpha = 255,
        trailLengthRatio = 0.16f,
        minTrailLength = 42.dp,
        drawOppositeTrail = true,
        focusScale = focusScale
    )

    FocusTrailBox(
        modifier = modifier.tiltOnFocus(isFocused, tiltDegrees),
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
            Card(
                modifier = Modifier
                    .fillMaxSize()
                    .padding(contentPadding),
                shape = RoundedCornerShape(contentCornerRadius),
                colors = CardDefaults.cardColors(containerColor = TVCardBackground),
                border = if (isFocused) {
                    BorderStroke(2.dp, trailColor)
                } else {
                    null
                }
            ) {
                Box(modifier = Modifier.fillMaxSize()) {
                    cardContent(this, isFocused)
                }
            }
        }
    }
}
