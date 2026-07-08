# Aruvi — Agent Guide

## Never touch
`data/`, `di/`, `download/`, `service/`, `TelePlayApp.kt` — upstream `subinps/TelePlay` code. Backend changes break sync. Safe directories: `ui/` (TV), `ui/mobile/` (phone), `ui/player/` (shared).

## Build commands
```bash
# Debug session (compile only, never full APK during dev)
GRADLE_USER_HOME=/tmp/.gradle ./gradlew kaptTvDebugKotlin compileTvDebugKotlin     # TV
GRADLE_USER_HOME=/tmp/.gradle ./gradlew kaptMobileDebugKotlin compileMobileDebugKotlin  # Mobile

# Full APK (final verification only)
GRADLE_USER_HOME=/tmp/.gradle ./gradlew assembleMobileRelease    # 6-8min (R8)
GRADLE_USER_HOME=/tmp/.gradle ./gradlew assembleMobileDebug      # ~2min
```

Always prefix with `GRADLE_USER_HOME=/tmp/.gradle` to avoid filling disk. Debug session = compile check only. Release APKs use R8 minification.

## Product flavors
Both flavors share all `.kt` source. Different AndroidManifest only:
- **mobile**: `targetSdk=36`, `touchscreen required="true"`, launcher = `MobileMainActivity`
- **tv**: `targetSdk=30` (broader TV compatibility), `leanback required="true"`, launcher = `MainActivity`

ABI splits: `armeabi-v7a`, `arm64-v8a`, `x86`, `x86_64` + universal APK.

## TV animation rule
Always use `Modifier.graphicsLayer { scaleX; scaleY; alpha }` — NEVER `Modifier.scale()`. The latter triggers layout pass and causes jank on leanback hardware.

## CI/CD (separate repo)
No workflow files in Aruvi. All CI lives in `Thirupathi-pirate/Aruvi-workflow`.
```bash
git push origin main          # Aruvi dev repo
git push workflow main        # trigger release build on Aruvi-workflow
```
Add the workflow remote if missing:
```bash
git remote add workflow https://github.com/Thirupathi-pirate/Aruvi-workflow.git
```

## Signing
Passwords via env vars (`RELEASE_STORE_PASSWORD`, `RELEASE_KEY_PASSWORD`) or `local.properties`. Keystore: `../my-release-key.jks` (relative to `app/`). Env vars override `local.properties`.

## Server URL
Default: `https://movie.aaruvi.space`. Override in `local.properties` (`TELEGRAM_TV_SERVER_URL`) or in-app settings.

## Key conventions
- **R8 full mode disabled** — `android.enableR8.fullMode=false` in `gradle.properties` (breaks Retrofit/Gson)
- **gradle.properties**: `-Xmx8g -XX:MaxMetaspaceSize=512m`, parallel + caching, 4 workers
- **TV targetSdk 30** — `RenderEffect` (requires API 31+) not used; brightness lift via alpha dim (0.88→1.0)
- **No bouncy springs** on TV — use `DampingRatioNoBouncy` + `StiffnessHigh`
- **Double-tap seek** — mobile only, left half rewind 10s, right half forward 10s (accelerates: 10→30→60→120→300s on rapid repeats within 1.5s)
- **Subtitles default off** — `PlayerViewModel` init disables `C.TRACK_TYPE_TEXT`
- **Move picker dialog** — self-contained, uses `loadFolderTree` suspend lambda; internal navigation stack; defined in `ui/mobile/components/MobileComponents.kt`
- **ExoPlayer buffer config** at `di/PlayerModule.kt:77-82` — `setBufferDurationsMs(min=32000, max=64000, playback=10000, rebuffer=10000)`
- **3 OkHttp clients** — `NetworkModule.kt` (API 30s timeout + download 5min read), `PlayerModule.kt` (streaming, no body logging); modify the right one
- **AuthInterceptor** (`data/api/AuthInterceptor.kt`) — adds Bearer token from session, retries on 401 with token refresh
- **Coil pre-configured** — `TelePlayApp.kt` registers an `ImageLoaderFactory`; all `AsyncImage` usage uses it automatically
- **Chromecast crash history** in `docs/cast.md` — `CastContext` must init on main thread; `PendingIntent.FLAG_MUTABLE` required for API 31+; proguard keep rules in `proguard-rules.pro`

## Entrypoints
- TV: `ui/MainActivity.kt` → `ui/navigation/NavGraph.kt`
- Mobile: `ui/mobile/MobileMainActivity.kt` → `ui/mobile/MobileNavigation.kt`
- Player ViewModel (shared): `ui/player/PlayerViewModel.kt`
