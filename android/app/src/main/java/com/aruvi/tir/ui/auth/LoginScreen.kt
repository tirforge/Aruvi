package com.aruvi.tir.ui.auth

import androidx.compose.animation.core.*
import androidx.compose.foundation.Image
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.asImageBitmap
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.res.painterResource
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.hilt.navigation.compose.hiltViewModel
import com.aruvi.tir.ui.components.TVButton
import com.aruvi.tir.ui.theme.*

@Composable
fun LoginScreen(
    onLoginSuccess: () -> Unit,
    viewModel: LoginViewModel = hiltViewModel()
) {
    val uiState by viewModel.uiState.collectAsState()

    val infiniteTransition = rememberInfiniteTransition(label = "bgGradient")
    val gradientOffset by infiniteTransition.animateFloat(
        initialValue = 0f,
        targetValue = 1f,
        animationSpec = infiniteRepeatable(
            animation = tween(6000, easing = LinearEasing),
            repeatMode = RepeatMode.Reverse
        ),
        label = "gradientShift"
    )

    LaunchedEffect(uiState.isLoggedIn) {
        if (uiState.isLoggedIn) {
            onLoginSuccess()
        }
    }

    Box(
        modifier = Modifier
            .fillMaxSize()
            .background(
                Brush.verticalGradient(
                    colors = listOf(
                        TVBackground,
                        Color(0xFF0A1628).copy(alpha = 0.3f + 0.2f * gradientOffset),
                        TVBackground
                    )
                )
            ),
        contentAlignment = Alignment.Center
    ) {
        Column(
            modifier = Modifier
                .fillMaxWidth()
                .padding(horizontal = 64.dp, vertical = 32.dp),
            horizontalAlignment = Alignment.CenterHorizontally
        ) {
            Box(
                contentAlignment = Alignment.Center,
                modifier = Modifier
                    .size(56.dp)
                    .background(
                        color = TVPrimary.copy(alpha = 0.12f),
                        shape = CircleShape
                    )
            ) {
                Image(
                    painter = painterResource(id = com.aruvi.tir.R.drawable.app_logo),
                    contentDescription = null,
                    modifier = Modifier.size(40.dp),
                    contentScale = ContentScale.Fit
                )
            }

            Spacer(modifier = Modifier.height(10.dp))

            Text(
                text = "Aruvi",
                style = MaterialTheme.typography.headlineLarge,
                color = TVTextPrimary,
                fontWeight = FontWeight.Bold
            )

            Spacer(modifier = Modifier.height(24.dp))

            when {
                uiState.isLoading -> {
                    CircularProgressIndicator(
                        modifier = Modifier.size(56.dp),
                        color = TVPrimary,
                        strokeWidth = 4.dp,
                        trackColor = TVPrimary.copy(alpha = 0.12f)
                    )
                    Spacer(modifier = Modifier.height(24.dp))
                    Text(
                        text = "Generating login code...",
                        style = MaterialTheme.typography.titleMedium,
                        color = TVTextSecondary
                    )
                }

                uiState.error != null -> {
                    Box(
                        contentAlignment = Alignment.Center,
                        modifier = Modifier
                            .size(64.dp)
                            .background(TVError.copy(alpha = 0.1f), CircleShape)
                    ) {
                        Icon(
                            imageVector = Icons.Default.ErrorOutline,
                            contentDescription = null,
                            tint = TVError,
                            modifier = Modifier.size(36.dp)
                        )
                    }
                    Spacer(modifier = Modifier.height(16.dp))
                    Text(
                        text = uiState.error!!,
                        style = MaterialTheme.typography.titleMedium,
                        color = TVError,
                        textAlign = TextAlign.Center
                    )
                    Spacer(modifier = Modifier.height(32.dp))
                    TVButton(
                        text = "Try Again",
                        onClick = { viewModel.generateLoginCode() }
                    )
                }

                uiState.loginCode != null -> {
                    Row(
                        modifier = Modifier
                            .fillMaxWidth()
                            .height(400.dp),
                        horizontalArrangement = Arrangement.spacedBy(32.dp),
                        verticalAlignment = Alignment.CenterVertically
                    ) {
                        // LEFT: Login code
                        Column(
                            modifier = Modifier.weight(1f).fillMaxHeight(),
                            horizontalAlignment = Alignment.CenterHorizontally,
                            verticalArrangement = Arrangement.Center
                        ) {
                            Text(
                                text = "Login Code",
                                style = MaterialTheme.typography.titleLarge,
                                color = TVTextSecondary
                            )

                            Spacer(modifier = Modifier.height(20.dp))

                            Surface(
                                color = Color.White.copy(alpha = 0.06f),
                                shape = RoundedCornerShape(20.dp),
                                modifier = Modifier.border(
                                    width = 1.dp,
                                    brush = Brush.linearGradient(
                                        listOf(
                                            Color.White.copy(alpha = 0.12f),
                                            Color.White.copy(alpha = 0.04f)
                                        )
                                    ),
                                    shape = RoundedCornerShape(20.dp)
                                )
                            ) {
                                Box(
                                    modifier = Modifier.padding(horizontal = 48.dp, vertical = 24.dp)
                                ) {
                                    Text(
                                        text = uiState.loginCode!!,
                                        style = MaterialTheme.typography.displayLarge.copy(
                                            fontSize = 52.sp,
                                            letterSpacing = 8.sp
                                        ),
                                        color = TVPrimary,
                                        fontWeight = FontWeight.Bold
                                    )
                                }
                            }

                            Spacer(modifier = Modifier.height(20.dp))

                            if (uiState.isPolling) {
                                val dotAlpha1 by infiniteTransition.animateFloat(
                                    initialValue = 0.3f, targetValue = 1f,
                                    animationSpec = infiniteRepeatable(
                                        animation = tween(600),
                                        repeatMode = RepeatMode.Reverse
                                    ), label = "dot1"
                                )
                                val dotAlpha2 by infiniteTransition.animateFloat(
                                    initialValue = 0.3f, targetValue = 1f,
                                    animationSpec = infiniteRepeatable(
                                        animation = tween(600, delayMillis = 200),
                                        repeatMode = RepeatMode.Reverse
                                    ), label = "dot2"
                                )
                                val dotAlpha3 by infiniteTransition.animateFloat(
                                    initialValue = 0.3f, targetValue = 1f,
                                    animationSpec = infiniteRepeatable(
                                        animation = tween(600, delayMillis = 400),
                                        repeatMode = RepeatMode.Reverse
                                    ), label = "dot3"
                                )

                                Row(verticalAlignment = Alignment.CenterVertically) {
                                    CircularProgressIndicator(
                                        modifier = Modifier.size(20.dp),
                                        color = TVSecondary,
                                        strokeWidth = 2.dp,
                                        trackColor = TVSecondary.copy(alpha = 0.12f)
                                    )
                                    Spacer(modifier = Modifier.width(12.dp))
                                    Text(
                                        text = "Waiting for confirmation",
                                        style = MaterialTheme.typography.bodyMedium,
                                        color = TVTextSecondary
                                    )
                                    Row(modifier = Modifier.padding(start = 2.dp)) {
                                        Text(".", color = TVSecondary.copy(alpha = dotAlpha1), fontSize = 18.sp, fontWeight = FontWeight.Bold)
                                        Text(".", color = TVSecondary.copy(alpha = dotAlpha2), fontSize = 18.sp, fontWeight = FontWeight.Bold)
                                        Text(".", color = TVSecondary.copy(alpha = dotAlpha3), fontSize = 18.sp, fontWeight = FontWeight.Bold)
                                    }
                                }
                            }

                            Spacer(modifier = Modifier.height(20.dp))

                            TVButton(
                                text = "Generate New Code",
                                onClick = { viewModel.generateLoginCode() },
                                isPrimary = false
                            )

                            Spacer(modifier = Modifier.height(24.dp))

                            Text(
                                text = "Open Telegram, send /login ${uiState.loginCode} to @${uiState.botUsername.ifBlank { "Aaruvi_movie_bot" }}",
                                style = MaterialTheme.typography.bodyMedium,
                                color = TVTextSecondary,
                                textAlign = TextAlign.Center
                            )
                        }

                        // RIGHT: QR code
                        if (uiState.qrCodeBitmap != null) {
                            Column(
                                modifier = Modifier.weight(1f).fillMaxHeight(),
                                horizontalAlignment = Alignment.CenterHorizontally,
                                verticalArrangement = Arrangement.Center
                            ) {
                                Surface(
                                    color = Color.White,
                                    shape = RoundedCornerShape(16.dp),
                                    modifier = Modifier
                                        .fillMaxWidth(0.7f)
                                        .aspectRatio(1f)
                                ) {
                                    Image(
                                        bitmap = uiState.qrCodeBitmap!!.asImageBitmap(),
                                        contentDescription = "Scan to login",
                                        modifier = Modifier.padding(16.dp),
                                        contentScale = ContentScale.Fit
                                    )
                                }
                                Spacer(modifier = Modifier.height(16.dp))
                                Text(
                                    text = "Scan to connect",
                                    style = MaterialTheme.typography.titleMedium,
                                    color = TVTextSecondary
                                )
                            }
                        }
                    }
                }
            }

            if (uiState.debugLog.isNotEmpty()) {
                Spacer(modifier = Modifier.height(16.dp))
                Text(
                    text = uiState.debugLog,
                    style = MaterialTheme.typography.bodySmall,
                    color = TVTextSecondary.copy(alpha = 0.5f),
                    modifier = Modifier.padding(16.dp)
                )
            }
        }
    }
}
