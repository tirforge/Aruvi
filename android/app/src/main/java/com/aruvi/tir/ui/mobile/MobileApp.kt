package com.aruvi.tir.ui.mobile

import androidx.compose.runtime.Composable
import com.aruvi.tir.ui.theme.TelePlayMobileTheme

@Composable
fun MobileApp(startDestination: String = "login") {
    TelePlayMobileTheme {
        MobileScaffold(startDestination = startDestination)
    }
}


