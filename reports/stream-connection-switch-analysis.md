# Stream Connection Lifecycle: User Switching Movies

## Summary

When a user stops watching one movie and starts another, the connection lifecycle is handled primarily by the **client (Android)**. The client properly calls `exoPlayer.stop()` which closes the HTTP connection before opening a new one via `loadAndPlay()`. However, the **backend (FastAPI)** has no per-user connection tracking — it relies entirely on FastAPI's automatic cancellation of `StreamingResponse` generators when the client disconnects. There's no mechanism to kill old streams when a new one starts for the same user, which could lead to resource leaks in edge cases.

---

## Client-Side Flow (Android — ExoPlayer)

### 🟢 Starting a Stream

```
PlayerViewModel.init()
  → loadAndPlay()
    → filesRepository.getFile(fileId)
    → Build stream URL: "$serverUrl/api/stream/$fileId?token=$token"
    → exoPlayer.setMediaSource(...)     // Replaces any previous source
    → exoPlayer.prepare()               // Opens new HTTP connection
    → exoPlayer.playWhenReady = true
```

### 🟡 Switching Movies (playNextFile)

```kotlin
fun playNextFile(newFileId: Int) {
    currentFileId = newFileId
    resumePosition = 0
    exoPlayer.stop()       // ← CLOSES old HTTP connection
    loadAndPlay()          // ← Opens new HTTP connection
}
```

**File:** `PlayerViewModel.kt:605-610`

### 🔴 Leaving the Player Screen

```kotlin
// DisposableEffect onDispose:
onDispose {
    viewModel.onLeavePlayer()
}

fun onLeavePlayer() {
    saveProgress()
    if (isAudioFile && exoPlayer.isPlaying) {
        startBackgroundAudio()   // Keeps connection alive for audio
    } else {
        exoPlayer.pause()        // Pauses, connection STAYS OPEN
    }
}

// ViewModel.onCleared:
override fun onCleared() {
    saveProgress()
    if (!isBackgroundAudioActive) {
        exoPlayer.stop()         // ← CLOSES connection
        exoPlayer.clearMediaItems()
    }
}
```

**Files:** `PlayerViewModel.kt:931-969`, `MobilePlayerScreen.kt:124-133`

### 🗺️ Navigation Flow (Switching Movies)

```
Player(A) → Back → Details Screen → Click Movie B → Player(B)
                ↓                            ↓
         popBackStack()              navigate(Screen.Player)

When Player(A) is popped:
  → DisposableEffect.onDispose
  → onLeavePlayer() → pause()
  → ViewModel.onCleared → stop() + clearMediaItems()

When Player(B) is created:
  → New PlayerViewModel (with fileId=B from SavedStateHandle)
  → loadAndPlay() → setMediaSource + prepare → NEW HTTP connection
```

**Key insight:** The `ExoPlayer` is a **Singleton** (via Hilt `@Singleton` in `PlayerModule.kt`), so there is only ever one player instance. This means:
- Only one HTTP connection to the backend at a time
- No risk of multiple simultaneous streams from the same device
- Clean transition: `stop()` → `setMediaSource()` → `prepare()`

---

## Backend-Side Flow (FastAPI/Python)

### 🟢 Stream Endpoint

```python
@router.get("/api/stream/{file_id}")
async def stream_file(file_id, request, db, current_user):
    # 1. Validate file belongs to user
    file = await db.execute(select(File).where(File.id == file_id, File.user_id == current_user.id))
    
    # 2. Parse HTTP Range header for seeking
    range_header = request.headers.get("range")
    from_bytes, until_bytes = parse_range_header(range_header, file_size)
    
    # 3. Fetch message from Telegram channel (MTProto)
    message = await get_message_from_channel(file.channel_message_id)
    
    # 4. Create async generator that streams chunks from Telegram
    async def file_streamer():
        async for chunk in stream_file_chunks(tg_client, message, from_bytes, until_bytes):
            yield chunk
    
    # 5. Return StreamingResponse
    return StreamingResponse(file_streamer(), status_code=206, ...)
```

