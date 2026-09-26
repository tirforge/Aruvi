# Fullscan Report — `android/` codebase

- **Scope (strict):** only files under `android/` were read/edited. No other top-level dirs, `.github/`, or vendored/build output touched (`build/`, `.gradle/` excluded).
- **Dirs scanned:**
  - `android/` (root: `build.gradle.kts`, `settings.gradle.kts`, `gradle.properties`, `gradlew`, `local.properties.example`, `.gitignore`)
  - `android/app/` (`build.gradle.kts`, `proguard-rules.pro`, `libs/`)
  - `android/app/src/main/` (all Kotlin under `java/com/aruvi/tir/`, `res/`, `AndroidManifest.xml`, `res/xml/file_paths.xml`)
  - `android/app/src/mobile/` + `android/app/src/tv/` (flavor manifests)
  - `android/gradle/wrapper/`
- **File count:** 110 files total under `android/` (excluding `build/` + `.gradle/`); **72 Kotlin (`.kt`)**, **12 XML**, **3 Gradle KTS**; remainder = assets (webp/png), `lib-decoder-av1-release.aar`, `proguard-rules.pro`, scripts.
- **Verdict: NOT CLEAN — findings below.** Safe minimal fixes applied to 21 files (see "Fixed" tags). All other findings are documented for follow-up (need design decisions / refactors / backend-contract confirmation — deliberately NOT changed per "no refactors" rule).

Verification: `./gradlew :app:compileMobileDebugKotlin --offline` attempted — runner has JDK 17 + SDK but no cached Android Gradle Plugin and no network to plugin repos, so the full build could not run here (CI on the PR will compile/lint). Edited files were brace/paren-balance checked and the full `git diff` was hand-reviewed. `git status` confirms only `android/` paths modified.

---

## Fixed in this run (21 files)

### Crash / correctness
1. `android/app/src/main/java/com/aruvi/tir/data/model/FileItem.kt:40` — `formattedSize` `units[digitGroups]` OOB for huge `fileSize` (index 5+). **FIXED:** coerce index to `0..units.size-1`.
2. `android/app/src/main/java/com/aruvi/tir/data/model/FileItem.kt:99` — `progressPercent` NaN `duration` passes through (`coerceIn` on NaN undefined) into `LinearProgressIndicator`. **FIXED:** `takeIf { it.isFinite() }` guard.
3. `android/app/src/main/java/com/aruvi/tir/data/model/FileItem.kt:79,85` — `fileType == "video"/"audio"` case-sensitive. **FIXED:** `equals(..., ignoreCase = true)` (+ mime prefix ignoreCase).
4. `android/app/src/main/java/com/aruvi/tir/data/model/FileItem.kt:108` — `PaginatedResponse` no defaults; missing `total/page/per_page` crashes Gson. **FIXED:** defaults (`emptyList()/0`).
5. `android/app/src/main/java/com/aruvi/tir/data/model/TVModels.kt:12` — `TVBrowseResponse` non-null lists, no defaults → Gson null-into-non-null crash. **FIXED:** `= emptyList()` on all three.
6. `android/app/src/main/java/com/aruvi/tir/data/model/WatchProgress.kt:22,39` — negative `position` formats `"0:-5"`; `dur == 0` misses negatives. **FIXED:** `coerceAtLeast(0)`, `dur <= 0`.
7. `android/app/src/main/java/com/aruvi/tir/ui/theme/Theme.kt:89` — `(view.context as Activity)` throws `ClassCastException` in previews/dialogs. **FIXED:** safe `findActivity() as? Activity` (new import) with null-guard.
8. `android/app/src/main/java/com/aruvi/tir/ui/mobile/Extensions.kt:8` — recursive `findActivity()`/`findFragmentActivity()` StackOverflow on cyclic wrapper. **FIXED:** iterative loop, depth cap 32.
9. `android/app/src/main/java/com/aruvi/tir/ui/mobile/player/MobilePlayerScreen.kt:683` — `Slider(value = currentPosition.toFloat())` uncoerced; `TIME_UNSET`/overshoot throws. **FIXED:** coerce value into range.
10. `android/app/src/main/java/com/aruvi/tir/ui/mobile/player/MobilePlayerScreen.kt:1039` — `formatTime(negative)` renders garbage. **FIXED:** `if (ms <= 0) return "0:00"`.
11. `android/app/src/main/java/com/aruvi/tir/ui/details/DetailsViewModel.kt:59` — `savedStateHandle.get<Int>("fileId") ?: 0` loads invalid file 0. **FIXED:** `fileId <= 0` → error state, return.
12. `android/app/src/main/java/com/aruvi/tir/ui/details/DetailsViewModel.kt:228` — `downloadStarted` never reset on FAILED/CANCELLED → Download button dead. **FIXED:** reset guard + `downloadId` on terminal states.
13. `android/app/src/main/java/com/aruvi/tir/ui/details/DetailsViewModel.kt:151,157` — `"$serverUrl/api/..."` double-slash on trailing `/`. **FIXED:** `trimEnd('/')`.
14. `android/app/src/main/java/com/aruvi/tir/ui/mobile/components/MobileComponents.kt:133` — `MovePickerDialog` `LaunchedEffect` no try/catch → `isLoading=true` forever. **FIXED:** try/catch/finally + error state.
15. `android/app/src/main/java/com/aruvi/tir/ui/mobile/components/MobileComponents.kt:110` — `remember { mutableStateOf(initialValue) }` stale on change. **FIXED:** `remember(initialValue)`.
16. `android/app/src/main/java/com/aruvi/tir/ui/mobile/components/MobileComponents.kt:115` — `onConfirm(text)` allows blank rename. **FIXED:** trim + blank guard, Confirm disabled when blank.
17. `android/app/src/main/java/com/aruvi/tir/ui/search/SearchViewModel.kt:96` — cancelled search leaves `isSearching=true`; stale query overwrites newer. **FIXED:** try/catch(CancellationException) resets flag + rethrows; generation guard; `<2`-char branch resets flag.
18. `android/app/src/main/java/com/aruvi/tir/ui/search/SearchViewModel.kt:187` — `flags = FLAG_ACTIVITY_NEW_TASK` overwrites intent flags. **FIXED:** `addFlags(...)`; mime `file.mimeType ?: "video/*"`.
19. `android/app/src/main/java/com/aruvi/tir/ui/components/MediaCard.kt:167` — `lowercase()` without locale (Turkish-I). **FIXED:** `lowercase(Locale.ROOT)`.
20. `android/app/src/main/java/com/aruvi/tir/ui/components/MediaCard.kt:32,229` + `android/app/src/main/java/com/aruvi/tir/ui/components/FolderCard.kt:26,97` — `basicMarquee()` is `ExperimentalFoundationApi` without `@OptIn`. **FIXED:** `@OptIn` annotations added.

