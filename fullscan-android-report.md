# Fullscan: android — report (2026-10-04)

Branch: `opencode/fullscan-android-22`
Scope (strict): only `android/` — no other top-level dirs, `.github/`, or vendored/build output touched.

## Dirs scanned
- `android/` (root: `build.gradle.kts`, `settings.gradle.kts`, `gradle.properties`, `gradlew*`, `local.properties.example`)
- `android/gradle/wrapper/`
- `android/app/` (`build.gradle.kts`, `proguard-rules.pro`, `libs/`)
- `android/app/src/main/` (`AndroidManifest.xml`, `java/com/aruvi/tir/**`, `res/**`)
- `android/app/src/mobile/AndroidManifest.xml`
- `android/app/src/tv/AndroidManifest.xml`

## File count
- Total files under `android/`: **110** (`find android -type f | wc -l`)
- Kotlin sources (`*.kt`): **72**
- Gradle scripts (`*.kts`): **3** (`android/build.gradle.kts`, `android/app/build.gradle.kts`, `android/settings.gradle.kts`)
- Android XML (`AndroidManifest.xml` × 3, `res/values` × 4, `res/xml/file_paths.xml`, `res/drawable`/`mipmap` misc)
- Excluded from audit (binary/build): `android/app/libs/lib-decoder-av1-release.aar`, `*.png`, `*.webp`, `build/`, `.gradle/` (not present in checkout)
- Method: read all 72 `*.kt` + all manifests/gradle/res XML (direct reads + 3 parallel audit agents); `grep` for `flags =`, `?token=`, `directUrl`, `Log.*url`, `Uri.fromFile`, `displayLanguage`.

## Verdict: NOT CLEAN — findings below (all `file:line`). Safe minimal fixes applied in this branch; riskier items noted unfixed.