**File:** `streaming.py` (backend repo)

### 📦 Chunk Streaming (Parallel Multi-Client)

```python
async def parallel_stream_generator(initial_message, offset, length, ...):
    # 1. Pre-fetch messages for ALL clients in parallel
    fetch_results = await asyncio.gather(*fetch_tasks)
    
    # 2. Create task queue of chunk indices
    task_queue = asyncio.Queue()
    for i in range(total_chunks):
        task_queue.put_nowait(start_chunk + i)
    
    # 3. Launch N worker tasks that fetch chunks in parallel
    worker_tasks = [asyncio.create_task(worker(i)) for i in range(concurrency)]
    
    # 4. Yield results in order
    for _ in range(total_chunks):
        chunk_data = await results[current_idx]
        yield chunk_data
    
    # 5. Cleanup: cancel workers on generator exit
    finally:
        for w in worker_tasks:
            w.cancel()
```

**File:** `streaming.py` (backend repo)

---

## Analysis: Connection Drop When Switching Movies

### ✅ What Works Correctly

| Step | Action | Result |
|------|--------|--------|
| 1. User presses Back | `PlayerA.onCleared()` → `exoPlayer.stop()` | HTTP connection to backend closed |
| 2. User clicks Movie B | New `PlayerViewModel(B)` created | Fresh state, new fileId |
| 3. `loadAndPlay()` runs | `exoPlayer.setMediaSource()` + `prepare()` | New HTTP connection to backend |
| 4. Backend gets request | FastAPI creates new `StreamingResponse` | New generator with fresh chunks |
| 5. Old connection cleanup | FastAPI detects disconnect → cancels old generator | Workers cancelled via `finally` block |

### ⚠️ Potential Issues Found

#### 1. Backend lacks per-user connection tracking

The backend has **no mechanism** to:
- Count active streams per user
- Kill old streams when a new one starts for the same user
- Enforce a maximum concurrent streams per user

**Risk:** If the client-side HTTP connection doesn't fully close (e.g., OS-level TCP keepalive, network issues, race condition where the new connection starts before the old one fully closes), both streams would be served simultaneously with no limit.

**File:** `streaming.py` (backend — no connection tracking code at all)

#### 2. `playNextFile()` doesn't call `clearMediaItems()`

```kotlin
fun playNextFile(newFileId: Int) {
    currentFileId = newFileId
    resumePosition = 0
    exoPlayer.stop()            // Stops playback
    // exoPlayer.clearMediaItems() is NOT called here
    loadAndPlay()               // setMediaSource + prepare
}
```

The `retry()` function **does** call `clearMediaItems()`, but `playNextFile()` does not. According to ExoPlayer docs, `setMediaSource()` when the player already has a source should replace it, so this might not be an issue. But for consistency and safety, it's worth noting.

#### 3. `onLeavePlayer()` only pauses, doesn't stop

When the user leaves the player (presses Back), `onLeavePlayer()` calls `exoPlayer.pause()` (for video) instead of `stop()`. The connection is only fully closed when the ViewModel is garbage collected and `onCleared()` fires.

**Potential race:** If navigation from Player(A) to Player(B) is fast enough that Player(A)'s ViewModel hasn't been cleared yet (ViewModel clearing is async), there's a brief window where both streams could be active.

However, since ExoPlayer is a **Singleton**, calling `setMediaSource()` + `prepare()` on the same ExoPlayer should properly replace the old source regardless of whether `stop()` was called.

#### 4. Backend generator cleanup relies on client disconnect detection

The backend's `parallel_stream_generator` has a `finally` block that cancels worker tasks:
```python
finally:
    for w in worker_tasks:
        w.cancel()
```

This only runs when the generator is closed, which happens when:
- FastAPI detects the HTTP client disconnected
- All chunks have been yielded (stream completed)

