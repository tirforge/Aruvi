package com.aruvi.tir.ui.components

import androidx.compose.animation.core.LinearEasing
import androidx.compose.animation.core.animateFloat
import androidx.compose.animation.core.infiniteRepeatable
import androidx.compose.animation.core.rememberInfiniteTransition
import androidx.compose.animation.core.tween
import androidx.compose.foundation.layout.Box
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.drawBehind
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import com.aruvi.tir.ui.theme.TVBackground
import com.aruvi.tir.ui.theme.TVPrimary
import com.aruvi.tir.ui.theme.TVSecondary
import com.aruvi.tir.ui.theme.TVSurface
import kotlin.math.PI
import kotlin.math.cos
import kotlin.math.max
import kotlin.math.sin

/**
 * "Gif-like" animated background for TV screens: brand-blue radial glows
 * drifting slowly across a dark gradient. Runs entirely in the draw phase
 * ([Modifier.drawBehind]) so screen content never recomposes.
 */
@Composable
fun TvAnimatedBackground(modifier: Modifier = Modifier) {
    val transition = rememberInfiniteTransition(label = "tvBg")
    val angle by transition.animateFloat(
        initialValue = 0f,
        targetValue = 360f,
        animationSpec = infiniteRepeatable(
            animation = tween(durationMillis = 24_000, easing = LinearEasing)
        ),
        label = "bgAngle"
    )
    val angle2 by transition.animateFloat(
        initialValue = 120f,
        targetValue = 480f,
        animationSpec = infiniteRepeatable(
            animation = tween(durationMillis = 19_000, easing = LinearEasing)
        ),
        label = "bgAngle2"
    )

    Box(
        modifier = modifier.drawBehind {
            val w = size.width
            val h = size.height
            val diagonal = max(w, h)

            drawRect(
                brush = Brush.verticalGradient(
                    colors = listOf(TVBackground, TVSurface, TVBackground)
                )
            )

            val rad1 = angle * PI.toFloat() / 180f
            val rad2 = angle2 * PI.toFloat() / 180f
            val center1 = Offset(
                w * (0.5f + 0.6f * cos(rad1)),
                h * (0.5f + 0.6f * sin(rad1))
            )
            val center2 = Offset(
                w * (0.5f + 0.6f * cos(rad2)),
                h * (0.5f + 0.6f * sin(rad2))
            )

            drawCircle(
                brush = Brush.radialGradient(
                    colors = listOf(TVPrimary.copy(alpha = 0.10f), Color.Transparent),
                    center = center1,
                    radius = diagonal * 0.9f
                ),
                radius = diagonal * 0.9f,
                center = center1
            )
            drawCircle(
                brush = Brush.radialGradient(
                    colors = listOf(TVSecondary.copy(alpha = 0.07f), Color.Transparent),
                    center = center2,
                    radius = diagonal * 0.7f
                ),
                radius = diagonal * 0.7f,
                center = center2
            )
        }
    )
}
