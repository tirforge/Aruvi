package com.aruvi.tir.ui.settings

import androidx.compose.animation.core.Spring
import androidx.compose.animation.core.animateFloatAsState
import androidx.compose.animation.core.spring
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.focusable
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.focus.onFocusChanged
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.graphicsLayer
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.hilt.navigation.compose.hiltViewModel
import androidx.tv.material3.ExperimentalTvMaterial3Api
import com.aruvi.tir.ui.components.TVButton
import com.aruvi.tir.ui.components.TvAnimatedBackground
import com.aruvi.tir.ui.theme.*

/**
 * Settings screen for app configuration.
 */
@Composable
fun SettingsScreen(
    onBackClick: () -> Unit,
    onLogout: () -> Unit,
    viewModel: SettingsViewModel = hiltViewModel()
) {
    val uiState by viewModel.uiState.collectAsState()

    Box(modifier = Modifier.fillMaxSize()) {
        TvAnimatedBackground(modifier = Modifier.fillMaxSize())
        Column(
            modifier = Modifier
                .fillMaxSize()
                .padding(48.dp)
        ) {
            // Header
            SettingsHeader(onBackClick = onBackClick)

            Spacer(modifier = Modifier.height(48.dp))

            // Settings sections
            Column(
                modifier = Modifier 
                    .fillMaxWidth(0.6f)
                    .align(Alignment.CenterHorizontally),
                verticalArrangement = Arrangement.spacedBy(24.dp)
            ) {
                // User info section
                if (uiState.userName != null) {
                    SettingsSection(title = "Account") {
                        SettingsItem(
                            label = "Logged in as",
                            value = uiState.userName!!
                        )
                    }
                }

                // Playback settings
                SettingsSection(title = "Playback") {
                    SettingsToggle(
                        label = "Auto-play next file",
                        checked = uiState.autoPlayNext,
                        onCheckedChange = { viewModel.toggleAutoPlayNext() }
                    )
                }

                Spacer(modifier = Modifier.height(32.dp))

                // Logout button - raw Box to avoid Material/TV button theming issues
                var logoutFocused by remember { mutableStateOf(false) }
                val logoutScale by animateFloatAsState(
                    targetValue = if (logoutFocused) 1.03f else 1f,
                    animationSpec = spring(stiffness = Spring.StiffnessMedium),
                    label = "logoutScale"
                )
                Box(
                    modifier = Modifier
                        .fillMaxWidth()
                        .height(52.dp)
                        .graphicsLayer {
                            scaleX = logoutScale
                            scaleY = logoutScale
                        }
                        .border(
                            width = if (logoutFocused) 2.dp else 1.dp,
                            color = if (logoutFocused) TVFocusRing else TVTextSecondary.copy(alpha = 0.15f),
                            shape = RoundedCornerShape(8.dp)
                        )
                        .background(
                            color = if (logoutFocused) Color(0xFF444444) else Color(0xFF333333),
                            shape = RoundedCornerShape(8.dp)
                        )
                        .focusable()
                        .onFocusChanged { logoutFocused = it.isFocused }
                        .clickable { viewModel.showLogoutConfirm() },
                    contentAlignment = Alignment.Center
                ) {
                    Text(
                        text = "Logout",
                        fontSize = 18.sp,
                        fontWeight = FontWeight.SemiBold,
                        color = Color.White
                    )
                }
            }
        }

        // Logout confirmation dialog
        if (uiState.showLogoutConfirm) {
            LogoutConfirmDialog(
                onConfirm = { viewModel.logout { onLogout() } },
                onDismiss = { viewModel.hideLogoutConfirm() }
            )
        }
    }
}

/**
 * Settings header.
 */
@Composable
private fun SettingsHeader(onBackClick: () -> Unit) {
    Row(
        modifier = Modifier.fillMaxWidth(),
        verticalAlignment = Alignment.CenterVertically
    ) {
        Icon(
            imageVector = Icons.Default.Settings,
            contentDescription = null,
            tint = TVPrimary,
            modifier = Modifier.size(28.dp)
        )

        Spacer(modifier = Modifier.width(12.dp))

        Text(
            text = "Settings",
            style = MaterialTheme.typography.headlineLarge,
            color = TVTextPrimary,
            fontWeight = FontWeight.Bold
        )
    }
}