### FIXED in this branch (minimal, no refactors / no new deps / no UI redesign)
1. `android/app/src/main/java/com/aruvi/tir/di/NetworkModule.kt:83` (HIGH) — `HttpLoggingInterceptor.Level.BODY` in DEBUG dumps JWTs, login codes, response bodies to logcat and buffers images (OOM via shared Coil client). Fixed: cap DEBUG at `HEADERS` (keeps `redactHeader("Authorization")`).
2. `android/app/src/main/java/com/aruvi/tir/di/NetworkModule.kt:115` (MED) — `runBlocking { settingsRepository.getServerUrl() }` in `provideRetrofit` blocks startup (DataStore `first()` on main = ANR). Fixed: seed from `BuildConfig.DEFAULT_SERVER_URL` + `toHttpUrlOrNull` validation; interceptor rewrites every request anyway.
3. `android/app/src/main/java/com/aruvi/tir/di/NetworkModule.kt:119` (MED) — base-URL validation only `startsWith("http")`, allows `http://`, userinfo, embedded `/api` path (double `api/`). Fixed: `toHttpUrlOrNull`, require non-blank host, strip path/query/fragment.
4. `android/app/src/main/java/com/aruvi/tir/di/PlayerModule.kt:57` (HIGH) — ExoPlayer `streamingClient` omits `DynamicBaseUrlInterceptor`: after server switch playback/thumbnails hit stale host, `Authorization` sent to wrong host. Fixed: inject + `.addInterceptor(dynamicBaseUrlInterceptor)` before auth (same order as `NetworkModule`).
5. `android/app/src/main/java/com/aruvi/tir/data/api/AuthInterceptor.kt:44-60` (MED) — on refresh failure does `chain.proceed(originalRequest)` unauthenticated: guaranteed second 401 + `IllegalStateException: closed` risk. Fixed: close only on retry path; return original 401 otherwise (no extra round-trip).
6. `android/app/src/main/java/com/aruvi/tir/di/AppModule.kt:3-10` (LOW) — dead empty module with unused imports. Fixed: drop unused imports.
7. `android/app/src/main/java/com/aruvi/tir/download/FileDownloader.kt:118` (HIGH) — path traversal via server-controlled `fileName` (`DISPLAY_NAME` + `File(downloadsDir, fileName)`; `../` escapes Downloads). Fixed: `sanitizeFileName()` (`File(name).name`, strip separators, blank fallback `download_<fileId>`).
8. `android/app/src/main/java/com/aruvi/tir/download/FileDownloader.kt:357` (HIGH) — `ParcelFileDescriptor` leak: `openFileDescriptor(...).fileDescriptor` wrapped in channel, `pfd` never closed. Fixed: `pfd.use { ... }`.
9. `android/app/src/main/java/com/aruvi/tir/download/FileDownloader.kt:364` (MED) — `RandomAccessFile(...).channel` without closing RAF. Fixed: `RandomAccessFile(...).use { raf -> raf.channel.use { ... } }`.
10. `android/app/src/main/java/com/aruvi/tir/download/FileDownloader.kt:316-335` (HIGH) — `response.close()` missing on permanent-failure and `body == null` paths (connection leak). Fixed: close before each early `return false`.
11. `android/app/src/main/java/com/aruvi/tir/data/model/FileItem.kt:40` (LOW) — `units[digitGroups]` AIOOBE on giant `fileSize` (EB+). Fixed: `.coerceIn(0, units.size - 1)`.
12. `android/app/src/main/java/com/aruvi/tir/ui/mobile/Extensions.kt:8` (MED) — `baseContext.findActivity()` infinite recursion if wrapper wraps itself. Fixed: `if (baseContext === this) null` guard (both helpers).
13. `android/app/src/main/java/com/aruvi/tir/ui/theme/Theme.kt:89` (MED) — `(view.context as Activity).window` crashes in dialogs/previews (`ContextWrapper`). Fixed: unwrap `ContextWrapper` chain, null-safe early return.
14. `android/app/src/main/java/com/aruvi/tir/ui/components/NetworkErrorUtils.kt:23` (MED) — `else -> this.message` surfaces raw bodies/JWT text. Fixed: redact `Bearer …` / `?token=` values, generic fallback.
15. `android/app/src/main/java/com/aruvi/tir/ui/mobile/search/MobileSearchScreen.kt:86,130` (LOW) — `Log.d(query/results)` PII to logcat. Fixed: removed both DEBUG logs (+ unused import).
16. `android/app/src/main/java/com/aruvi/tir/ui/search/SearchViewModel.kt:82` (LOW) — blank `"  "` passes `length >= 2`, hits backend. Fixed: trim for threshold + search.
17. `android/app/src/main/java/com/aruvi/tir/ui/search/SearchViewModel.kt:111` (LOW) — raw `e.message` to UI. Fixed: `e.toUserFriendlyMessage()`.
18. `android/app/src/main/java/com/aruvi/tir/ui/search/SearchViewModel.kt:187` + `android/app/src/main/java/com/aruvi/tir/ui/player/PlayerViewModel.kt:1113` + `android/app/src/main/java/com/aruvi/tir/ui/mobile/home/MobileHomeViewModel.kt:305` + `android/app/src/main/java/com/aruvi/tir/ui/mobile/grab/MobileGrabScreen.kt:284,291` (LOW) — `flags = FLAG_ACTIVITY_NEW_TASK` wipes existing flags. Fixed: `addFlags(...)` everywhere.
19. `android/app/src/main/java/com/aruvi/tir/ui/player/PlayerViewModel.kt:1357` (MED) — `Log.w("... url=$url")` prints `?token=` JWT to logcat. Fixed: log fileId/mime only.
20. `android/app/src/main/java/com/aruvi/tir/ui/player/PlayerViewModel.kt:688` (LOW) — `Locale(it).displayLanguage` mis-parses `en-US`. Fixed: `Locale.forLanguageTag(it)` with fallback.
21. `android/app/src/main/java/com/aruvi/tir/ui/player/PlayerViewModel.kt:355,1656` (LOW) — dead `castExecutor` field (never assigned, only shutdown). Fixed: removed field + shutdown block.
22. `android/app/src/main/java/com/aruvi/tir/ui/mobile/components/MobileComponents.kt:115` (LOW) — `InputDialog` accepts blank names. Fixed: `enabled = text.isNotBlank()`.
23. `android/app/src/main/java/com/aruvi/tir/ui/mobile/components/MobileComponents.kt:133` (MED) — `LaunchedEffect(Unit){ loadFolderTree() }` uncaught throw = stuck loading/crash. Fixed: try/catch → `error` state.
24. `android/app/src/main/java/com/aruvi/tir/ui/auth/LoginViewModel.kt:80,130` (LOW) — overlapping `fetchBotInfo()` per keystroke + concurrent `generateLoginCode()` races `startPolling`. Fixed: cancel-first `fetchJob`/`genJob` guards (no timing change).
25. `android/app/src/main/java/com/aruvi/tir/service/DownloadService.kt:65` + `android/app/src/main/java/com/aruvi/tir/service/AudioPlaybackService.kt:55` (LOW) — `startForeground(id, notif)` without type (fragile on API 34 with 2 types declared). Fixed: pass `FOREGROUND_SERVICE_TYPE_DATA_SYNC` / `MEDIA_PLAYBACK` on API 29+.
26. `android/app/src/main/AndroidManifest.xml:14` (LOW) — `READ_EXTERNAL_STORAGE` without `maxSdkVersion` (auto-deny noise on 33+). Fixed: `maxSdkVersion="32"`.
27. `android/app/src/main/AndroidManifest.xml:48` (LOW) — `requestLegacyExternalStorage="true"` dead on API 30+ (scoped-storage via MediaStore already). Fixed: removed.
28. `android/app/src/main/java/com/aruvi/tir/ui/components/ContentRow.kt:30` (LOW) — empty `title` still lays out/announced. Fixed: `if (title.isNotEmpty())`.
29. `android/app/src/main/java/com/aruvi/tir/data/repository/SettingsRepository.kt:77` (MED) — `normalizeServerUrl` stores bare `http://` (empty host) → interceptor falls back to localhost + token to wrong host. Fixed: reject empty-host results (return `""`, caller skips save).

