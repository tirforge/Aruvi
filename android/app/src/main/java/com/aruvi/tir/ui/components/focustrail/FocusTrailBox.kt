/*
 * Copyright (c) 2026 Haocong Xing
 *
 * MIT License
 *
 * Permission is hereby granted, free of charge, to any person obtaining a copy
 * of this software and associated documentation files (the "Software"), to deal
 * in the Software without restriction, including without limitation the rights
 * to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
 * copies of the Software, and to permit persons to whom the Software is
 * furnished to do so, subject to the following conditions:
 *
 * The above copyright notice and this permission notice shall be included in all
 * copies or substantial portions of the Software.
 *
 * THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
 * IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
 * FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
 * AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
 * LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
 * OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
 * SOFTWARE.
 */
package dev.holtchas.focustrail.compose

import android.graphics.LinearGradient
import android.graphics.Paint
import android.graphics.Path
import android.graphics.PathMeasure
import android.graphics.RectF
import android.graphics.Region
import android.graphics.Shader
import android.graphics.Color as AndroidColor
import androidx.compose.animation.core.Animatable
import androidx.compose.animation.core.FastOutSlowInEasing
import androidx.compose.animation.core.LinearEasing
import androidx.compose.animation.core.tween
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.BoxScope
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberUpdatedState
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.graphicsLayer
import androidx.compose.ui.graphics.drawscope.drawIntoCanvas
import androidx.compose.ui.graphics.nativeCanvas
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import kotlinx.coroutines.coroutineScope
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import kotlin.math.max
import kotlin.math.min

/**
 * Shape constants used by Compose focus trails.
 *
 * Compose 焦点流光的形状常量。
 */
object FocusTrailShape {
    /** Rounded-rectangle trail path. 圆角矩形流光路径。 */
    const val ROUND_RECT = 0
    /** Circle trail path. 圆形流光路径。 */
    const val CIRCLE = 1
}

/**
 * Reusable style for [FocusTrailBox]. Size values are stored in pixels.
 *
 * [FocusTrailBox] 的可复用样式。尺寸参数保存为 px，方便在绘制阶段直接使用。
 */
data class FocusTrailStyle(
    val shape: Int = FocusTrailShape.ROUND_RECT,
    val durationMs: Long = 10_000L,
    val startDelayMs: Long = 1_000L,
    val cornerRadiusPx: Float = 40f,
    val borderWidthPx: Float = 5f,
    val staticBorderWidthPx: Float = borderWidthPx,
    val trailPaddingPx: Float = 24f,
    val glowWidthPx: Float = 24f,
    val staticColor: Int = AndroidColor.WHITE,
    val trailColor: Int = AndroidColor.WHITE,
    val baseAlpha: Int = 126,
    val glowAlpha: Int = 50,
    val highlightAlpha: Int = 255,
    val trailLengthRatio: Float = 0.16f,
    val minTrailLengthPx: Float = 42f,
    val drawOppositeTrail: Boolean = true,
    val segmentCount: Int = 1,
    val focusScale: Float = 1.08f
)

/**
 * Dp-friendly presets for common TV focus states.
 *
 * 面向电视焦点场景的默认样式集合，调用侧可以用 Dp 调参。
 */
