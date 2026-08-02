package com.aruvi.tir.ui.mobile

import android.os.Bundle
import androidx.fragment.app.FragmentActivity
import androidx.activity.compose.setContent
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.platform.LocalContext
import com.aruvi.tir.data.repository.AuthRepository
import dagger.hilt.android.AndroidEntryPoint
import javax.inject.Inject
import androidx.activity.enableEdgeToEdge

@AndroidEntryPoint
class MobileMainActivity : FragmentActivity() {

    @Inject
    lateinit var authRepository: AuthRepository

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        enableEdgeToEdge()
        setContent {
            val context = LocalContext.current
            val permissions = if (android.os.Build.VERSION.SDK_INT >= android.os.Build.VERSION_CODES.TIRAMISU) {
                arrayOf(
                    android.Manifest.permission.READ_MEDIA_IMAGES,
                    android.Manifest.permission.READ_MEDIA_VIDEO,
                    android.Manifest.permission.READ_MEDIA_AUDIO,
                    android.Manifest.permission.POST_NOTIFICATIONS
                )
            } else {
                arrayOf(
                    android.Manifest.permission.READ_EXTERNAL_STORAGE,
                    android.Manifest.permission.WRITE_EXTERNAL_STORAGE
                )
            }

            // Only request permissions that haven't been granted yet, so we
            // don't re-prompt for things the user already allowed.
            val pendingPermissions = remember(permissions) {
                permissions.filter { context.checkSelfPermission(it) != android.content.pm.PackageManager.PERMISSION_GRANTED }
                    .toTypedArray()
            }

            // rememberSaveable so a config change (rotation) doesn't re-launch
            // the request while the first dialog is still up.
            var requestedThisSession by rememberSaveable { mutableStateOf(false) }

            val launcher = androidx.activity.compose.rememberLauncherForActivityResult(
                androidx.activity.result.contract.ActivityResultContracts.RequestMultiplePermissions()
            ) { }

            LaunchedEffect(Unit) {
                if (!requestedThisSession && pendingPermissions.isNotEmpty()) {
                    requestedThisSession = true
                    launcher.launch(pendingPermissions)
                }
            }

            val isLoggedIn by authRepository.isLoggedIn.collectAsState(initial = false)
            val startDestination = if (isLoggedIn) "dashboard" else "login"

            MobileApp(startDestination = startDestination)
        }
    }
}