### Security / data-loss
21. `android/app/src/main/java/com/aruvi/tir/download/FileDownloader.kt:118` — `fileName` unsanitized: `../` traversal + silent overwrite. **FIXED:** `sanitizeFileName()` (strip dirs, replace separators, blank→"download", 255 cap).
22. `android/app/src/main/java/com/aruvi/tir/download/FileDownloader.kt:236` — `deleteFile()` never cancels `activeJobs[id]` → zombie writer re-adds task. **FIXED:** cancel + cleanup, atomic `_tasks.update`.
23. `android/app/src/main/java/com/aruvi/tir/download/FileDownloader.kt:249` — `activeJobs[id]=job` overwrites without cancelling prior (double-resume → two writers). **FIXED:** cancel prior in `resume()` + `startDownload()`.
24. `android/app/src/main/java/com/aruvi/tir/download/FileDownloader.kt:85` — `enqueue` pause/cancel-before-start overwritten by later `startDownload`. **FIXED:** status check before starting.
25. `android/app/src/main/java/com/aruvi/tir/download/FileDownloader.kt:311` — `response`/`body` leaks on early returns/`IOException`. **FIXED:** `.use {}` block.
26. `android/app/src/main/java/com/aruvi/tir/download/FileDownloader.kt:387` — ignores `FileChannel.write` partial-write return → corrupt download. **FIXED:** `while (hasRemaining())` loop.
27. `android/app/src/main/java/com/aruvi/tir/download/FileDownloader.kt:314` — HTTP 416 treated as permanent failure. **FIXED:** truncate (MediaStore-safe) / delete (legacy) + retryable resume-from-0.
28. `android/app/src/main/java/com/aruvi/tir/download/FileDownloader.kt:442` — `_tasks.value = ...` read-modify-write from IO threads loses updates. **FIXED:** `_tasks.update {}` (+ import).
29. `android/app/src/main/java/com/aruvi/tir/data/api/AuthInterceptor.kt:23` — `path.contains("/auth/...")` substring match skips auth wrongly. **FIXED:** `endsWith(...)` exact suffix.
30. `android/app/src/main/java/com/aruvi/tir/data/model/GrabModels.kt:18` — `GrabSelectRequest.chatId: Int?` truncates Telegram 64-bit chat IDs (response model already `Long?`). **FIXED:** `Long?` (callers don't pass it yet — no caller breakage).
31. `android/app/src/main/java/com/aruvi/tir/data/model/User.kt:17` — `""` treated as present; fallback leaks `telegramId` (`"User $telegramId"`). **FIXED:** `isNullOrBlank()` checks, generic `"User"` fallback.
32. `android/.gitignore:1` — no keystore/secret patterns; signing keys committable. **FIXED:** added `*.jks *.keystore *.p12 *.pem *.key google-services.json .env`.

### Error handling / structured concurrency
33. `android/app/src/main/java/com/aruvi/tir/ui/components/NetworkErrorUtils.kt:12` — no `CancellationException` guard. **FIXED:** rethrow first line.
34. `android/app/src/main/java/com/aruvi/tir/data/repository/AuthRepository.kt:192` — `logout()` swallows `CancellationException`. **FIXED:** rethrow before generic catch.
35. `android/app/src/main/java/com/aruvi/tir/data/repository/SettingsRepository.kt:80` — `normalizeServerUrl` case-sensitive scheme check. **FIXED:** `ignoreCase = true`.
36. `android/app/src/main/java/com/aruvi/tir/data/repository/SettingsRepository.kt:90` — `setServerUrl("")` persists empty string → localhost fallback confusion. **FIXED:** ignore blank.
37. `android/app/src/main/java/com/aruvi/tir/data/repository/FilesRepository.kt:53` — `getFile()` maps every error to `"File not found"` (masks 401/500). **FIXED:** 404-specific message, else `HTTP <code>`.
38. `android/app/src/main/java/com/aruvi/tir/data/repository/FoldersRepository.kt:48` — same pattern for folders. **FIXED:** same treatment.

---

## Found but deliberately NOT fixed (need refactor / design / backend confirmation)

### Auth / token storage & threading (high — needs design)
- `android/app/src/main/java/com/aruvi/tir/data/repository/AuthRepository.kt:30` — tokens in plain DataStore; `security-crypto` dep declared but unused. Needs EncryptedSharedPreferences migration (not minimal).
- `android/app/src/main/java/com/aruvi/tir/di/NetworkModule.kt:114` — `runBlocking { getServerUrl() }` on main thread at startup (ANR risk). Needs DI redesign (sync default + async seed).
- `android/app/src/main/java/com/aruvi/tir/di/PlayerModule.kt:53` — ExoPlayer OkHttp client omits `DynamicBaseUrlInterceptor` (playback sticks to old server). One-line add but changes playback routing — left for playback-owner review.
- `android/app/src/main/java/com/aruvi/tir/data/api/AuthInterceptor.kt:30,46` — `runBlocking` on OkHttp dispatcher + `refreshMutex` pool-starvation; unauthenticated retry on refresh failure. Needs Authenticator redesign.
- `android/app/src/main/java/com/aruvi/tir/data/repository/AuthRepository.kt:107` — N queued 401s rotate N times (no failed-token dedup). Needs API change to `refreshAccessToken(failedToken)`.
- `android/app/src/main/AndroidManifest.xml:55` — `usesCleartextTraffic="true"` globally. Removing could break LAN/tunnel self-hosting; needs `networkSecurityConfig` design.
- `android/app/src/main/AndroidManifest.xml:93` — `AudioPlaybackService exported="true"`. Needs Media3 external-controller decision.
- `android/app/src/main/res/xml/file_paths.xml:3` — FileProvider exposes whole `Download/`. Needs UX decision on subdir scope.
- `android/app/src/main/java/com/aruvi/tir/TelePlayApp.kt:37` — Coil reuses BODY-logging client. Needs separate client decision.

### Player (large, high-risk — needs playback-owner review)
- `android/app/src/main/java/com/aruvi/tir/ui/player/PlayerViewModel.kt:1327` — Cast `setCurrentTime(ms?)` suspected seconds-vs-ms mismatch.
- `android/app/src/main/java/com/aruvi/tir/ui/player/PlayerViewModel.kt:1587` — `TIME_UNSET` position fed to UI; `:1604` truncation garbage; `:1673` `onCleared` save lost (scope cancelled); `:1634` `startForegroundService` bg crash (Android 12+); `:192` non-atomic `_uiState.value = copy` across coroutines (use `update{}`); `:1357` token URL logged; `:552` token in `technicalDetails`; `:1053` `currentFileId` plain-var race; `:734` cast-audio double-work; `:311` `cycleResizeMode` no-op while casting.
- `android/app/src/main/java/com/aruvi/tir/ui/player/PlayerScreen.kt:184` — number keys unguarded vs dialogs; `:951` seek-slider steps/precision; `:225` PlayerView never released.
- `android/app/src/main/java/com/aruvi/tir/ui/mobile/player/MobilePlayerScreen.kt:123` — resume-position race vs VM init; `:130` system-bars not restored; `:351` brightness not restored; `:236` competing gesture detectors; `:223` graphicsLayer on SurfaceView; `:159` BackHandler exits with sheet open. (Slider crash + formatTime fixed; rest need UX decisions.)
- `android/app/src/main/java/com/aruvi/tir/service/DownloadService.kt:63` — unguarded `startForeground` (Android 14+ `foregroundServiceType`); `:92` notification-ID overflow/collision; per-500ms notify spam.
- `android/app/src/main/java/com/aruvi/tir/ui/mobile/downloads/DownloadsViewModel.kt:75` — no enqueue dedup. `android/app/src/main/java/com/aruvi/tir/cast/CastOptionsProvider.kt:55` — hardcoded activity name.

### Navigation / viewmodels (behavior changes — needs product review)
- `android/app/src/main/java/com/aruvi/tir/ui/MainActivity.kt:31`, `android/app/src/main/java/com/aruvi/tir/ui/mobile/MobileMainActivity.kt:74`, `android/app/src/main/java/com/aruvi/tir/ui/navigation/NavGraph.kt:31` — frozen `startDestination` (logged-in users land on Login). Needs splash-gate nav redesign.
- `android/app/src/main/java/com/aruvi/tir/ui/mobile/home/MobileHomeViewModel.kt:58` — double-load/deep-link race; `:289` token-in-URL to external player + clipboard (prefer public link — product/security decision); `:200` ignored CRUD failures; `:283` logout/nav race.
- `android/app/src/main/java/com/aruvi/tir/ui/mobile/MobileNavigation.kt:98` — Player drops `fileId`/`directUrl`; `:148` resume position lost; `:164` `restoreState` folder-arg staleness.
- `android/app/src/main/java/com/aruvi/tir/ui/auth/LoginViewModel.kt:74` — bot-info fetch per keystroke (needs debounce); fragile expiry string-match; unvalidated URL persist.
- `android/app/src/main/java/com/aruvi/tir/ui/home/HomeViewModel.kt:83` — fallback masks error, ignores continueWatching.
- `android/app/src/main/java/com/aruvi/tir/ui/grab/TvGrabViewModel.kt:97`, `android/app/src/main/java/com/aruvi/tir/ui/mobile/grab/GrabViewModel.kt:104` — grabbing-identity int math can collide (needs shared String key — behavior change).
- `android/app/src/main/java/com/aruvi/tir/ui/settings/SettingsViewModel.kt:45` — uncaught settings loads; dual logout paths.
- `android/app/src/main/java/com/aruvi/tir/ui/browse/FolderScreen.kt:91` — empty state pushed off-screen by `fillMaxSize` grid (layout change).
- `android/app/src/main/java/com/aruvi/tir/ui/details/DetailsScreen.kt:240` — disk I/O in composition; `:739` "Play Offline" streams instead of local; `:725` absolute path disclosure.
- `android/app/src/main/java/com/aruvi/tir/ui/components/TvSound.kt:13` — no throttle; `ContentRow.kt:43` un-normalized thumb URL; `StateComponents.kt:136` ErrorState no focus request (TV D-pad trap); `TvAnimatedBackground.kt:32` always-on shaders; `FocusTrailBox.kt:236` 1s focus delay + per-frame allocs (perf redesign); `Theme.kt:81` dynamic colors discard brand.
- `android/app/src/main/java/com/aruvi/tir/ui/mobile/profile/MobileProfileScreen.kt:113` — dead Settings/Clear-Cache buttons; hardcoded version.
- `android/app/build.gradle.kts:69` — release silently signs with debug key (should fail build — CI policy decision); `:42` localhost default bakes into release; `:103` Compose/Kotlin version skew; `:114` dead splits block; `:194` unused security-crypto (kept for future token-encryption work).
- `android/gradle.properties:5` — `configureondemand=true` breaks Hilt/KAPT (build-policy change).
- `android/settings.gradle.kts:13` — jitpack availability risk.
- `android/app/proguard-rules.pro:5,15,23` — over-broad keeps; `:17` incomplete Hilt rules.
- `android/app/src/main/res/xml/file_paths.xml` + manifests + `local.properties.example` doc nits listed above.

No hardcoded secrets/tokens found in `android/` (server URL + signing passwords correctly sourced from `local.properties`/env).
