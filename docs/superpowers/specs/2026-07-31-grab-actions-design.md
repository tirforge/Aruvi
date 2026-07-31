# Grab Screen Actions: Watch Now (in-app), VLC, Download, Back + Navbar Fix

Date: 2026-07-31
Status: Approved (verbal) / pending spec review
App: Aruvi mobile (`com.aruvi.tir`, flavor `mobile`)
Files: `app/src/main/java/com/aruvi/tir/ui/mobile/grab/MobileGrabScreen.kt`,
`GrabViewModel.kt`, `ui/mobile/MobileNavigation.kt`, `ui/navigation/Screen.kt` (no change — reused)

## Problem

The grab result dialog ("Ready to Watch!") has one "Watch Now" button that opens
an arbitrary external player via generic `ACTION_VIEW` — it does not play inside
the app, does not specifically launch VLC, and has no download action.
Additionally, the bottom-nav "Search Movies" label wraps to two lines, pushing
the Movie icon 23px above the other tab icons.

## Existing building blocks (no new dependencies)

- In-app ExoPlayer: `MobilePlayerScreen` + `PlayerViewModel` already reads
  `directUrl` from the nav SavedStateHandle (TV flavor uses it). Mobile route
  `player/{fileId}` just never passes a URL.
- `FileDownloader.enqueue(fileId: Int, fileName, url, mimeType)` — authenticated
  OkHttp downloader; Downloads tab already lists tasks with progress/pause/resume.
- VLC confirmed installed on device (`org.videolan.vlc`).

## Design

### 1. Grab result dialog → 4 buttons

Replace the current single "Watch Now" (external ACTION_VIEW) + "Close" with:

- **Watch Now** — plays inside the app: navigate to the in-app player route with
  the grab `streamUrl` as `directUrl`.
- **VLC** — explicit redirect: `Intent(ACTION_VIEW)` with
  `setDataAndType(streamUrl, "video/*")` + `setPackage("org.videolan.vlc")`.
  Fallback: if VLC not installed (ActivityNotFoundException), fall back to
  generic `ACTION_VIEW`; if that fails, Toast "No player found".
- **Download** — `FileDownloader.enqueue(fileId = result.id ?: 0, result.name,
  result.streamUrl, "video/*")` via a new `GrabViewModel.download(result)`
  method; Toast "Download started". Appears in the existing Downloads tab.
- **Back** — dismiss dialog (replaces the "Close" TextButton).

### 2. Wire in-app playback route for grab streams

- `MobileNavigation.kt`: change the mobile player composable route from
  `player/{fileId}` to `player/{fileId}?startPosition={startPosition}&directUrl={directUrl}`
  (same shape as the TV `Screen.Player` route; add navArguments: `fileId` Int,
  `startPosition` Long default 0, `directUrl` String nullable default null).
  Pass `startPosition` into `MobilePlayerScreen(startPosition = ...)`.
- `MainAppScreen.onNavigateToPlayer` signature: `(Int) -> Unit` →
  `(Int, String?) -> Unit`; callers (`MobileHomeScreen`, `MobileSearchScreen`)
  pass `fileId` with `directUrl = null`.
- In `MobileScaffold`, navigate with `Screen.Player.createRoute(fileId, 0L, directUrl)`.
- `MobileGrabScreen` gains an `onPlayStream: (String) -> Unit` callback; the
  Watch Now button calls it with `result.streamUrl`.

### 3. Navbar fix

- `MobileNavigation.kt` `BottomNavItem.Grab`: title `"Search Movies"` → `"Movies"`
  (one line; icon aligns with the other three tabs).
- Unselected icon: `Icons.Outlined.Movie` (currently Filled for both states) for
  visual consistency with the other tabs.

## Data flow

1. User taps Grab on a result card → `grabItem` → `GrabSelectResponse(name, size,
   streamUrl, ...)` → dialog.
2. Watch Now → `onPlayStream(streamUrl)` → rootNav `player/0?startPosition=0&directUrl=<encoded>`
   → `PlayerViewModel` picks up `directUrl` from SavedStateHandle → ExoPlayer plays.
3. Download → `GrabViewModel.download()` → `FileDownloader.enqueue(...)` → task in
   Downloads tab.
4. VLC → explicit VLC intent.

## Error handling

- VLC missing → generic player fallback → Toast.
- Download enqueue failure → Toast error.
- Player load failure → existing `PlayerErrorScreen` (has Retry / External Player /
  Go Back).

## Testing

No unit-test seam exists in the project (no src/test, no src/androidTest) —
flagging as a known finding. Verification is on-device via adb:
- Build `assembleMobileDebug`, install, login.
- Search → Grab a result → verify dialog shows 4 buttons.
- Watch Now → in-app player starts (check topResumedActivity / logcat).
- VLC → VLC app foregrounds with stream.
- Download → task appears in Downloads tab.
- Navbar: dump UI — "Movies" label one line, icon Y aligned with siblings
  (2121–2189), no crash.

## Out of scope

- Server-side / mirrorbot downloads (this is phone-side download only).
- TV flavor changes.
- Quality selection for grab streams.