If the client disconnect is not detected promptly (e.g., TCP half-open connections), the generator could continue running unnecessarily.

---

## Recommendations

### 1. Add per-user stream tracking on the backend (LOW PRIORITY)

```python
# In streaming.py or a new connection_manager.py:
_active_streams: dict[int, list[asyncio.Task]] = {}  # user_id → tasks

def track_stream(user_id: int, generator_task: asyncio.Task):
    """Track active stream for a user. Cancel old ones."""
    if user_id in _active_streams:
        for old_task in _active_streams[user_id]:
            old_task.cancel()  # Kill old stream
    _active_streams[user_id] = [generator_task]
```

This would prevent the same user from having multiple active streams.

### 2. Add `clearMediaItems()` in `playNextFile()` (ZERO PRIORITY — optional)

```kotlin
fun playNextFile(newFileId: Int) {
    currentFileId = newFileId
    resumePosition = 0
    exoPlayer.stop()
    exoPlayer.clearMediaItems()  // Add for consistency
    loadAndPlay()
}
```

Not strictly needed since `setMediaSource()` replaces existing sources, but makes the contract explicit.

### 3. Ensure ExoPlayer's stop() properly releases connections (ALREADY WORKS)

ExoPlayer's implementation of `stop()` already releases the MediaSource, which triggers the underlying data source (OkHttp) to close the HTTP connection. Verified working.

---

## Source Files Examined

| File | Path | Purpose |
|------|------|---------|
| `PlayerViewModel.kt` | `app/src/main/java/.../ui/player/PlayerViewModel.kt` | Client-side player lifecycle, `playNextFile()`, `onCleared()` |
| `PlayerScreen.kt` | `app/src/main/java/.../ui/player/PlayerScreen.kt` | TV player screen with DisposableEffect cleanup |
| `MobilePlayerScreen.kt` | `app/src/main/java/.../ui/mobile/player/MobilePlayerScreen.kt` | Mobile player screen with BackHandler |
| `PlayerModule.kt` | `app/src/main/java/.../di/PlayerModule.kt` | Singleton ExoPlayer DI configuration |
| `NavGraph.kt` | `app/src/main/java/.../ui/navigation/NavGraph.kt` | Navigation flow between screens |
| `Screen.kt` | `app/src/main/java/.../ui/navigation/Screen.kt` | Route definitions |
| `TelePlayApi.kt` | `app/src/main/java/.../data/api/TelePlayApi.kt` | API interface (stream endpoint definition) |
| `streaming.py` | `teleplay-backend/app/routers/streaming.py` | Backend streaming endpoint with StreamingResponse |
| `streaming.py` | `teleplay-backend/app/streaming.py` | Parallel multi-client chunk streaming |
| `main.py` | `teleplay-backend/app/main.py` | FastAPI app with CORS and middleware |
| `telegram.py` | `teleplay-backend/app/telegram.py` | Telegram client pool management |
| `config.py` | `teleplay-backend/app/config.py` | Backend configuration |
| `patch.py` | `teleplay-backend/app/patch.py` | Custom Pyrogram client patches |
| `rate_limit.py` | `teleplay-backend/app/rate_limit.py` | Rate limiter (only on public streams) |

---

## Conclusion

**The code works correctly for the described scenario.** When a user stops watching a movie and starts a new one:

1. **Client side:** `exoPlayer.stop()` is called, which properly closes the HTTP connection
2. **Singleton ExoPlayer** ensures only one connection exists at a time
3. **Backend:** FastAPI detects the disconnect and cancels the stream generator
4. **New connection:** `loadAndPlay()` opens a fresh HTTP connection via `setMediaSource()` + `prepare()`

The main gap is the **lack of backend-side per-user connection tracking**, which means there's no protection against duplicate streams if the client disconnect isn't properly detected. This is a low-risk issue for normal operation but could matter in edge cases (network flakiness, rapid switching, etc.).
