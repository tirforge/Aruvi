package com.aruvi.tir.ui.navigation

/**
 * Navigation routes for the app.
 */
sealed class Screen(val route: String) {
    object Login : Screen("login")
    object Home : Screen("home")
    object Folder : Screen("folder/{folderId}") {
        fun createRoute(folderId: Int) = "folder/$folderId"
    }
    object Details : Screen("details/{fileId}") {
        fun createRoute(fileId: Int) = "details/$fileId"
    }
    object Player : Screen("player/{fileId}?startPosition={startPosition}&directUrl={directUrl}") {
        fun createRoute(fileId: Int, startPosition: Long = 0L, directUrl: String? = null) =
            buildString {
                append("player/$fileId?startPosition=$startPosition")
                if (directUrl != null) append("&directUrl=").append(android.net.Uri.encode(directUrl))
            }
    }
    object Search : Screen("search")
    object Settings : Screen("settings")
    object Grab : Screen("grab")
}
