# Fullscan: android — report (2026-10-11, run 23)

Branch: `opencode/fullscan-android-23`
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
- Prior open PR for this area: #74 (`opencode/fullscan-android-22`, still OPEN, 21 android files + report). This run rebases those fixes onto current `main` (no `.github/` drift) and adds NEW findings below — not a duplicate, a superset on fresh base.

## Verdict: NOT CLEAN — findings below (all `file:line`). Safe minimal fixes applied in this branch; riskier items noted unfixed.

### FIXED in this branch (minimal, no refactors / no new deps / no UI redesign)

#### Inherited from PR #74 (re-applied on current main, still needed — verified present in pre-fix tree)
1. `android/app/src/main/java/com/aruvi/tir/di/NetworkModule.kt:83` (HIGH) — `HttpLoggingInterceptor.Level.BODY` in DEBUG dumps JWTs. Fixed: cap DEBUG at `HEADERS`.
2. `android/app/src/main/java/com/aruvi/tir/di/NetworkModule.kt:115` (MED) — `runBlocking { settingsRepository.getServerUrl() }` blocks startup. Fixed: seed from `BuildConfig.DEFAULT_SERVER_URL` + `toHttpUrlOrNull`.
3. `android/app/src/main/java/com/aruvi/tir/di/NetworkModule.kt:119` (MED) — base-URL validation only `startsWith("http")`. Fixed: `toHttpUrlOrNull`, require host, strip path/query.
4. `android/app/src/main/java/com/aruvi/tir/di/PlayerModule.kt:57` (HIGH) — ExoPlayer `streamingClient` omits `DynamicBaseUrlInterceptor`. Fixed: inject + add before auth.
5. `android/app/src/main/java/com/aruvi/tir/data/api/AuthInterceptor.kt:44-60` (MED) — refresh-failure re-proceeds unauthenticated. Fixed: return original 401, close only on retry.
6. `android/app/src/main/java/com/aruvi/tir/di/AppModule.kt:3-10` (LOW) — dead empty module imports. Fixed: drop unused imports.
7. `android/app/src/main/java/com/aruvi/tir/download/FileDownloader.kt:118` (HIGH) — path traversal via `fileName`. Fixed: `sanitizeFileName()`.
8. `android/app/src/main/java/com/aruvi/tir/download/FileDownloader.kt:357` (HIGH) — `ParcelFileDescriptor` leak. Fixed: `pfd.use { }`.
9. `android/app/src/main/java/com/aruvi/tir/download/FileDownloader.kt:364` (MED) — `RandomAccessFile` channel leak. Fixed: `use {}` nesting.
10. `android/app/src/main/java/com/aruvi/tir/download/FileDownloader.kt:316-335` (HIGH) — `response.close()` missing on failure paths. Fixed: close before early return.
11. `android/app/src/main/java/com/aruvi/tir/data/model/FileItem.kt:40` (LOW) — `units[digitGroups]` AIOOBE. Fixed: `coerceIn`.
12. `android/app/src/main/java/com/aruvi/tir/ui/mobile/Extensions.kt:8` (MED) — `findActivity()` self-wrap recursion. Fixed: identity guard.
13. `android/app/src/main/java/com/aruvi/tir/ui/theme/Theme.kt:89` (MED) — `(view.context as Activity)` crash. Fixed: unwrap `ContextWrapper`.
14. `android/app/src/main/java/com/aruvi/tir/ui/components/NetworkErrorUtils.kt:23` (MED) — raw message surfaces tokens. Fixed: redact Bearer/token.
15. `android/app/src/main/java/com/aruvi/tir/ui/mobile/search/MobileSearchScreen.kt:86,130` (LOW) — `Log.d` PII. Fixed: removed.
16. `android/app/src/main/java/com/aruvi/tir/ui/search/SearchViewModel.kt:82` (LOW) — blank query hits backend. Fixed: trim threshold.
17. `android/app/src/main/java/com/aruvi/tir/ui/search/SearchViewModel.kt:111` (LOW) — raw `e.message` to UI. Fixed: user-friendly.
18. `android/app/src/main/java/com/aruvi/tir/ui/search/SearchViewModel.kt:187` + `PlayerViewModel.kt:1113` + `MobileHomeViewModel.kt:305` + `MobileGrabScreen.kt:284,291` (LOW) — `flags =` wipes flags. Fixed: `addFlags`.
19. `android/app/src/main/java/com/aruvi/tir/ui/player/PlayerViewModel.kt:1357` (MED) — `Log.w url=` prints token. Fixed: log fileId/mime only.
20. `android/app/src/main/java/com/aruvi/tir/ui/player/PlayerViewModel.kt:688` (LOW) — `Locale(it).displayLanguage` mis-parses. Fixed: `forLanguageTag`.
21. `android/app/src/main/java/com/aruvi/tir/ui/player/PlayerViewModel.kt:355,1656` (LOW) — dead `castExecutor`. Fixed: removed.
22. `android/app/src/main/java/com/aruvi/tir/ui/mobile/components/MobileComponents.kt:115` (LOW) — blank names accepted. Fixed: `isNotBlank` guard.
23. `android/app/src/main/java/com/aruvi/tir/ui/mobile/components/MobileComponents.kt:133` (MED) — uncaught `loadFolderTree`. Fixed: try/catch.
24. `android/app/src/main/java/com/aruvi/tir/ui/auth/LoginViewModel.kt:80,130` (LOW) — overlapping fetch/generate races. Fixed: cancel-first guards.
25. `android/app/src/main/java/com/aruvi/tir/service/DownloadService.kt:65` + `AudioPlaybackService.kt:55` (LOW) — `startForeground` without type. Fixed: pass type on API 29+.
26. `android/app/src/main/AndroidManifest.xml:14` (LOW) — `READ_EXTERNAL_STORAGE` without maxSdk. Fixed: `maxSdkVersion="32"`.
27. `android/app/src/main/AndroidManifest.xml:48` (LOW) — dead `requestLegacyExternalStorage`. Fixed: removed.
28. `android/app/src/main/java/com/aruvi/tir/ui/components/ContentRow.kt:30` (LOW) — empty title layout. Fixed: `isNotEmpty` guard.
29. `android/app/src/main/java/com/aruvi/tir/data/repository/SettingsRepository.kt:77` (MED) — stores bare `http://`. Fixed: reject empty host.

