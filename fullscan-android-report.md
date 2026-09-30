# Fullscan Report — android/

Verdict: FINDINGS (11 files fixed, 0 new build errors; 7 pre-existing compile errors unchanged)

## Scope

- Dirs scanned (source only, excluding `build/` and `.gradle/`):
  - `android/`
  - `android/app/`
  - `android/app/src/main/java/com/aruvi/tir/` (incl. `cast/`, `data/api/`, `data/model/`, `data/repository/`, `di/`, `download/`, `service/`, `ui/` + `ui/mobile/`, `ui/player/`, `ui/details/`, `ui/search/`, `ui/auth/`, `ui/components/`, `ui/theme/`, `ui/navigation/`, `ui/browse/`, `ui/home/`, `ui/grab/`, `ui/settings/`)
  - `android/app/src/main/res/` (values, xml, drawable, mipmap)
  - `android/app/src/mobile/`, `android/app/src/tv/`
  - `android/gradle/wrapper/`
- File count: 110 source files (72 Kotlin `*.kt`), excluding `build/` + `.gradle/` output.
- Checked: hardcoded secrets/tokens/URLs, cleartext HTTP, token storage, auth-header handling, refresh races, dynamic-base-URL SSRF, path traversal in downloads, FileProvider exposure, exported components/permissions, intent/MIME injection, log leakage of tokens/PII, exception swallowing, coroutine error handling, StateFlow races, lifecycle leaks (ViewModel/Service/PlayerView), dead code/imports, missing error handling around network/IO, Gradle signing/ProGuard config.
- Verified: `./gradlew :app:compileMobileDebugKotlin` before and after. Both runs fail with the SAME 7 pre-existing errors in `PlayerViewModel.kt` (unresolved `setActiveTrackIds`, `TextTrackStyle.COLOR_WHITE/COLOR_NONE`, `WebImage`, forward `file` reference). No new errors introduced (only line numbers shifted -2 from dead-code removal). No WebView and no raw SQL/Room in tree (pass). MediaStore selection uses `?` args (safe).

## Fixed (this run)

1. `android/app/src/main/java/com/aruvi/tir/download/FileDownloader.kt:118` — Path traversal via server-controlled `fileName` used verbatim as `MediaStore.DISPLAY_NAME` and `File(downloadsDir, fileName)`. Fixed with `sanitizeFileName()` (strip directories, replace `[\\/:*?"<>|]`, reject `.`/`..`, cap 255 chars), applied in `createDestination()`.
2. `android/app/src/main/java/com/aruvi/tir/download/FileDownloader.kt:442` — `MutableStateFlow` read-modify-write race (`_tasks.value = _tasks.value + ...`) from many `Dispatchers.IO` coroutines. Fixed with `update {}`; also `cancel()`/`deleteFile()` map-removal races switched to `_tasks.update { it - id }`.
3. `android/app/src/main/java/com/aruvi/tir/data/repository/AuthRepository.kt:107` — Refresh thundering-herd: second waiter behind `refreshMutex` re-spent the rotated single-use refresh token. Fixed by capturing the token before the lock and reusing the fresh access token when the stored token changed.
4. `android/app/src/main/java/com/aruvi/tir/ui/player/PlayerViewModel.kt:1357` — Logcat leakage of full cast URL (contains `?token=<JWT>`). Fixed to log without the URL.
5. `android/app/src/main/java/com/aruvi/tir/ui/player/PlayerViewModel.kt:25,355` — Dead `DefaultHttpDataSource` import and never-assigned `castExecutor` field (+ shutdown block). Removed.
6. `android/app/src/main/java/com/aruvi/tir/di/PlayerModule.kt:53` — Streaming `OkHttpClient` had `AuthInterceptor` but not `DynamicBaseUrlInterceptor`, so server change required restart for playback. Fixed by injecting and adding the interceptor first.
7. `android/app/src/main/java/com/aruvi/tir/di/AppModule.kt:3` — Dead imports (`Context`, `AuthRepository`, `SettingsRepository`, `Provides`, `ApplicationContext`, `Singleton`). Removed.
8. `android/app/src/main/java/com/aruvi/tir/service/DownloadService.kt:6` — Unused `PendingIntent` import. Removed.
9. `android/app/src/main/java/com/aruvi/tir/ui/details/DetailsViewModel.kt:64` — `downloadJob` collecting `fileDownloader.tasks` never cancelled in `onCleared()` (lifecycle leak). Added `onCleared()` override cancelling the job.
10. `android/app/src/main/java/com/aruvi/tir/ui/player/PlayerScreen.kt:225` and `android/app/src/main/java/com/aruvi/tir/ui/mobile/player/MobilePlayerScreen.kt:190` — `AndroidView(PlayerView)` never detached (`player=null`) in `onRelease`, leaking the shared singleton ExoPlayer reference. Added `onRelease = { it.player = null }` in both.
11. `android/app/src/main/java/com/aruvi/tir/ui/mobile/components/MobileComponents.kt:133` — `LaunchedEffect { loadFolderTree() }` threw uncaught on network failure (crash). Wrapped in try/catch with error state + `finally { isLoading = false }`.
12. `android/app/src/main/AndroidManifest.xml:14` — `READ_EXTERNAL_STORAGE` without `maxSdkVersion` over-requested on API 33+ (which uses `READ_MEDIA_*`, already declared). Added `android:maxSdkVersion="32"`.