object FocusTrailDefaults {
    /**
     * Creates a TV card style and converts all Dp values with the current density.
     *
     * 创建电视卡片样式，并使用当前 density 把 Dp 参数转换为 px。
     */
    @Composable
    fun tvCardStyle(
        shape: Int = FocusTrailShape.ROUND_RECT,
        durationMs: Long = 10_000L,
        startDelayMs: Long = 1_000L,
        cornerRadius: Dp = 20.dp,
        borderWidth: Dp = 2.8.dp,
        staticBorderWidth: Dp = borderWidth,
        trailPadding: Dp = 12.dp,
        glowWidth: Dp = 12.dp,
        staticColor: Int = AndroidColor.WHITE,
        trailColor: Int = AndroidColor.WHITE,
        baseAlpha: Int = 126,
        glowAlpha: Int = 50,
        highlightAlpha: Int = 255,
        trailLengthRatio: Float = 0.16f,
        minTrailLength: Dp = 42.dp,
        drawOppositeTrail: Boolean = true,
        segmentCount: Int = 1,
        focusScale: Float = 1.08f
    ): FocusTrailStyle {
        val density = LocalDensity.current
        return with(density) {
            FocusTrailStyle(
                shape = shape,
                durationMs = durationMs,
                startDelayMs = startDelayMs,
                cornerRadiusPx = cornerRadius.toPx(),
                borderWidthPx = borderWidth.toPx(),
                staticBorderWidthPx = staticBorderWidth.toPx(),
                trailPaddingPx = trailPadding.toPx(),
                glowWidthPx = glowWidth.toPx(),
                staticColor = staticColor,
                trailColor = trailColor,
                baseAlpha = baseAlpha,
                glowAlpha = glowAlpha,
                highlightAlpha = highlightAlpha,
                trailLengthRatio = trailLengthRatio,
                minTrailLengthPx = minTrailLength.toPx(),
                drawOppositeTrail = drawOppositeTrail,
                segmentCount = segmentCount,
                focusScale = focusScale
            )
        }
    }
}

/**
 * Recommended Compose entry point using a reusable [FocusTrailStyle].
 *
 * 推荐的 Compose 入口：通过 [FocusTrailStyle] 复用一套焦点流光参数，由调用方用 [active] 控制焦点状态。
 */
@Composable
fun FocusTrailBox(
    modifier: Modifier = Modifier,
    active: Boolean = true,
    style: FocusTrailStyle,
    content: @Composable BoxScope.() -> Unit
) {
    FocusTrailBox(
        modifier = modifier,
        active = active,
        shape = style.shape,
        durationMs = style.durationMs,
        startDelayMs = style.startDelayMs,
        cornerRadiusPx = style.cornerRadiusPx,
        borderWidthPx = style.borderWidthPx,
        staticBorderWidthPx = style.staticBorderWidthPx,
        trailPaddingPx = style.trailPaddingPx,
        glowWidthPx = style.glowWidthPx,
        staticColor = style.staticColor,
        trailColor = style.trailColor,
        baseAlpha = style.baseAlpha,
        glowAlpha = style.glowAlpha,
        highlightAlpha = style.highlightAlpha,
        trailLengthRatio = style.trailLengthRatio,
        minTrailLengthPx = style.minTrailLengthPx,
        drawOppositeTrail = style.drawOppositeTrail,
        segmentCount = style.segmentCount,
        focusScale = style.focusScale,
        content = content
    )
}

/**
 * Low-level Compose focus trail container with direct pixel parameters.
 *
 * 底层 Compose 入口：直接传入 px 参数，适合需要完全自定义或从外部设计系统映射参数的场景。
 */
