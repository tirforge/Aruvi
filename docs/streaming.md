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
        │  RAM Cache  │  (300 MB/video)   │  Disk Cache │  (8 GB total)
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

While you watch byte 0-100 MB, we **quietly download bytes 100-292 MB** in the background.

- **Ahead:** 192 MB (`STREAM_PREFETCH_AHEAD_MB`, ~192 chunks of 1 MB)
- **Concurrency:** 1 bot at a time (`STREAM_PREFETCH_CONCURRENCY`)
- **Cap:** 200 MB in-flight (`STREAM_INFLIGHT_MB`)
- **Backs off if:** System memory > 60% (`_memory_pressure()`)

Result: User seeks forward → **instant** (already in RAM/disk).

---

## Chunk Math (Why 1 MB)

```
CHUNK_SIZE = 1 MB (fixed, matches Telegram's API granularity)

A 2 GB movie = 2048 chunks
RAM tier holds last ~300 chunks   (300 MB window behind playhead)
Disk tier holds up to 2048 chunks (whole movie, 2 GB cap)
Prefetch keeps ~192 chunks ahead of playhead
In-flight budget: 200 MB → at most 200 unbacklogged chunk requests
```

Player requests come in as HTTP Range headers, mapped to chunk indexes:
`chunk_index = range_start // CHUNK_SIZE`

---

## Worker Pool (For Cold Starts)

When neither RAM nor disk has the chunk:

```
1. Acquire _stream_semaphore (STREAM_MAX_CONCURRENT = 4)
2. Launch up to 4 workers (user chunks + prefetch share the pool)
3. Each worker grabs batches of 10 chunks (STREAM_BATCH_SIZE)
4. Fetch via: client.stream_media(message, limit=1, offset=chunk)
5. On success: _resolve_chunk_now() → acquires backpressure permit
6. On failure: Release permit, retry with fresh message ref
```

**Backpressure:** We only "pay" a permit when a chunk **actually arrives**. Failed fetches don't consume permits.

---

## Anatomy of One Range Request

```
GET /api/stream/42?token=...  Range: bytes=1048576-3145727
  │
  ├─ 1. Verify download token (sub, fid==42, ver)     [routers/streaming.py]
  ├─ 2. parse_range_header() → (start=1MB, end=3MB)   [206 semantics]
  ├─ 3. Map to chunk indexes 1..3
  ├─ 4. RAM hit?   → copy slices, done                [~0 ms]
  ├─ 5. Disk hit?  → read files, warm RAM, done       [~5 ms]
  └─ 6. Miss?      → spawn workers → Telegram fetch
                       → write disk (atomic tmp+rename)
                       → warm RAM
                       → stream bytes as they land
  Response: 206 Partial Content + Content-Range header
```

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