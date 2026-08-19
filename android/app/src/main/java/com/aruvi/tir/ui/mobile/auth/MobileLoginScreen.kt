package com.aruvi.tir.ui.mobile.auth

import androidx.compose.animation.AnimatedVisibility
import androidx.compose.animation.expandVertically
import androidx.compose.animation.shrinkVertically
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.LiveTv
import androidx.compose.material.icons.filled.Refresh
import androidx.compose.material.icons.filled.Settings
import androidx.compose.material.icons.automirrored.filled.Send
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.res.painterResource
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.foundation.Image
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.zIndex
import com.aruvi.tir.R
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.hilt.navigation.compose.hiltViewModel
import com.aruvi.tir.ui.auth.LoginViewModel
import com.aruvi.tir.ui.theme.*

@Composable
fun MobileLoginScreen(
    viewModel: LoginViewModel = hiltViewModel(),
    onLoginSuccess: () -> Unit
) {
    val uiState by viewModel.uiState.collectAsState()
    val context = androidx.compose.ui.platform.LocalContext.current

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
                        MobileBackground,
                        Color(0xFF101420),
                        MobileBackground
                    )
                )
            )
    ) {
        // Settings Button (Top Right) — zIndex ensures it stays above the scroll layer
        IconButton(
            onClick = { viewModel.toggleServerConfig() },
            modifier = Modifier
                .align(Alignment.TopEnd)
                .zIndex(1f)
                .padding(16.dp)
                .statusBarsPadding()
                .size(48.dp)
        ) {
            Icon(
                imageVector = Icons.Default.Settings,
                contentDescription = "Server Settings",
                tint = if (uiState.showServerConfig) MobilePrimary else Color.White.copy(alpha = 0.6f)
            )
        }

        Column(
            modifier = Modifier
                .fillMaxSize()
                .padding(horizontal = 32.dp)
                .verticalScroll(androidx.compose.foundation.rememberScrollState()),
            horizontalAlignment = Alignment.CenterHorizontally,
            verticalArrangement = Arrangement.Center
        ) {
            // App Logo
            Surface(
                modifier = Modifier.size(80.dp),
                shape = CircleShape,
                color = MobilePrimary.copy(alpha = 0.1f),
                border = androidx.compose.foundation.BorderStroke(1.dp, MobilePrimary.copy(alpha = 0.2f))
            ) {
                Box(contentAlignment = Alignment.Center) {
                    Image(
                        painter = painterResource(id = R.drawable.app_logo),
                        contentDescription = null,
                        modifier = Modifier.size(60.dp),
                        contentScale = ContentScale.Fit
                    )
                }
            }

            Spacer(modifier = Modifier.height(24.dp))
            
            Text(
                text = "Aruvi",
                style = MaterialTheme.typography.headlineLarge,
                color = Color.White,
                fontWeight = FontWeight.Bold
            )
            
            Text(
                text = "Secure Media Streaming",
                style = MaterialTheme.typography.bodyMedium,
                color = Color.White.copy(alpha = 0.5f)
            )

            Spacer(modifier = Modifier.height(40.dp))

            // Server Configuration (Collapsible)
            AnimatedVisibility(
                visible = uiState.showServerConfig,
                enter = expandVertically(),
                exit = shrinkVertically()
            ) {
                GlassmorphismSurface(
                    modifier = Modifier
                        .fillMaxWidth()
                        .padding(bottom = 32.dp),
                    shape = RoundedCornerShape(20.dp)
                ) {
                    Column(
                        modifier = Modifier.padding(20.dp)
                    ) {
                        Text(
                            text = "Server Settings",
                            style = MaterialTheme.typography.titleMedium,
                            color = Color.White,
                            fontWeight = FontWeight.SemiBold
                        )
                        
                        Spacer(modifier = Modifier.height(16.dp))

                        OutlinedTextField(
                            value = uiState.serverUrl,
                            onValueChange = { viewModel.updateServerUrl(it) },
                            label = { Text("Server URL", color = Color.White.copy(alpha = 0.6f)) },
                            placeholder = { Text("http://your-server:7680") },
                            singleLine = true,
                            colors = OutlinedTextFieldDefaults.colors(
                                focusedTextColor = Color.White,
                                unfocusedTextColor = Color.White,
                                focusedBorderColor = MobilePrimary,
                                unfocusedBorderColor = Color.White.copy(alpha = 0.2f)
                            ),
                            shape = RoundedCornerShape(12.dp),
                            modifier = Modifier.fillMaxWidth()
                        )
                        
                        // Bot info is now fetched automatically
                        if (uiState.botUsername.isNotEmpty()) {
                            Spacer(modifier = Modifier.height(12.dp))
                            Text(
                                text = "Connected to @${uiState.botUsername}",
                                style = MaterialTheme.typography.bodySmall,
                                color = MobilePrimary.copy(alpha = 0.8f),
                                modifier = Modifier.padding(start = 4.dp)
                            )
                        }
                        
                        Spacer(modifier = Modifier.height(20.dp))
                        
                        Button(
                            onClick = { viewModel.saveAndRestart() },
                            modifier = Modifier.fillMaxWidth(),
                            colors = ButtonDefaults.buttonColors(containerColor = MobilePrimary),
                            shape = RoundedCornerShape(12.dp)
                        ) {
                            Icon(Icons.Default.Refresh, null, modifier = Modifier.size(18.dp))
                            Spacer(modifier = Modifier.width(8.dp))
                            Text("Save & Restart", fontWeight = FontWeight.Bold)
                        }
                    }
                }
            }

            if (uiState.isLoading) {
                CircularProgressIndicator(color = MobilePrimary)
                Spacer(modifier = Modifier.height(16.dp))
                Text("Preparing authentication...", color = Color.White.copy(alpha = 0.7f))
            } else if (uiState.loginCode != null) {
                // Instruction
                Text(
                    text = "Confirm in Telegram",
                    style = MaterialTheme.typography.titleLarge,
                    color = Color.White,
                    fontWeight = FontWeight.Bold
                )
                
                Spacer(modifier = Modifier.height(24.dp))

                // Login Code Card
                GlassmorphismSurface(
                    shape = RoundedCornerShape(24.dp),
                    borderColor = MobilePrimary.copy(alpha = 0.3f)
                ) {
                    Column(
                        modifier = Modifier.padding(horizontal = 48.dp, vertical = 24.dp),
                        horizontalAlignment = Alignment.CenterHorizontally
                    ) {
                        Text(
                            text = uiState.loginCode!!,
                            style = MaterialTheme.typography.displayLarge.copy(
                                fontSize = 42.sp,
                                letterSpacing = 4.sp,
                                fontWeight = FontWeight.Black
                            ),
                            color = MobilePrimary,
                            maxLines = 1,
                            softWrap = false
                        )
                        
                        Spacer(modifier = Modifier.height(8.dp))
                        
                        Text(
                            text = "Expires in 5 minutes",
                            style = MaterialTheme.typography.labelMedium,
                            color = Color.White.copy(alpha = 0.4f)
                        )
                    }
                }
                
                Spacer(modifier = Modifier.height(32.dp))
                
                // Deep Link Button
                Button(
                    onClick = {
                        val bot = uiState.botUsername.ifBlank { "Aaruvi_movie_bot" }
                        val intent = android.content.Intent(
                            android.content.Intent.ACTION_VIEW,
                            android.net.Uri.parse("https://t.me/$bot?start=${uiState.loginCode}")
                        )
                        try {
                            context.startActivity(intent)
                        } catch (e: Exception) {
                            android.widget.Toast.makeText(context, "Could not open Telegram", android.widget.Toast.LENGTH_SHORT).show()
                        }
                    },
                    modifier = Modifier.fillMaxWidth().height(56.dp),
                    colors = ButtonDefaults.buttonColors(containerColor = Color.White.copy(alpha = 0.05f)),
                    shape = RoundedCornerShape(16.dp),
                    border = androidx.compose.foundation.BorderStroke(1.dp, Color.White.copy(alpha = 0.1f))
                ) {
                    Icon(
                        imageVector = Icons.AutoMirrored.Filled.Send, 
                        contentDescription = null,
                        tint = Color.White,
                        modifier = Modifier.size(20.dp)
                    )
                    Spacer(modifier = Modifier.width(12.dp))
                    Text("Open @${uiState.botUsername.ifBlank { "Aaruvi_movie_bot" }}", color = Color.White)
                }
                
                Spacer(modifier = Modifier.height(24.dp))
                
                if (uiState.isPolling) {
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        CircularProgressIndicator(
                            modifier = Modifier.size(16.dp), 
                            strokeWidth = 2.dp,
                            color = MobileSecondary
                        )
                        Spacer(modifier = Modifier.width(12.dp))
                        Text(
                            text = "Waiting for confirmation...", 
                            style = MaterialTheme.typography.bodyMedium,
                            color = Color.White.copy(alpha = 0.6f)
                        )
                    }
                }
                
                Spacer(modifier = Modifier.height(16.dp))
                
                TextButton(onClick = { viewModel.generateLoginCode() }) {
                    Text("Generate New Code", color = Color.White.copy(alpha = 0.4f))
                }
            }

            if (uiState.error != null) {
                Spacer(modifier = Modifier.height(24.dp))
                Text(
                    text = uiState.error!!,
                    color = MaterialTheme.colorScheme.error,
                    textAlign = TextAlign.Center,
                    style = MaterialTheme.typography.bodyMedium
                )
                Spacer(modifier = Modifier.height(16.dp))
                Button(
                    onClick = { viewModel.generateLoginCode() },
                    colors = ButtonDefaults.buttonColors(containerColor = MaterialTheme.colorScheme.error),
                    shape = RoundedCornerShape(12.dp)
                ) {
                    Text("Retry Connection")
                }
            }
        }
    }
}
