package com.aruvi.tir.ui

import android.os.Bundle
import androidx.fragment.app.FragmentActivity
import androidx.activity.compose.setContent
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.material3.Surface
import androidx.compose.ui.Modifier
import androidx.navigation.compose.rememberNavController
import com.aruvi.tir.data.repository.AuthRepository
import com.aruvi.tir.ui.navigation.NavGraph
import com.aruvi.tir.ui.theme.TelePlayTheme
import com.aruvi.tir.ui.theme.TVBackground
import dagger.hilt.android.AndroidEntryPoint
import javax.inject.Inject

/**
 * Main Activity for TelePlay.
 * Serves as the entry point and hosts the Compose navigation.
 */
@AndroidEntryPoint
class MainActivity : FragmentActivity() {

    @Inject
    lateinit var authRepository: AuthRepository

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)

        setContent {
            TelePlayTheme {
                Surface(
                    modifier = Modifier.fillMaxSize(),
                    color = TVBackground
                ) {
                    val navController = rememberNavController()
                    NavGraph(
                        navController = navController,
                        authRepository = authRepository
                    )
                }
            }
        }
    }
}