/**
 * Settings section with title.
 */
@Composable
private fun SettingsSection(
    title: String,
    content: @Composable ColumnScope.() -> Unit
) {
    Column {
        Row(
            verticalAlignment = Alignment.CenterVertically,
            modifier = Modifier.padding(bottom = 12.dp)
        ) {
            Text(
                text = title.uppercase(),
                style = MaterialTheme.typography.labelMedium,
                color = TVPrimary,
                fontWeight = FontWeight.Bold,
                letterSpacing = 1.sp
            )
        }

        Card(
            modifier = Modifier.fillMaxWidth(),
            colors = CardDefaults.cardColors(containerColor = TVSurface),
            shape = RoundedCornerShape(16.dp)
        ) {
            Column(
                modifier = Modifier.padding(20.dp),
                verticalArrangement = Arrangement.spacedBy(16.dp),
                content = content
            )
        }
    }
}

/**
 * Read-only settings item.
 */
@Composable
private fun SettingsItem(label: String, value: String) {
    Row(
        modifier = Modifier.fillMaxWidth(),
        horizontalArrangement = Arrangement.SpaceBetween,
        verticalAlignment = Alignment.CenterVertically
    ) {
        Text(
            text = label,
            style = MaterialTheme.typography.bodyLarge,
            color = TVTextSecondary
        )
        Text(
            text = value,
            style = MaterialTheme.typography.bodyLarge,
            color = TVTextPrimary
        )
    }
}

/**
 * Settings toggle switch.
 */
@Composable
private fun SettingsToggle(
    label: String,
    checked: Boolean,
    onCheckedChange: () -> Unit
) {
    var toggleFocused by remember { mutableStateOf(false) }
    val toggleScale by animateFloatAsState(
        targetValue = if (toggleFocused) 1.03f else 1f,
        animationSpec = spring(stiffness = Spring.StiffnessMedium),
        label = "toggleScale"
    )
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .graphicsLayer {
                scaleX = toggleScale
                scaleY = toggleScale
            }
            .border(
                width = if (toggleFocused) 2.dp else 1.dp,
                color = if (toggleFocused) TVFocusRing else TVTextSecondary.copy(alpha = 0.15f),
                shape = RoundedCornerShape(12.dp)
            )
            .clip(RoundedCornerShape(12.dp))
            .background(
                if (toggleFocused) TVCardFocused else Color.Transparent,
                RoundedCornerShape(12.dp)
            )
            .padding(horizontal = 16.dp, vertical = 12.dp)
            .focusable()
            .onFocusChanged { toggleFocused = it.isFocused }
            .clickable { onCheckedChange() },
        horizontalArrangement = Arrangement.SpaceBetween,
        verticalAlignment = Alignment.CenterVertically
    ) {
        Text(
            text = label,
            style = MaterialTheme.typography.bodyLarge,
            color = TVTextPrimary
        )

        Switch(
            checked = checked,
            onCheckedChange = null,
            colors = SwitchDefaults.colors(
                checkedThumbColor = TVPrimary,
                checkedTrackColor = TVPrimary.copy(alpha = 0.5f),
                uncheckedThumbColor = TVTextSecondary,
                uncheckedTrackColor = TVSurfaceVariant
            )
        )
    }
}

/**
 * Logout confirmation dialog.
 */
@Composable
private fun LogoutConfirmDialog(
    onConfirm: () -> Unit,
    onDismiss: () -> Unit
) {
    AlertDialog(
        onDismissRequest = onDismiss,
        title = {
            Text(
                text = "Logout",
                style = MaterialTheme.typography.headlineSmall
            )
        },
        text = {
            Text(
                text = "Are you sure you want to logout?",
                style = MaterialTheme.typography.bodyLarge
            )
        },
        confirmButton = {
            TextButton(onClick = onConfirm) {
                Text("Logout", color = TVError)
            }
        },
        dismissButton = {
            TextButton(onClick = onDismiss) {
                Text("Cancel")
            }
        },
        containerColor = TVSurface
    )
}
