# Aruvi Codebase — Bug & Performance Report

## Summary

Systematic review of the 57 Kotlin source files across the Aruvi Android app data layer, DI, UI, downloader, and services. Found **11 bugs** spanning correctness (data races, resource leaks), security (token in URL query params), performance (unnecessary recomposition, missing caching), and reliability (silent failures, untracked scope).

---

## BUG-1: Token Leaked in Stream URL Query Parameter

**Severity: HIGH**  
**File:** `ui/player/PlayerViewModel.kt`, lines 565–571, 641–648, 669–673, 679–681  
**Type:** Security / Correctness

The access token is appended as a plain URL query parameter (`?token=$token`). This leaks the token to:
- Server access logs
- Any intermediate proxies
- The Android `Intent` system when opening in external players (line 651)
- Cast device control messages

**Fix:** Use the `AuthInterceptor` (which already exists and works for API calls) for streaming requests instead of inline token parameters. The `OkHttpDataSource.Factory` in `PlayerModule` already includes the `AuthInterceptor`. The player should use the `/api/stream/{id}` URL **without** a token param — the interceptor adds the `Authorization` header automatically.

---

## BUG-2: Download Resource Leak — RandomAccessFile Not Closed on Exception

**Severity: HIGH**  
**File:** `download/FileDownloader.kt`, lines 224–265  
**Type:** Resource Leak / Reliability

`RandomAccessFile` is opened at line 224 but the `close()` at line 265 is **outside** the `try/catch` block. If an exception occurs between line 225 and 265 (network error, disk full, cancellation), `raf.close()` never executes, leaking the file descriptor.

The `inputStream.use { stream -> ... }` block (line 235) properly wraps the stream, but the `raf` is not within any `use {}` block.

**Fix:** Move `raf` inside a `use {}` block or wrap in a try/finally.

---

## BUG-3: Race Condition in Download State Updates

**Severity: MEDIUM**  
**File:** `download/FileDownloader.kt`, lines 297–301, 255–260  
**Type:** Concurrency

`updateTask()` does a read-copy-write on `_tasks.value` without synchronization:

```kotlin
private fun updateTask(task: DownloadTask) {
    val currentTasks = _tasks.value.toMutableMap()  // read
    currentTasks[task.id] = task                     // modify
    _tasks.value = currentTasks                      // write
}
```

Since downloads run on `Dispatchers.IO` and `updateTask` is called from the download coroutine AND from `pause()`/`cancel()`/`resume()` (which can be called from main thread), there's a race: two concurrent calls can each copy the map, apply their change, and write — one overwrites the other's change.

**Fix:** Use `_tasks.update { ... }` (atomic `MutableStateFlow.update`) or synchronize.

---

## BUG-4: ProgressTracking Infinite Loop — No Cancellation Check

**Severity: MEDIUM**  
**File:** `ui/player/PlayerViewModel.kt`, lines 885–903  
**Type:** Reliability

The `while (true)` loop at line 888 has no `isActive` / `currentCoroutineContext().isActive` check. It relies on coroutine cancellation via `viewModelScope`. If something leaks the scope or the job isn't properly cancelled, this loop runs forever, wasting battery and CPU.

**Fix:** Change `while (true)` to `while (isActive)`.

---

## BUG-5: Unbounded CoroutineScope in DownloadService

**Severity: MEDIUM**  
**File:** `service/DownloadService.kt`, line 33  
**Type:** Memory / Reliability

```kotlin
private val serviceScope = CoroutineScope(SupervisorJob() + Dispatchers.Main)
```

This scope is never cancelled if `onDestroy()` doesn't run (Android can kill services without calling `onDestroy` in some cases). More critically, the `collect` on `fileDownloader.tasks` (line 69) runs in this scope — if the service is restarted, a new scope is created but the old one may not be cleaned up.

**Fix:** Use `lifecycleScope` from a LifecycleService, or cancel in `onStartCommand` before reassigning.

---

## BUG-6: Login Code Already Used — Silent Fail on Concurrent Clients

**Severity: MEDIUM**  
**File:** `data/repository/AuthRepository.kt`, line 147  
**Type:** Correctness

The `verifyLoginCode` method maps HTTP 404 to "Code not yet confirmed". However, if a login code was already used by another client, the backend returns... also likely 404 or 410. There's no way to distinguish "waiting for confirmation" from "already consumed by another device."

The frontend polls this endpoint. If the user logs in on device A, then opens the app on device B and sees a new code, the old code on device A will 404 forever — the user just sees "Code not yet confirmed" indefinitely.

**Fix:** This is partly backend-side, but the frontend should detect a successful login by an *active push* mechanism (WebSocket) or at minimum show a different message if the code was already confirmed (the `/auth/me` endpoint could be checked).

---

## BUG-7: Missing `@OptIn` Warning Suppression on PlayerView Usage

**Severity: LOW**  
**File:** `ui/player/PlayerScreen.kt`, lines 195–212  
**Type:** Correctness / Maintenance