@Composable
fun FocusTrailBox(
    modifier: Modifier = Modifier,
    active: Boolean = true,
    shape: Int = FocusTrailShape.ROUND_RECT,
    durationMs: Long = 10_000L,
    startDelayMs: Long = 0L,
    cornerRadiusPx: Float = 40f,
    borderWidthPx: Float = 5f,
    staticBorderWidthPx: Float = borderWidthPx,
    trailPaddingPx: Float = borderWidthPx * 4f,
    glowWidthPx: Float = borderWidthPx * 4f,
    staticColor: Int = 0x88FFFFFF.toInt(),
    trailColor: Int = AndroidColor.WHITE,
    baseAlpha: Int = 126,
    glowAlpha: Int = 50,
    highlightAlpha: Int = 255,
    trailLengthRatio: Float = 0.22f,
    minTrailLengthPx: Float = borderWidthPx * 15f,
    drawOppositeTrail: Boolean = true,
    segmentCount: Int = 1,
    focusScale: Float = 1f,
    content: @Composable BoxScope.() -> Unit
) {
    val renderer = remember { FocusTrailRenderer() }
    val progress = remember { Animatable(0f) }
    val baseProgress = remember { Animatable(0f) }
    val trailFadeProgress = remember { Animatable(0f) }
    val scaleProgress = remember { Animatable(1f) }
    val latestDurationMs by rememberUpdatedState(durationMs.toInt().coerceAtLeast(100))

    LaunchedEffect(active, focusScale) {
        scaleProgress.animateTo(
            targetValue = if (active) focusScale.coerceAtLeast(1f) else 1f,
            animationSpec = tween(durationMillis = SCALE_ANIMATION_DURATION_MS, easing = FastOutSlowInEasing)
        )
    }

    LaunchedEffect(active, startDelayMs, durationMs) {
        progress.snapTo(0f)
        baseProgress.snapTo(0f)
        trailFadeProgress.snapTo(0f)
        if (!active) {
            return@LaunchedEffect
        }

        coroutineScope {
            launch {
                delay(startDelayMs.coerceAtLeast(0L))
                baseProgress.animateTo(
                    targetValue = 1f,
                    animationSpec = tween(durationMillis = BASE_BORDER_FADE_DURATION_MS, easing = FastOutSlowInEasing)
                )
            }
            launch {
                delay(startDelayMs.coerceAtLeast(0L) + BASE_BORDER_FADE_DURATION_MS)
                trailFadeProgress.animateTo(
                    targetValue = 1f,
                    animationSpec = tween(durationMillis = TRAIL_FADE_DURATION_MS, easing = FastOutSlowInEasing)
                )
            }
            launch {
                delay(startDelayMs.coerceAtLeast(0L) + BASE_BORDER_FADE_DURATION_MS)
                while (true) {
                    progress.snapTo(0f)
                    progress.animateTo(
                        targetValue = 1f,
                        animationSpec = tween(durationMillis = latestDurationMs, easing = LinearEasing)
                    )
                }
            }
        }
    }

    Box(
        modifier = modifier.graphicsLayer {
            val scale = scaleProgress.value
            scaleX = scale
            scaleY = scale
        }
    ) {
        content()
        Canvas(modifier = Modifier.fillMaxSize()) {
            drawIntoCanvas { canvas ->
                renderer.draw(
                    canvas = canvas.nativeCanvas,
                    width = size.width,
                    height = size.height,
                    shape = shape,
                    progress = progress.value,
                    active = active,
                    baseProgress = baseProgress.value,
                    trailFadeProgress = trailFadeProgress.value,
                    cornerRadius = cornerRadiusPx,
                    borderWidth = borderWidthPx,
                    staticBorderWidth = staticBorderWidthPx,
                    trailPadding = trailPaddingPx,
                    glowWidth = glowWidthPx,
                    staticColor = staticColor,
                    trailColor = trailColor,
                    baseAlpha = baseAlpha,
                    glowAlpha = glowAlpha,
                    highlightAlpha = highlightAlpha,
                    trailLengthRatio = trailLengthRatio,
                    minTrailLength = minTrailLengthPx,
                    drawOppositeTrail = drawOppositeTrail,
                    segmentCount = segmentCount
                )
            }
        }
    }
}

private const val BASE_BORDER_FADE_DURATION_MS = 360
private const val TRAIL_FADE_DURATION_MS = 480
private const val SCALE_ANIMATION_DURATION_MS = 120

