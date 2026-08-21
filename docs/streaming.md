# Streaming Engine Architecture

## Two-Tier Cache

### L1: RAM Hot Layer (`ChunkCache`)
- Per-video capacity: `STREAM_RAM_PER_VIDEO_MB` (default 200 MB)
- LRU eviction when video exceeds cap
- Hit = instant memory `yield chunk`
- Miss = spawn worker to fetch from L2 or Telegram

### L2: Disk Tier (`DiskChunkCache` at `/home/container/vcache/`)
- Global cap: `DISK_CACHE_MAX_BYTES` (8 GB)
- Per-video cap: `DISK_CACHE_PER_VIDEO_BYTES` (2 GB)
- TTL: `DISK_CACHE_TTL` (30 min) after **last activity** (stream start or write touch)
- Layout: `vcache/{chat_id}_{message_id}/{chunk_index}.bin`
- Atomic write: unique temp file → `os.replace(tmp, final)`
- Reads: `os.scandir()` once per movie to list resident chunks (fast range checks)

## Prefetcher (`AheadPrefetcher`)

Triggered on first byte request for a video:
1. Background task computes chunk indices ahead of playhead
2. Bounded by:
   - `STREAM_PREFETCH_CONCURRENCY` (1 bot at a time)
   - `STREAM_INFLIGHT_MB` (200 MB unbacklogged data)
   - `STREAM_PREFETCH_AHEAD_MB` (128 MB ahead of playhead)
   - `_memory_pressure()` gate (cgroup mem > 60% → back off)
3. Writes to **both** RAM (if space) and disk (thread pool)
4. Idle timeout: ~30 s of no reads → cancels itself

## Worker Pool (`parallel_stream_generator`)

For cold ranges not in RAM/disk:
- Launches `STREAM_MAX_CONCURRENT` workers (default 3: 2 users + 1 prefetch)
- Each worker processes a chunk range via `stream_file_chunks()`
- Chunk fetch: `client.stream_media(message, limit=1, offset=chunk)`
- Results gathered in `results: dict[chunk_idx, asyncio.Future]`
- **Backpressure**: `CappedSemaphore(STREAM_INFLIGHT_MB)` acquired **only on successful chunk delivery** via `_resolve_chunk_now()`
- Reconnect/refresh loops release permits on failure; only completed chunks consume permits

## Message Cache (`_msg_cache` in `streaming.py`)

- Key: `(bot_pool_index, chat_id, message_id)`
- TTL: 15 s throttle window (`_MSG_REFRESH_MIN_INTERVAL`)
- Poison tracking: `_msg_poisoned` set for dead `FILE_REFERENCE` errors
- Force refetch bypasses throttle when poisoned
- Count cap: 4096 keys, oldest-evict prune

## Media Session Serialization

- Process-wide lock: `_media_session_lock` (asyncio.Lock)
- Boot warmup: `_warm_media_sessions()` serially imports authorization on **all 11 bots**
- Prevents N concurrent cold streams from flooding Telegram with `ImportBotAuthorization`

## Circuit Breakers

| Breaker | Trigger | Action |
|---------|---------|--------|
| Per-DC auth cooldown (`_dc_auth_failure_until`) | `ImportBotAuthorization` fails | 30 s cooldown, skip DC |
| Per-client reconnect cooldown | `AuthKeyUnregistered` / `AuthBytesInvalid` | 60 s before reconnect |
| Force-refresh throttle (`_MSG_REFRESH_MIN_INTERVAL`) | `FILE_REFERENCE` errors | 15 s min interval per (bot, chat, msg) |

## Disk Write Pipeline

- 4-worker `ThreadPoolExecutor` (`diskw-*`)
- Max 96 pending writes (backpressure into prefetcher)
- Slow SATA never blocks event loop
- Single `fsync(fd)` per slot on completion

## Failure Modes & Recovery

| Scenario | Behavior |
|----------|----------|
| Chunk vanishes from disk mid-stream | `_fetch_chunk_now` fallback fetches single chunk from Telegram |
| Worker batch timeout (30 s) | Batch cancelled, worker exits, next worker retries |
| Telegram `FLOOD_WAIT` | `sleep_threshold=15` absorbs short waits; longer waits trigger reconnect |
| OOM (cgroup > 90%) | `_memory_pressure()` true → prefetcher pauses, LRU evicts aggressively |