# Streaming Engine — Simple Explanation

## The Problem

Streaming a 2 GB movie from Telegram is slow. We can't make the user wait 30 seconds for the first byte.

## The Solution: Two-Tier Cache

```
┌─────────────────────────────────────────────────────────────┐
│                    USER REQUESTS BYTE 0                     │
└─────────────────────────────────────────────────────────────┘
                              │
              ┌───────────────┴───────────────┐
              ▼                               ▼
       ┌─────────────┐                   ┌─────────────┐
       │  RAM Cache  │  (200 MB/video)   │  Disk Cache │  (8 GB total)
       │  (Instant)  │                   │  (Fast SSD) │
       └─────────────┘                   └─────────────┘
              │                               │
              │  MISS                         │  MISS
              ▼                               ▼
       ┌─────────────────────────────────────┐
       │     FETCH FROM TELEGRAM (slow)      │
       │  → Save to RAM + Disk               │
       │  → Stream to user                   │
       └─────────────────────────────────────┘
```

---

## Three Tiers of Speed

| Tier | When | Speed |
|------|------|-------|
| **RAM Hit** | Rewatching recent video | ~0 ms (memory copy) |
| **Disk Hit** | Watched yesterday | ~5-10 ms (local SSD) |
| **Telegram Fetch** | First time / cold | ~2-15 s (network) |

---

## The Prefetcher (Reads Your Mind)

While you watch byte 0-100 MB, we **quietly download bytes 100-228 MB** in the background.

- **Ahead:** 128 MB (`STREAM_PREFETCH_AHEAD_MB`)
- **Concurrency:** 1 bot at a time (`STREAM_PREFETCH_CONCURRENCY`)
- **Cap:** 200 MB in-flight (`STREAM_INFLIGHT_MB`)
- **Backs off if:** System memory > 60% (`_memory_pressure()`)

Result: User seeks forward → **instant** (already in RAM/disk).

---

## Worker Pool (For Cold Starts)

When neither RAM nor disk has the chunk:

```
1. Launch up to 3 workers (2 stream + 1 prefetch)
2. Each worker grabs 5 chunks/batch (STREAM_BATCH_SIZE)
3. Fetch via: client.stream_media(message, limit=1, offset=chunk)
4. On success: _resolve_chunk_now() → acquires backpressure permit
5. On failure: Release permit, retry with fresh message ref
```

**Backpressure:** We only "pay" a permit when a chunk **actually arrives**. Failed fetches don't consume permits.

---

## Message Cache (Don't Ask Telegram Twice)

- Key: `(bot_index, chat_id, message_id)`
- TTL: 15 seconds (`_MSG_REFRESH_MIN_INTERVAL`)
- **Poison tracking:** If a message ref dies (`FILE_REFERENCE`), mark it poisoned → next force-refresh hits Telegram for real

---

## Circuit Breakers (Don't Make Things Worse)

| Breaker | Trigger | Cooldown |
|---------|---------|----------|
| Per-DC media auth | `ImportBotAuthorization` fails | 30 s |
| Per-client reconnect | `AuthKeyUnregistered` / `AuthBytesInvalid` | 60 s |
| Force-refresh throttle | Too many refetches for same message | 15 s |

---

## Disk Write Pipeline (Never Block the Event Loop)

```
Worker thread (diskw-1..4)          Event Loop
     │                                  │
     ├── write chunk to temp file ─────▶│
     │                                  │
     ├── os.replace(tmp, final) ──────▶│ (atomic)
     │                                  │
     └── single fsync(fd) ────────────▶│ (on slot complete)
```

- 4 worker threads, max 96 pending writes
- Slow SATA never stalls streaming

---

## Failure Modes (What Happens When Things Break)

| Scenario | What Happens |
|----------|--------------|
| Chunk missing from disk mid-stream | Fallback: fetch single chunk from Telegram (`_fetch_chunk_now`) |
| Batch times out (30 s) | Cancel batch, worker exits, next worker retries |
| Telegram `FLOOD_WAIT` | Client `sleep_threshold=15` absorbs short waits |
| OOM (container > 90%) | `_memory_pressure()` → pause prefetch, aggressive LRU evict |