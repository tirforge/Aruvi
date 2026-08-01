package com.aruvi.tir.ui.mobile

import androidx.compose.animation.AnimatedVisibility
import androidx.compose.animation.slideInVertically
import androidx.compose.animation.slideOutVertically
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.consumeWindowInsets
import androidx.compose.foundation.layout.WindowInsets
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Download
import androidx.compose.material.icons.filled.Home
import androidx.compose.material.icons.filled.Person
import androidx.compose.material.icons.filled.Search
import androidx.compose.material.icons.filled.Movie
import androidx.compose.material.icons.outlined.Download
import androidx.compose.material.icons.outlined.Home
import androidx.compose.material.icons.outlined.Person
import androidx.compose.material.icons.outlined.Movie
import androidx.compose.material.icons.outlined.Search
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.unit.dp
import androidx.navigation.NavGraph.Companion.findStartDestination
import androidx.navigation.NavHostController
import androidx.navigation.NavType
import androidx.navigation.compose.NavHost
import androidx.navigation.compose.composable
import androidx.navigation.compose.currentBackStackEntryAsState
import androidx.navigation.compose.rememberNavController
import androidx.navigation.navArgument
import com.aruvi.tir.ui.mobile.auth.MobileLoginScreen
import com.aruvi.tir.ui.mobile.home.MobileHomeScreen
import com.aruvi.tir.ui.mobile.player.MobilePlayerScreen
import com.aruvi.tir.ui.navigation.Screen
import androidx.compose.material3.MaterialTheme

sealed class BottomNavItem(
val route: String,
val title: String,
val selectedIcon: ImageVector,
val unselectedIcon: ImageVector
) {
object Home : BottomNavItem("home", "Home", Icons.Filled.Home, Icons.Outlined.Home)
object Search : BottomNavItem("search", "Search", Icons.Filled.Search, Icons.Outlined.Search)
object Downloads : BottomNavItem("downloads", "Downloads", Icons.Filled.Download, Icons.Outlined.Download)
object Grab : BottomNavItem("grab", "Movies", Icons.Filled.Movie, Icons.Outlined.Movie)
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun MobileScaffold(
startDestination: String = "dashboard" // Changed default to dashboard wrapper
) {
val rootNavController = rememberNavController()

NavHost(
navController = rootNavController,
startDestination = startDestination,
modifier = Modifier.fillMaxSize()
) {
// 1. Login Screen (Full Screen)
composable("login") {
MobileLoginScreen(
onLoginSuccess = {
rootNavController.navigate("dashboard") {
popUpTo("login") { inclusive = true }
}
}
)
}

// 2. Dashboard (Tabs with Scaffold)
composable("dashboard") {
MainAppScreen(
onNavigateToPlayer = { fileId, directUrl ->
rootNavController.navigate(Screen.Player.createRoute(fileId, 0L, directUrl))
},
onLogout = {
rootNavController.navigate("login") {
popUpTo("dashboard") { inclusive = true }
}
}
)
}

// 3. Player (True Full Screen)
composable(
route = Screen.Player.route,
arguments = listOf(
navArgument("fileId") { type = NavType.IntType },
navArgument("startPosition") { type = NavType.LongType; defaultValue = 0L },
navArgument("directUrl") { type = NavType.StringType; nullable = true; defaultValue = null }
)
) { backStackEntry ->
val startPosition = backStackEntry.arguments?.getLong("startPosition") ?: 0L
MobilePlayerScreen(
startPosition = startPosition,
onBack = { rootNavController.popBackStack() }
)
}
}
}

@Composable
fun MainAppScreen(
onNavigateToPlayer: (Int, String?) -> Unit,
onLogout: () -> Unit
) {
val tabNavController = rememberNavController()
val navBackStackEntry by tabNavController.currentBackStackEntryAsState()
val currentRoute = navBackStackEntry?.destination?.route

Scaffold(
containerColor = MaterialTheme.colorScheme.background,
contentWindowInsets = WindowInsets(0.dp), // Fix: Allow content to extend behind system bars
bottomBar = {
GlassmorphismBottomNavigation(tabNavController, currentRoute)
}
) { innerPadding ->
// Inner NavHost for Tabs
NavHost(
navController = tabNavController,
startDestination = BottomNavItem.Home.route + "?folderId={folderId}&folderName={folderName}",
modifier = Modifier
.padding(innerPadding)
.consumeWindowInsets(innerPadding)
.fillMaxSize()
) {
composable(
route = BottomNavItem.Home.route + "?folderId={folderId}&folderName={folderName}",
arguments = listOf(
navArgument("folderId") { 
type = NavType.IntType
defaultValue = -1 // Use -1 to represent null/root
},
navArgument("folderName") { 
type = NavType.StringType
nullable = true
defaultValue = null
}
)
) {
MobileHomeScreen(
onPlayFile = { id -> onNavigateToPlayer(id, null) },
onLogout = onLogout,
onSearchClick = {
tabNavController.navigate(BottomNavItem.Search.route) {
popUpTo(tabNavController.graph.findStartDestination().id) {
saveState = true
}
launchSingleTop = true
restoreState = true
}
}
)
}
composable(BottomNavItem.Search.route) {
com.aruvi.tir.ui.mobile.search.MobileSearchScreen(
onPlayFile = { id -> onNavigateToPlayer(id, null) },
onGoToFolder = { folderId, folderName ->
tabNavController.navigate(BottomNavItem.Home.route + "?folderId=$folderId&folderName=$folderName") {
popUpTo(tabNavController.graph.findStartDestination().id) {
saveState = true
}
launchSingleTop = true
restoreState = true
}
}
)
}
composable(BottomNavItem.Downloads.route) {
com.aruvi.tir.ui.mobile.downloads.MobileDownloadsScreen()
}
composable(BottomNavItem.Grab.route) {
com.aruvi.tir.ui.mobile.grab.MobileGrabScreen(
onBackClick = { tabNavController.popBackStack() },
onPlayStream = { streamUrl -> onNavigateToPlayer(0, streamUrl) }
)
}
}
}
}

@Composable
fun GlassmorphismBottomNavigation(
navController: NavHostController,
currentRoute: String?
) {
NavigationBar(
containerColor = MaterialTheme.colorScheme.surface.copy(alpha = 0.9f),
tonalElevation = 0.dp,
modifier = Modifier
) {
val items = listOf(
BottomNavItem.Home,
BottomNavItem.Search,
BottomNavItem.Grab,
BottomNavItem.Downloads
)

items.forEach { item ->
val isSelected = currentRoute?.startsWith(item.route) == true
NavigationBarItem(
selected = isSelected,
onClick = {
navController.navigate(item.route) {
popUpTo(navController.graph.findStartDestination().id) {
saveState = true
}
launchSingleTop = true
restoreState = true
}
},
icon = {
Icon(
imageVector = if (isSelected) item.selectedIcon else item.unselectedIcon,
contentDescription = item.title,
tint = if (isSelected) MaterialTheme.colorScheme.primary else MaterialTheme.colorScheme.onSurfaceVariant
)
},
label = {
Text(
text = item.title,
color = if (isSelected) MaterialTheme.colorScheme.primary else MaterialTheme.colorScheme.onSurfaceVariant,
style = MaterialTheme.typography.labelSmall
)
},
colors = NavigationBarItemDefaults.colors(
indicatorColor = MaterialTheme.colorScheme.primary.copy(alpha = 0.1f)
)
)
}
}
}