## Found but intentionally NOT changed (needs product/backend decision, out of minimal-fix scope)

- `android/app/src/main/java/com/aruvi/tir/data/repository/AuthRepository.kt:20` — Tokens in plain `preferencesDataStore("auth_prefs")`; `security-crypto` is a dependency but migration to encrypted storage is a behavior/refactor change, not minimal.
- `android/app/src/main/AndroidManifest.xml:55` + defaults `http://localhost:7680` (`SettingsRepository.kt:40`, `NetworkModule.kt:117`) — `usesCleartextTraffic="true"` + http default allows JWT over cleartext on LAN/tunnels. Flipping to `false`/https-only would break self-hosted plain-HTTP users; needs `networkSecurityConfig` + UX decision.
- `android/app/src/main/java/com/aruvi/tir/ui/player/PlayerViewModel.kt:273,767,1170,1177,1188,1102`, `android/app/src/main/java/com/aruvi/tir/ui/mobile/home/MobileHomeViewModel.kt:289,339`, `android/app/src/main/java/com/aruvi/tir/ui/search/SearchViewModel.kt:170,230` — JWT passed as `?token=` query (stream/cast/thumbnail/external-player/clipboard). Backend has no header-capable public path for Cast/external players, so removing query tokens now would break playback/sharing.
- `android/app/src/main/java/com/aruvi/tir/data/api/DynamicBaseUrlInterceptor.kt:24`, `android/app/src/main/java/com/aruvi/tir/data/repository/SettingsRepository.kt:77`, `android/app/src/main/java/com/aruvi/tir/ui/auth/LoginViewModel.kt:116,134` — User-typed server URL persisted with no allowlist validation (SSRF/open-redirect of JWTs to attacker host). Strict https-only/userinfo rejection would break http LAN installs; needs product decision.
- `android/app/src/main/AndroidManifest.xml:94`, `:60`, `:48,56`, `android/app/src/main/res/xml/file_paths.xml:3`, `android/app/build.gradle.kts:69`, `android/app/proguard-rules.pro:5` — Exported service/activity, `largeHeap`/`requestLegacyExternalStorage`, broad FileProvider path, debug-signed release fallback, over-broad `-keep` rules. Each is a behavior/release-pipeline change; left as-is.
- Pre-existing compile errors (NOT introduced here, identical before/after): `android/app/src/main/java/com/aruvi/tir/ui/player/PlayerViewModel.kt:748,821` (`setActiveTrackIds`), `:875,876` (`COLOR_WHITE/COLOR_NONE`), `:1155,1156` (forward `file` ref), `:1299` (`WebImage`).

## Verification

- `./gradlew :app:compileMobileDebugKotlin` on clean tree: 7 errors (lines 750,823,877,878,1157,1158,1301).
- Same task after fixes: same 7 errors (lines 748,821,875,876,1155,1156,1299 — shifted only by dead-code removal). No new errors.
- `git status` confirms only `android/**` + this report file touched.
