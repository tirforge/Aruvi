package com.aruvi.tir.ui.mobile.profile

import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ExitToApp
import androidx.compose.material.icons.filled.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.hilt.navigation.compose.hiltViewModel
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.aruvi.tir.data.repository.AuthRepository
import com.aruvi.tir.data.repository.SettingsRepository
import com.aruvi.tir.ui.mobile.auth.MobileLoginScreen
import com.aruvi.tir.ui.theme.*
import dagger.hilt.android.lifecycle.HiltViewModel
import kotlinx.coroutines.flow.SharingStarted
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.stateIn
import kotlinx.coroutines.launch
import javax.inject.Inject

@HiltViewModel
class MobileProfileViewModel @Inject constructor(
    private val authRepository: AuthRepository,
    private val settingsRepository: SettingsRepository
) : ViewModel() {
    
    val userName: StateFlow<String?> = authRepository.userName
        .stateIn(viewModelScope, SharingStarted.WhileSubscribed(5000), null)
        
    val serverUrl: StateFlow<String?> = settingsRepository.serverUrl
         .stateIn(viewModelScope, SharingStarted.WhileSubscribed(5000), null)

    fun logout(onLogoutSuccess: () -> Unit) {
        viewModelScope.launch {
            authRepository.logout()
            onLogoutSuccess()
        }
    }
}

@Composable
fun MobileProfileScreen(
    viewModel: MobileProfileViewModel = hiltViewModel(),
    onLogout: () -> Unit
) {
    val userName by viewModel.userName.collectAsState()
    val serverUrl by viewModel.serverUrl.collectAsState()

    Column(
        modifier = Modifier
            .fillMaxSize()
            .background(MobileBackground)
    ) {
        // Header
        Box(
            modifier = Modifier
                .fillMaxWidth()
                .height(200.dp)
                .background(
                    Brush.verticalGradient(
                        colors = listOf(MobileHeaderGradientStart, MobileBackground)
                    )
                ),
            contentAlignment = Alignment.Center
        ) {
            Column(horizontalAlignment = Alignment.CenterHorizontally) {
                Icon(
                    Icons.Default.AccountCircle,
                    contentDescription = null,
                    modifier = Modifier.size(80.dp),
                    tint = MobilePrimary
                )
                Spacer(modifier = Modifier.height(16.dp))
                Text(
                    text = userName ?: "Guest",
                    style = MaterialTheme.typography.headlineSmall,
                    color = MobileTextPrimary,
                    fontWeight = FontWeight.Bold
                )
                Text(
                    text = serverUrl ?: "No Server",
                    style = MaterialTheme.typography.bodyMedium,
                    color = MobileTextSecondary
                )
            }
        }

        // Options
        Column(modifier = Modifier.padding(16.dp)) {
            Text(
                text = "General Settings",
                style = MaterialTheme.typography.titleMedium,
                color = MobilePrimary,
                modifier = Modifier.padding(bottom = 8.dp)
            )
            
            ProfileMenuItem(
                icon = Icons.Default.Settings,
                title = "App Settings",
                onClick = { /* TODO: Open Settings */ }
            )
            
            Spacer(modifier = Modifier.height(12.dp))
            
            ProfileMenuItem(
                icon = Icons.Default.CleaningServices,
                title = "Clear Cache",
                onClick = { 
                    // Simple cache clear
                }
            )

            Spacer(modifier = Modifier.height(12.dp))

            ProfileMenuItem(
                icon = Icons.AutoMirrored.Filled.ExitToApp,
                title = "Logout",
                onClick = { viewModel.logout(onLogout) }
            )
        }
        
        Spacer(modifier = Modifier.weight(1f))
        
        Text(
            text = "Version 1.0.0",
            style = MaterialTheme.typography.labelSmall,
            color = MobileTextSecondary,
            modifier = Modifier.align(Alignment.CenterHorizontally).padding(16.dp)
        )
    }
}

@Composable
fun ProfileMenuItem(
    icon: androidx.compose.ui.graphics.vector.ImageVector,
    title: String,
    onClick: () -> Unit
) {
    GlassmorphismSurface(
        modifier = Modifier
            .fillMaxWidth()
            .height(56.dp)
            .clickable { onClick() }
    ) {
        Row(
            modifier = Modifier
                .fillMaxSize()
                .padding(horizontal = 16.dp),
            verticalAlignment = Alignment.CenterVertically
        ) {
            Icon(icon, contentDescription = null, tint = MobilePrimary)
            Spacer(modifier = Modifier.width(16.dp))
            Text(title, color = MobileTextPrimary, style = MaterialTheme.typography.titleMedium)
        }
    }
}