#### NEW in run 23 (not covered by #74)
30. `android/app/src/main/java/com/aruvi/tir/data/repository/AuthRepository.kt:107-126` (HIGH) — `refreshAccessToken()` called `clearAuth()` on ANY non-200 (429/500/502) and on 200+null body, logging user out on transient errors. Fixed: only `clearAuth()` on 401/403; otherwise return null preserving tokens.
31. `android/app/src/main/java/com/aruvi/tir/data/repository/AuthRepository.kt:192-199` (MED) — `logout()` `catch (Exception)` swallows `CancellationException`. Fixed: rethrow cancellation before generic catch.
32. `android/app/src/main/java/com/aruvi/tir/data/model/GrabModels.kt:18` (HIGH) — `GrabSelectRequest.chatId: Int?` truncates real channel IDs (`-100...` exceeds Int.MAX) while result carries `Long?`. Fixed: `Long?`.
33. `android/app/src/main/java/com/aruvi/tir/data/api/AuthInterceptor.kt:22-27` (MED) — skip-list misses public `auth/bot/info` (called pre-login), wastes refresh rotation. Fixed: add `/auth/bot/info` to skip.
34. `android/app/src/main/java/com/aruvi/tir/data/api/AuthInterceptor.kt:30` (MED) — `runBlocking { getAccessToken() }` unguarded; DataStore `IOException` escapes interceptor. Fixed: try/catch → null (proceed unauthenticated).
35. `android/app/src/main/java/com/aruvi/tir/di/NetworkModule.kt:44-47` (MED) — download client logs `HEADERS` in release (URLs, Range). Fixed: `if (DEBUG) HEADERS else NONE`.
36. `android/app/src/main/java/com/aruvi/tir/download/FileDownloader.kt:102-108` (MED) — `enqueue()` throw in `createDestination` leaves task stuck PENDING (SupervisorJob swallows). Fixed: try/catch → FAILED with error.
37. `android/app/src/main/java/com/aruvi/tir/download/FileDownloader.kt:404` (MED) — progress emit overwrites concurrent `pause()` (stale RUNNING copy resurrects task). Fixed: only emit if live status still RUNNING.
38. `android/app/src/main/java/com/aruvi/tir/download/FileDownloader.kt:437-441` (MED) — disk-full `ENOSPC` retried 10× with backoff. Fixed: fail fast on `ENOSPC` (message check) → FAILED, no retry.
39. `android/app/src/main/java/com/aruvi/tir/ui/grab/TvGrabViewModel.kt:99-109` (HIGH) — `grabItem` reads `_state.value.query` INSIDE launch; query edit mid-flight grabs wrong file. Fixed: snapshot `q` before launch.
40. `android/app/src/main/java/com/aruvi/tir/ui/mobile/grab/GrabViewModel.kt:106-116` (HIGH) — same query snapshot race. Fixed: same.
41. `android/app/src/main/java/com/aruvi/tir/ui/mobile/home/MobileHomeScreen.kt:564-569` (MED) — `ContinueWatchingCard` hardcodes `0.5f` progress. Fixed: use `progressPercent`.
42. `android/app/src/main/java/com/aruvi/tir/ui/mobile/downloads/MobileDownloadsScreen.kt:164,190` (MED) — `toFloat()` division loses precision on GB files. Fixed: `toDouble()` math, `toFloat()` only for indicator.
43. `android/app/src/main/java/com/aruvi/tir/ui/grab/TvGrabScreen.kt:460-467` + `android/app/src/main/java/com/aruvi/tir/ui/mobile/player/MobilePlayerScreen.kt:1039-1045` + `android/app/src/main/java/com/aruvi/tir/service/DownloadService.kt:201-212` (LOW) — `String.format("%.1f")` without Locale → comma decimals. Fixed: `Locale.US`.
44. `android/app/src/main/AndroidManifest.xml` (MED) — external-player `resolveActivity` false-negative on API 30+ (no `<queries>`). Fixed: add `<queries>` for `ACTION_VIEW video/*`.
45. `android/app/src/main/java/com/aruvi/tir/ui/player/PlayerViewModel.kt:1679-1685` (MED) — teardown guard misses `directUrl` (`mediaId="stream"` never equals fileId → leak). Fixed: treat `"stream"` as owned.