`PlayerView` is from `androidx.media3.ui` which is `@UnstableApi`. The `@OptIn(UnstableApi::class)` annotation is present on ViewModel functions but **not** on the `PlayerScreen` composable where `AndroidView { PlayerView(context) }` is used.

This may cause compilation warnings and could break with future Media3 API changes.

**Fix:** Add `@OptIn(UnstableApi::class)` to the `PlayerScreen` composable or the lambda.

---

## BUG-8: Search `per_page` Mismatch — Files Endpoint vs Search Endpoint

**Severity: LOW**  
**File:** `data/api/TelePlayApi.kt`, lines 77–81  
**Type:** Correctness

```kotlin
@GET("files")
suspend fun searchFiles(
    @Query("search") query: String,
    @Query("per_page") limit: Int = 50
): Response<PaginatedResponse<FileItem>>
```

This calls the same `GET /files` endpoint as `getFiles()`. The `searchFiles` method passes `query` as a `search` parameter, but the `getFiles` method has `@Query("search") search: String? = null`. Both map to the same Retrofit method signature. The search function doesn't pass `includeAll`, so the backend may paginate results differently.

**Minor issue:** `searchFiles` passes `limit` as `per_page`, `getFiles` passes `perPage` as `per_page`. They're the same query param, but the semantics differ (search expects limit, list expects perPage). These are the same Retrofit endpoint with different defaults.

**Fix:** Remove `searchFiles()` entirely and use `getFiles(search = query, perPage = limit)` in the repository.

---

## BUG-9: `FilesRepository.searchFiles` Returns Items Directly vs `getFiles` Returns PaginatedResponse

**Severity: LOW**  
**File:** `data/repository/FilesRepository.kt`, lines 56–67  
**Type:** API Inconsistency

```kotlin
suspend fun searchFiles(query: String, limit: Int = 50): Result<List<FileItem>>
// vs
suspend fun getFiles(...): Result<PaginatedResponse<FileItem>>
```

Search unwraps the paginated response and returns only items, losing pagination metadata. This means search results are capped at 50 with no way to load more.

**Fix:** Make search also return `PaginatedResponse<FileItem>` for consistency, or document the limitation.

---

## BUG-10: Player `onTracksChanged` Called Too Early — NPE Risk

**Severity: LOW**  
**File:** `ui/player/PlayerViewModel.kt`, line 292–294  
**Type:** Correctness

```kotlin
override fun onTracksChanged(tracks: Tracks) {
    updateTracks()
}
```

`updateTracks()` accesses `exoPlayer.currentTracks`. During early initialization, this may be `null` or return an empty/partial track list before `STATE_READY`. The code has a redundant `tracks` parameter that's ignored — it should use the parameter instead of reading from the player.

**Fix:** Pass `tracks` to `updateTracks(tracks)` instead of reading from `exoPlayer.currentTracks`.

---

## BUG-11: `JUMP_TO_POSITION` Dialog — Minutes/Secs > 59 Not validated

**Severity: LOW**  
**File:** `ui/player/PlayerScreen.kt`, lines 1017–1019, 1137–1139  
**Type:** Correctness

The time input fields only validate `length <= 2` and `isDigit()`, but do not clamp `minutes` to 0..59 or `seconds` to 0..59. A user can enter "99:99:99" which will attempt to seek beyond the duration (though `seekTo` clamps to duration). This is confusing UX.

**Fix:** Clamp minutes and seconds values in the `onJump` callback.

---

## Performance Issues Summary

| # | Issue | Location | Impact |
|---|-------|----------|--------|
| P1 | `while(true)` in progress tracking — no `isActive` | PlayerViewModel:888 | Battery drain on leak |
| P2 | `updateTask` read-copy-write race | FileDownloader:297 | Lost state updates |
| P3 | `onTracksChanged` ignores parameter, reads player | PlayerViewModel:292 | Redundant track query |
| P4 | Unbounded `CoroutineScope` in DownloadService | DownloadService:33 | Scope leak on restart |
| P5 | `collect` on preference Flow with no error handling | PlayerViewModel:241 | Silent crash on data store error |

## Security Issues Summary

| # | Issue | Location | Impact |
|---|-------|----------|--------|
| S1 | Token in URL query params | PlayerViewModel:568,642,670 | Token logged/leaked |
| S2 | `!!` operator on response bodies in 9 locations | Various repositories | NPE on null body |

## Correctness Issues Summary

| # | Issue | Location | Impact |
|---|-------|----------|--------|
| C1 | `RandomAccessFile` not closed on exception | FileDownloader:224 | FD leak |
| C2 | Search/List API inconsistency | TelePlayApi / FilesRepository | Broken pagination |
| C3 | Jump dialog allows invalid time values | PlayerScreen:1137 | Bad UX |
| C4 | Auth code consumed detection missing | AuthRepository:147 | User stuck at "not yet confirmed" |
| C5 | Missing `@OptIn` on PlayerScreen | PlayerScreen:195 | Future breakage risk |