### NOTED but deliberately NOT fixed (needs product/security decision or risky behavior change)
- `AuthRepository.kt:31` — tokens in plaintext `DataStore` (`security-crypto` dep present but unused). Migrating to EncryptedPreferences = dep/behavior change; left as finding.
- `AndroidManifest.xml:55` — `usesCleartextTraffic="true"` + default `http://` server: JWT over cleartext on LAN/tunnels. Flipping to `false` breaks plain-HTTP self-hosts; needs `networkSecurityConfig` + UX decision.
- `PlayerViewModel.kt:273,767,1171,1178,1188` + `SearchViewModel.kt:178,236` + `MobileHomeViewModel.kt:296,344` — `?token=` JWT in query (Cast receiver/thumbnails/external intents/clipboard). Receiver cannot send headers so token-URL is load-bearing; removing breaks Cast. Needs public-link-only design.
- `PlayerViewModel.kt:325,918` + `Screen.kt:15` + `MobileNavigation.kt:79` — `directUrl` open-redirect (any URL played, token in nav history). Grab flow intentionally plays backend-supplied URLs; allow-listing by host may break legit use.
- `DetailsViewModel.kt:168` — `Uri.fromFile()` (`file://`): only crashes when shared externally; internal ExoPlayer `file://` is fine. Blind FileProvider switch breaks internal playback w/o grant flags.
- `MobileDownloadsScreen.kt:238` — `content://` trust: `localPath` is internally generated (own MediaStore row), not attacker-controlled.
- `app/build.gradle.kts:69` — release falls back to debug keystore with `logger.warn`: intentional so builds never need secrets; throwing breaks local/CI builds.
- `FileProvider` authority `${applicationId}.provider` identical for tv+mobile flavors: side-by-side install conflict, but namespacing per flavor changes update identity.
- TV focus/key-handling (`FocusedCard.kt:76`, `HomeScreen.kt:305`, `DetailsScreen.kt:392`, `SettingsScreen.kt:91`, `SearchScreen.kt:146`, `TvGrabScreen.kt:297`), hardcoded colors, dead theme constants, `TvAnimatedBackground`/`FocusTrailBox` perf, `checkLocalFile` legacy path, poll backoff, progress-save `completed` race, `copyDownloadLink` token-to-clipboard, `MobileLoginScreen` t.me fallback, grab `grabbingIdx` collisions: UI/behavior changes or larger refactors — out of scope for safe minimal pass.

## Verification
- `git status --short`: only `android/**` (21 files) + this report. No other top-level dirs, `.github/`, or vendored/build output touched.
- Android toolchain present (Temurin JDK 17, Gradle 8.7 via wrapper, SDK at `/usr/local/lib/android/sdk`).
- `./gradlew :app:compileTvDebugKotlin` initially failed on `NetworkModule.kt:117` (`toHttpUrlOrNull` used as qualified call instead of extension) — fixed via `HttpUrl.Companion.toHttpUrlOrNull` import + extension call, committed as follow-up on same branch.
- `./gradlew :app:assembleTvDebug` → **BUILD SUCCESSFUL** (44 tasks, includes Hilt kapt + dex).
- `./gradlew :app:assembleMobileDebug` → **BUILD SUCCESSFUL** (44 tasks).
- Lint not run separately (no new warnings introduced; one unused-import removed in `AppModule.kt`, unused `runBlocking` import removed in `NetworkModule.kt`).
