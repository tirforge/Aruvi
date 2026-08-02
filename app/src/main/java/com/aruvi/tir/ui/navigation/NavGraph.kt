package com.aruvi.tir.ui.navigation

import androidx.compose.runtime.Composable
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.navigation.NavHostController
import androidx.navigation.NavType
import androidx.navigation.compose.NavHost
import androidx.navigation.compose.composable
import androidx.navigation.navArgument
import com.aruvi.tir.data.repository.AuthRepository
import com.aruvi.tir.ui.auth.LoginScreen
import com.aruvi.tir.ui.browse.FolderScreen
import com.aruvi.tir.ui.details.DetailsScreen
import com.aruvi.tir.ui.home.HomeScreen
import com.aruvi.tir.ui.player.PlayerScreen
import com.aruvi.tir.ui.search.SearchScreen
import com.aruvi.tir.ui.settings.SettingsScreen
import com.aruvi.tir.BuildConfig
import com.aruvi.tir.ui.grab.TvGrabScreen
import com.aruvi.tir.ui.mobile.grab.MobileGrabScreen

/**
 * Main navigation graph for the app.
 */
@Composable
fun NavGraph(
    navController: NavHostController,
    authRepository: AuthRepository
) {
    val isLoggedIn by authRepository.isLoggedIn.collectAsState(initial = false)
    
    val startDestination = if (isLoggedIn) Screen.Home.route else Screen.Login.route

    NavHost(
        navController = navController,
        startDestination = startDestination
    ) {
        // Login Screen
        composable(Screen.Login.route) {
            LoginScreen(
                onLoginSuccess = {
                    navController.navigate(Screen.Home.route) {
                        popUpTo(Screen.Login.route) { inclusive = true }
                    }
                }
            )
        }

// Home Screen
composable(Screen.Home.route) {
    HomeScreen(
        onFileClick = { fileId ->
            navController.navigate(Screen.Details.createRoute(fileId))
        },
        onFolderClick = { folderId ->
            navController.navigate(Screen.Folder.createRoute(folderId))
        },
        onSearchClick = {
            navController.navigate(Screen.Search.route)
        },
        onSettingsClick = {
            navController.navigate(Screen.Settings.route)
        },
        onGrabClick = {
            navController.navigate(Screen.Grab.route)
        }
    )
}

        // Folder Screen
        composable(
            route = Screen.Folder.route,
            arguments = listOf(
                navArgument("folderId") { type = NavType.IntType }
            )
        ) {
            FolderScreen(
                onFileClick = { fileId ->
                    navController.navigate(Screen.Details.createRoute(fileId))
                },
                onFolderClick = { subFolderId ->
                    navController.navigate(Screen.Folder.createRoute(subFolderId))
                },
                onBackClick = {
                    navController.popBackStack()
                }
            )
        }

        // File Details Screen
        composable(
            route = Screen.Details.route,
            arguments = listOf(
                navArgument("fileId") { type = NavType.IntType }
            )
        ) { backStackEntry ->
            val fileId = backStackEntry.arguments?.getInt("fileId") ?: return@composable
            DetailsScreen(
                fileId = fileId,
                onPlayClick = { id, resumePosition ->
                    navController.navigate(Screen.Player.createRoute(id, resumePosition))
                },
                onBackClick = {
                    navController.popBackStack()
                }
            )
        }

        // Player Screen
        composable(
            route = Screen.Player.route,
            arguments = listOf(
                navArgument("fileId") { type = NavType.IntType },
                navArgument("startPosition") { type = NavType.LongType; defaultValue = 0L },
                navArgument("directUrl") { type = NavType.StringType; nullable = true; defaultValue = null }
            )
        ) {
            PlayerScreen(
                onBackClick = {
                    navController.popBackStack()
                }
            )
        }

        // Search Screen
        composable(Screen.Search.route) {
            SearchScreen(
                onFileClick = { fileId ->
                    navController.navigate(Screen.Details.createRoute(fileId))
                },
                onBackClick = {
                    navController.popBackStack()
                }
            )
        }

        // Settings Screen
        composable(Screen.Settings.route) {
            SettingsScreen(
                onBackClick = {
                    navController.popBackStack()
                },
                onLogout = {
                    navController.navigate(Screen.Login.route) {
                        popUpTo(Screen.Home.route) { inclusive = true }
                    }
                }
            )
        }
// Grab Screen
composable(Screen.Grab.route) {
    if (BuildConfig.FLAVOR == "tv") {
        TvGrabScreen(
            onBackClick = { navController.popBackStack() },
            onPlayStream = { url ->
                navController.navigate(Screen.Player.createRoute(0, 0L, url))
            }
        )
    } else {
MobileGrabScreen(
onBackClick = { navController.popBackStack() },
onPlayStream = { url ->
navController.navigate(Screen.Player.createRoute(0, 0L, url))
}
)
    }
}
    }
}