### NOTED but deliberately NOT fixed (needs product/security decision or risky behavior change)
- Tokens in plaintext DataStore (`AuthRepository.kt:40-59`; `security-crypto` dep unused) — EncryptedPreferences migration = behavior change.
- `usesCleartextTraffic="true"` + default `http://` — flipping breaks plain-HTTP self-hosts; needs `networkSecurityConfig`.
- `?token=` JWT in query (Cast/external/clipboard: `PlayerViewModel`, `SearchViewModel:170-182`, `MobileHomeViewModel:289-311`, `MobileGrabScreen:257-273`) — receiver cannot send headers; needs short-lived download-token design.
- `directUrl` open-redirect (`PlayerViewModel:325,918`, `Screen.kt:15`) — grab flow intentionally plays backend URLs; allow-list may break legit use.
- `Uri.fromFile` (`DetailsViewModel.kt:168`) — internal ExoPlayer `file://` fine; blind FileProvider switch breaks playback.
- Concurrent-401 double-refresh still possible (mutex serializes but second waiter re-uses rotated token) — needs failed-token double-check; left as follow-up (risky auth change).
- `FileDownloader` pause/cancel cannot unblock in-flight socket read; `activeJobs` check-then-act duplicate-job race — needs Call-handle redesign; noted.
- `DetailsViewModel` MediaStore invisible + download state-machine dead-end + `deleteLocalFile` bypass — needs ViewModel wiring change; noted.
- `NavGraph`/`MobileNavigation` `startDestination` frozen on cold start; `HomeViewModel` concurrent loads; `MobileHomeViewModel` deep-link race; `grabbingIdx` int collisions — UI/behavior changes, out of scope for minimal pass.
- `TelePlayTheme(darkTheme)` dead param; `FocusTrailStyle` per-recomp alloc; thumbnail string-concat in 8 places; `DownloadsViewModel` dead deps + per-emit sort — refactors, noted.

## Verification
- `git status --short`: only `android/**` + this report. No other top-level dirs, `.github/`, or vendored/build output touched.
- Toolchain: Temurin JDK 17, Gradle 8.7 via wrapper, SDK at `/usr/local/lib/android/sdk`.
- `./gradlew :app:assembleTvDebug` → **BUILD SUCCESSFUL** (44 tasks, Hilt kapt + dex).
- `./gradlew :app:assembleMobileDebug` → **BUILD SUCCESSFUL** (44 tasks, 10 from cache).
- Only pre-existing warnings (deprecated `LocalLifecycleOwner`, unused `onBackClick`, `darkTheme` param noted above); no new warnings from this branch.

Fix PR: https://github.com/tirforge/Aruvi/pull/90