private class FocusTrailRenderer {
    private val borderPaint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        style = Paint.Style.STROKE
        strokeCap = Paint.Cap.ROUND
        strokeJoin = Paint.Join.ROUND
    }
    private val trailPaint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        style = Paint.Style.STROKE
        strokeCap = Paint.Cap.BUTT
        strokeJoin = Paint.Join.ROUND
    }
    private val pathRect = RectF()
    private val outerRect = RectF()
    private val cornerArcRect = RectF()
    private val borderPath = Path()
    private val outerTrailPath = Path()
    private val targetClipPath = Path()
    private val segmentPath = Path()
    private val pathMeasure = PathMeasure()
    private val outerPathMeasure = PathMeasure()
    private val segmentStart = FloatArray(2)
    private val segmentEnd = FloatArray(2)
    private val highlightStops = floatArrayOf(0f, 0.26f, 0.42f, 0.58f, 0.74f, 1f)
    private val highlightAlphaFactors = floatArrayOf(0f, 0.42f, 1f, 1f, 0.42f, 0f)

    fun draw(
        canvas: android.graphics.Canvas,
        width: Float,
        height: Float,
        shape: Int,
        progress: Float,
        active: Boolean,
        baseProgress: Float,
        trailFadeProgress: Float,
        cornerRadius: Float,
        borderWidth: Float,
        staticBorderWidth: Float,
        trailPadding: Float,
        glowWidth: Float,
        staticColor: Int,
        trailColor: Int,
        baseAlpha: Int,
        glowAlpha: Int,
        highlightAlpha: Int,
        trailLengthRatio: Float,
        minTrailLength: Float,
        drawOppositeTrail: Boolean,
        segmentCount: Int
    ) {
        val halfStroke = max(borderWidth, staticBorderWidth) / 2f
        val safeTrailPadding = max(trailPadding, max(borderWidth, glowWidth))
        pathRect.set(
            safeTrailPadding + halfStroke,
            safeTrailPadding + halfStroke,
            width - safeTrailPadding - halfStroke,
            height - safeTrailPadding - halfStroke
        )
        if (pathRect.width() <= 0f || pathRect.height() <= 0f) {
            return
        }

        borderPath.reset()
        outerTrailPath.reset()
        targetClipPath.reset()
        if (shape == FocusTrailShape.CIRCLE) {
            val size = min(pathRect.width(), pathRect.height())
            val left = pathRect.centerX() - size / 2f
            val top = pathRect.centerY() - size / 2f
            pathRect.set(left, top, left + size, top + size)
            borderPath.addOval(pathRect, Path.Direction.CW)
            targetClipPath.addOval(pathRect, Path.Direction.CW)
            val outerOffset = borderWidth
            outerRect.set(
                pathRect.left - outerOffset,
                pathRect.top - outerOffset,
                pathRect.right + outerOffset,
                pathRect.bottom + outerOffset
            )
            outerTrailPath.addOval(outerRect, Path.Direction.CW)
        } else {
            addStableRoundRect(borderPath, pathRect, cornerRadius)
            targetClipPath.addRoundRect(pathRect, cornerRadius, cornerRadius, Path.Direction.CW)
            val outerOffset = borderWidth
            outerRect.set(
                pathRect.left - outerOffset,
                pathRect.top - outerOffset,
                pathRect.right + outerOffset,
                pathRect.bottom + outerOffset
            )
            addStableRoundRect(outerTrailPath, outerRect, cornerRadius + outerOffset)
        }

        if (!active) {
            return
        }

        pathMeasure.setPath(borderPath, true)
        outerPathMeasure.setPath(outerTrailPath, true)
        val pathLength = pathMeasure.length
        val outerPathLength = outerPathMeasure.length
        if (pathLength <= 0f || outerPathLength <= 0f) {
            return
        }

        val segmentLength = max(pathLength * trailLengthRatio.coerceIn(0.02f, 0.95f), minTrailLength)
            .coerceAtMost(pathLength * 0.34f)
        val outerSegmentLength = max(outerPathLength * trailLengthRatio.coerceIn(0.02f, 0.95f), minTrailLength)
            .coerceAtMost(outerPathLength * 0.34f)

        if (trailFadeProgress > 0f) {
            val saveCount = canvas.save()
            canvas.clipPath(targetClipPath, Region.Op.DIFFERENCE)
            drawTrail(
                canvas = canvas,
                measure = outerPathMeasure,
                pathLength = outerPathLength,
                progress = progress,
                strokeWidth = glowWidth,
                trailColor = trailColor,
                alpha = (glowAlpha.coerceIn(0, 255) * trailFadeProgress.coerceIn(0f, 1f)).toInt(),
                segmentLength = outerSegmentLength,
                drawOppositeTrail = drawOppositeTrail,
                segmentCount = segmentCount
            )
            canvas.restoreToCount(saveCount)
        }

        if (baseProgress > 0f) {
            borderPaint.strokeWidth = staticBorderWidth
            borderPaint.color = withAlpha(
                staticColor,
                (baseAlpha.coerceIn(0, 255) * baseProgress.coerceIn(0f, 1f)).toInt()
            )
            canvas.drawPath(borderPath, borderPaint)
        }
        if (trailFadeProgress > 0f) {
            drawTrail(
                canvas = canvas,
                measure = pathMeasure,
                pathLength = pathLength,
                progress = progress,
                strokeWidth = borderWidth,
                trailColor = trailColor,
                alpha = (highlightAlpha.coerceIn(0, 255) * trailFadeProgress.coerceIn(0f, 1f)).toInt(),
                segmentLength = segmentLength,
                drawOppositeTrail = drawOppositeTrail,
                segmentCount = segmentCount
            )
        }
    }

    private fun drawTrail(
        canvas: android.graphics.Canvas,
        measure: PathMeasure,
        pathLength: Float,
        progress: Float,
        strokeWidth: Float,
        trailColor: Int,
        alpha: Int,
        segmentLength: Float,
        drawOppositeTrail: Boolean,
        segmentCount: Int
    ) {
        trailPaint.strokeWidth = strokeWidth
        val safeSegmentCount = max(1, segmentCount)
        for (i in 0 until safeSegmentCount) {
            val center = normalize(progress * pathLength + pathLength * i / safeSegmentCount, pathLength)
            drawSegment(canvas, measure, pathLength, center, segmentLength, trailColor, alpha)
            if (drawOppositeTrail) {
                drawSegment(
                    canvas,
                    measure,
                    pathLength,
                    normalize(center + pathLength / 2f, pathLength),
                    segmentLength,
                    trailColor,
                    alpha
                )
            }
        }
    }

    private fun drawSegment(
        canvas: android.graphics.Canvas,
        measure: PathMeasure,
        pathLength: Float,
        center: Float,
        segmentLength: Float,
        trailColor: Int,
        alpha: Int
    ) {
        val half = min(segmentLength, pathLength - 1f) / 2f
        val start = center - half
        val end = center + half
        if (start < 0f) {
            val split = -start / (half * 2f)
            drawRange(canvas, measure, pathLength + start, pathLength, 0f, split, trailColor, alpha)
            drawRange(canvas, measure, 0f, end, split, 1f, trailColor, alpha)
        } else if (end > pathLength) {
            val split = (pathLength - start) / (half * 2f)
            drawRange(canvas, measure, start, pathLength, 0f, split, trailColor, alpha)
            drawRange(canvas, measure, 0f, end - pathLength, split, 1f, trailColor, alpha)
        } else {
            drawRange(canvas, measure, start, end, 0f, 1f, trailColor, alpha)
        }
    }

    private fun drawRange(
        canvas: android.graphics.Canvas,
        measure: PathMeasure,
        start: Float,
        end: Float,
        startFraction: Float,
        endFraction: Float,
        trailColor: Int,
        alpha: Int
    ) {
        if (end - start <= 0.5f) {
            return
        }
        val distance = end - start
        val slices = max(1, min(24, kotlin.math.ceil(distance / max(1f, trailPaint.strokeWidth * 1.5f)).toInt()))
        for (i in 0 until slices) {
            val from = i / slices.toFloat()
            val to = (i + 1) / slices.toFloat()
            drawRangeSlice(
                canvas,
                measure,
                start + distance * from,
                start + distance * to,
                lerp(startFraction, endFraction, from),
                lerp(startFraction, endFraction, to),
                trailColor,
                alpha
            )
        }
    }

    private fun drawRangeSlice(
        canvas: android.graphics.Canvas,
        measure: PathMeasure,
        start: Float,
        end: Float,
        startFraction: Float,
        endFraction: Float,
        trailColor: Int,
        alpha: Int
    ) {
        if (end - start <= 0.5f) {
            return
        }
        segmentPath.reset()
        measure.getSegment(start, end, segmentPath, true)
        if (segmentPath.isEmpty) {
            return
        }
        val safeEnd = min(end, measure.length - 0.5f)
        measure.getPosTan(start, segmentStart, null)
        measure.getPosTan(safeEnd, segmentEnd, null)
        trailPaint.shader = LinearGradient(
            segmentStart[0],
            segmentStart[1],
            segmentEnd[0],
            segmentEnd[1],
            buildSegmentColors(trailColor, alpha, startFraction, endFraction),
            buildSegmentStops(startFraction, endFraction),
            Shader.TileMode.CLAMP
        )
        canvas.drawPath(segmentPath, trailPaint)
        trailPaint.shader = null
    }

    private fun buildSegmentColors(trailColor: Int, alpha: Int, startFraction: Float, endFraction: Float): IntArray {
        val start = startFraction.coerceIn(0f, 1f)
        val end = endFraction.coerceIn(0f, 1f)
        val colors = ArrayList<Int>(highlightStops.size + 2)
        colors.add(colorAtHighlightFraction(trailColor, alpha, start))
        for (stop in highlightStops) {
            if (stop > start && stop < end) {
                colors.add(colorAtHighlightFraction(trailColor, alpha, stop))
            }
        }
        colors.add(colorAtHighlightFraction(trailColor, alpha, end))
        return colors.toIntArray()
    }

    private fun buildSegmentStops(startFraction: Float, endFraction: Float): FloatArray {
        val start = startFraction.coerceIn(0f, 1f)
        val end = endFraction.coerceIn(0f, 1f)
        val span = max(0.001f, end - start)
        val stops = ArrayList<Float>(highlightStops.size + 2)
        stops.add(0f)
        for (stop in highlightStops) {
            if (stop > start && stop < end) {
                stops.add((stop - start) / span)
            }
        }
        stops.add(1f)
        return stops.toFloatArray()
    }

    private fun colorAtHighlightFraction(trailColor: Int, alpha: Int, fraction: Float): Int {
        val clampedFraction = fraction.coerceIn(0f, 1f)
        var factor = highlightAlphaFactors.last()
        for (i in 1 until highlightStops.size) {
            val previousStop = highlightStops[i - 1]
            val nextStop = highlightStops[i]
            if (clampedFraction <= nextStop) {
                val localFraction = if (nextStop == previousStop) {
                    0f
                } else {
                    (clampedFraction - previousStop) / (nextStop - previousStop)
                }
                factor = lerp(highlightAlphaFactors[i - 1], highlightAlphaFactors[i], localFraction)
                break
            }
        }
        val colorAlpha = min(AndroidColor.alpha(trailColor), alpha)
        val resolvedAlpha = (colorAlpha * factor.coerceIn(0f, 1f)).toInt()
        return (trailColor and 0x00FFFFFF) or (resolvedAlpha shl 24)
    }

    private fun withAlpha(color: Int, alpha: Int): Int {
        return (color and 0x00FFFFFF) or (min(AndroidColor.alpha(color), alpha).coerceIn(0, 255) shl 24)
    }

    private fun addStableRoundRect(path: Path, rect: RectF, radius: Float) {
        val safeRadius = max(0f, min(radius, min(rect.width(), rect.height()) / 2f))
        if (safeRadius <= 0f) {
            path.addRect(rect, Path.Direction.CW)
            return
        }

        path.moveTo(rect.left + safeRadius, rect.top)
        path.lineTo(rect.right - safeRadius, rect.top)
        cornerArcRect.set(rect.right - safeRadius * 2f, rect.top, rect.right, rect.top + safeRadius * 2f)
        path.arcTo(cornerArcRect, -90f, 90f)
        path.lineTo(rect.right, rect.bottom - safeRadius)
        cornerArcRect.set(rect.right - safeRadius * 2f, rect.bottom - safeRadius * 2f, rect.right, rect.bottom)
        path.arcTo(cornerArcRect, 0f, 90f)
        path.lineTo(rect.left + safeRadius, rect.bottom)
        cornerArcRect.set(rect.left, rect.bottom - safeRadius * 2f, rect.left + safeRadius * 2f, rect.bottom)
        path.arcTo(cornerArcRect, 90f, 90f)
        path.lineTo(rect.left, rect.top + safeRadius)
        cornerArcRect.set(rect.left, rect.top, rect.left + safeRadius * 2f, rect.top + safeRadius * 2f)
        path.arcTo(cornerArcRect, 180f, 90f)
        path.close()
    }

    private fun normalize(value: Float, max: Float): Float {
        val result = value % max
        return if (result < 0f) result + max else result
    }

    private fun lerp(start: Float, end: Float, fraction: Float): Float {
        return start + (end - start) * fraction
    }
}
