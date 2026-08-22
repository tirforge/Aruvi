"""
Custom streaming utilities for Telegram media files.
Multi-client parallel streaming for maximum download speed.
"""
import asyncio
import ctypes
import gc
import os
import re
import sys
import time
import traceback
import logging
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from typing import AsyncGenerator
from contextlib import asynccontextmanager

_libc = ctypes.CDLL("libc.so.6")


class CappedSemaphore(asyncio.Semaphore):
    """asyncio.Semaphore whose value never exceeds its initial cap.

    The in-flight backpressure semaphore guards "resolved-but-unyielded" chunk
    data. Chunks served purely from RAM/disk never acquire a permit, but the
    yield loop releases one token per yielded chunk. A plain Semaphore would
    therefore inflate past STREAM_INFLIGHT_MB on cache-heavy streams, weakening
    the OOM bound forever (release() can grow the value arbitrarily). This
    subclass no-ops a release once the value is back at the cap, preserving the
    cold-stream pipeline exactly while bounding cache-served streams too.
    """
    def release(self):
        if self._value < self._initial_cap:
            super().release()

    def __init__(self, value: int = 1):
        self._initial_cap = value
        super().__init__(value)

BATCH_SIZE = int(os.environ.get("STREAM_BATCH_SIZE", "10"))  # chunks per stream_media call
CHUNK_SIZE = 1024 * 1024  # 1 MB per chunk

# Cache profile: RAM is a SMALL hot layer, the disk tier (disk_cache.py) is the
# authoritative big cache. These env knobs retune the RAM/disk balance without
# code edits — defaults are tuned for a ~3 GB / 2-core box where the old 350 MB
# per-video RAM cache + 300 MB prefetch could OOM with 5 concurrent streams.
STREAM_RAM_PER_VIDEO_MB = int(os.environ.get("STREAM_RAM_PER_VIDEO_MB", "300"))
STREAM_INFLIGHT_MB = int(os.environ.get("STREAM_INFLIGHT_MB", "200"))
STREAM_MAX_CONCURRENT = int(os.environ.get("STREAM_MAX_CONCURRENT", "4"))
STREAM_PREFETCH_AHEAD_MB = int(os.environ.get("STREAM_PREFETCH_AHEAD_MB", "192"))
STREAM_PREFETCH_CONCURRENCY = int(os.environ.get("STREAM_PREFETCH_CONCURRENCY", "3"))
# Prefetch load gate: above this many concurrent live streams the ahead-prefetcher
# stops pre-filling entirely. Below it (but >= 2) it paces gentler instead of
# stopping, so the 2nd+ concurrent stream still gets some buffer headroom.
STREAM_PREFETCH_MAX_STREAMS = int(os.environ.get("STREAM_PREFETCH_MAX_STREAMS", "6"))
# Batch fetch budget (s): wall-clock cap for a batch's stream_media, and the
# no-progress stall threshold inside a batch. A slow-but-steady batch is now
# given STREAM_BATCH_TIMEOUT_S total instead of being killed mid-progress.
STREAM_BATCH_TIMEOUT_S = int(os.environ.get("STREAM_BATCH_TIMEOUT_S", "30"))
STREAM_BATCH_STALL_S = int(os.environ.get("STREAM_BATCH_STALL_S", "15"))
# Separate short cap for waiting on a busy bot's transmission slot, so queueing
# behind a slow fetch never eats into the actual fetch budget.
STREAM_SEM_WAIT_TIMEOUT_S = int(os.environ.get("STREAM_SEM_WAIT_TIMEOUT_S", "10"))
# Single-chunk emergency fetch budget (s).
STREAM_CHUNK_TIMEOUT_S = int(os.environ.get("STREAM_CHUNK_TIMEOUT_S", "15"))


def _get_media(message):
    """Get the media object from a message, trying video, document, audio."""
    return message.video or message.document or message.audio


class ChunkCache:
    """Per-video FIFO cache for already-yielded chunks (backward seek support).
    Key: chunk_idx -> bytes
    Max size: 2GB per video, evicts oldest entries when full.
    """
    def __init__(self, max_bytes: int = 2 * 1024 * 1024 * 1024):
        self._data: dict[int, bytes] = {}
        self._order: deque[int] = deque()
        self._size = 0
        self._max = max_bytes
        self._hits = 0
        self._misses = 0
        self._evictions = 0

    def get(self, key: int) -> bytes | None:
        data = self._data.get(key)
        if data is not None:
            self._hits += 1
            return data
        self._misses += 1
        return None

    def put(self, key: int, data: bytes):
        if key in self._data or not data:
            return
        self._data[key] = data
        self._order.append(key)
        self._size += len(data)
        while self._size > self._max and self._order:
            old_key = self._order.popleft()
            old_data = self._data.pop(old_key, None)
            if old_data:
                self._size -= len(old_data)
                self._evictions += 1
                if self._evictions == 1 or self._evictions % 10 == 0:
                    logger.info("Evicted %d chunks (%.1f MB)", self._evictions, self._size / 1024 / 1024)

    def clear(self) -> int:
        freed = self._size
        self._data.clear()
        self._order.clear()
        self._size = 0
        self._hits = 0
        self._misses = 0
        self._evictions = 0
        return freed

    @property
    def info(self) -> dict:
        return {
            "chunks": len(self._data),
            "size_mb": round(self._size / 1024 / 1024, 1),
            "max_mb": round(self._max / 1024 / 1024, 1),
            "hits": self._hits,
            "misses": self._misses,
            "evictions": self._evictions,
        }



class CacheManager:
    """Manages per-video ChunkCache instances.
    Each (chat_id, message_id) pair gets its own 2GB FIFO cache,
    so concurrent streams don't evict each other's backward seek data.
    """
    def __init__(self, per_video_max: int = 2 * 1024 * 1024 * 1024):
        self._caches: dict[tuple[int, int], ChunkCache] = {}
        self._per_video_max = per_video_max

    def get_cache(self, chat_id: int, message_id: int) -> ChunkCache:
        key = (chat_id, message_id)
        if key not in self._caches:
            self._caches[key] = ChunkCache(max_bytes=self._per_video_max)
        return self._caches[key]

    def remove(self, chat_id: int, message_id: int):
        key = (chat_id, message_id)
        if key in self._caches:
            self._caches.pop(key).clear()

    def clear_all(self, exclude_keys: set[tuple[int, int]] | None = None) -> int:
        total = 0
        keys_to_clear = [k for k in self._caches if exclude_keys is None or k not in exclude_keys]
        for key in keys_to_clear:
            total += self._caches.pop(key).clear()
        return total

    @property
    def per_video(self) -> list[dict]:
        result = []
        for (chat_id, message_id), cache in self._caches.items():
            info = cache.info
            result.append({
                "chat_id": chat_id,
                "message_id": message_id,
                "chunks": info["chunks"],
                "size_mb": info["size_mb"],
                "max_mb": info["max_mb"],
                "hits": info["hits"],
                "misses": info["misses"],
                "evictions": info["evictions"],
            })
        return sorted(result, key=lambda x: x["size_mb"], reverse=True)

    @property
    def info(self) -> dict:
        total_chunks = 0
        total_size = 0
        total_max = 0
        total_hits = 0
        total_misses = 0
        total_evictions = 0
        for cache in self._caches.values():
            i = cache.info
            total_chunks += i["chunks"]
            total_size += i["size_mb"]
            total_max += i["max_mb"]
            total_hits += i["hits"]
            total_misses += i["misses"]
            total_evictions += i["evictions"]
        return {
            "chunks": total_chunks,
            "size_mb": round(total_size, 1),
            "max_mb": round(total_max, 1),
            "hits": total_hits,
            "misses": total_misses,
            "evictions": total_evictions,
        }


_cache_manager = CacheManager(per_video_max=STREAM_RAM_PER_VIDEO_MB * 1024 * 1024)  # RAM backward cache per video
_forward_streams: dict[tuple[int, int], dict] = {}  # (chat_id, message_id) → live forward stream
_cache_finished_at: dict[tuple[int, int], float] = {}  # (chat_id, msg_id) → monotonic when stream ended
CACHE_TTL = 1800  # 30 min cache retention after stream ends

# Disk cache total usage (bytes), cached internally by DiskChunkCache.used_bytes
# so status/diag polls don't stat every chunk on each request.
def _dc_disk_size() -> int:
    return _disk_cache.used_bytes()


# ── Auto-restart when all streams finish ─────────────────────────────
_pending_restart: asyncio.TimerHandle | None = None

def _cancel_restart():
    global _pending_restart
    if _pending_restart is not None:
        _pending_restart.cancel()
        _pending_restart = None

def _do_restart():
    global _pending_restart
    _pending_restart = None
    _forward_streams.clear()
    _cache_finished_at.clear()
    _prefetch_size.clear()
    _prefetch_hwm.clear()
    _prefetch_cursor.clear()
    freed = _cache_manager.clear_all()
    logger.warning("No active streams — cleared %.1f MB from cache", freed / 1024 / 1024)

def _schedule_restart(delay: float = 900.0):
    global _pending_restart
    _cancel_restart()
    loop = asyncio.get_running_loop()
    _pending_restart = loop.call_later(delay, _do_restart)


def _evict_idle_ram_caches():
    """Enforce the CACHE_TTL retention policy: drop a movie's RAM cache once it
    has been idle for 30 min after its last stream ended.

    Previously nothing consumed _cache_finished_at, so under continuous traffic
    (no 15-min all-idle gap for _do_restart, no 65%+ memory for the OOM guard)
    every distinct movie streamed this boot kept up to STREAM_RAM_PER_VIDEO_MB
    of RAM for the whole session. Called from the periodic disk sweep."""
    now = time.monotonic()
    for key, finished_at in list(_cache_finished_at.items()):
        if now - finished_at <= CACHE_TTL:
            continue
        # The timestamp may be stale from a PRIOR stream of the same movie: if a
        # new stream is active right now (seek / resume), keep its hot cache.
        # Composite key: the same message id in a different chat (diag route
        # with ?chat=) must not keep/evict the wrong movie's cache.
        if key in _forward_streams:
            continue
        _cache_finished_at.pop(key, None)
        freed = _cache_manager.remove(*key)
        if freed:
            logger.info("RAM cache TTL evict: %s freed %.1f MB", key, freed / 1024 / 1024)


def get_forward_snapshot() -> list[dict]:
    # Prune stale entries (>8h since last update — a stream that ended without
    # its finally ever running, e.g. a hard server abort, would linger forever)
    now = time.monotonic()
    for key in list(_forward_streams.keys()):
        if now - _forward_streams[key].get("updated_at", 0) > 8 * 3600:
            _forward_streams.pop(key, None)
    result = []
    for key, info in list(_forward_streams.items()):
        futures = info.get("results", {})
        done = sum(1 for f in futures.values() if f.done())
        result.append({
            "message_id": key[1],
            "chat_id": info["chat_id"],
            "prebuffer_mb": done,
            "max_mb": info.get("total_chunks", 2000),
        })
    return result


from pyrogram import Client
from pyrogram.file_id import FileId, FileType
from pyrogram.errors import FileReferenceExpired, FileReferenceInvalid, AuthKeyUnregistered, AuthBytesInvalid

from .telegram import clients, reconnect_client
from .config import get_settings
from .disk_cache import _disk_cache


# ── Bounded disk write-through ───────────────────────────────────────────────
# Disk is the authoritative cold tier; RAM is only a small hot layer. Writes are
# fire-and-forget but bounded: if more than _DISK_WRITE_MAX_PENDING writes are
# queued (e.g. disk stalled), further chunks are skipped rather than accumulating
# unbounded tasks that hold the chunk bytes in memory (would defeat the RAM
# bound). A dedicated small thread pool does the writes so the default asyncio
# executor (also used for latency-sensitive disk reads) is never saturated by a
# backlog of fire-and-forget chunk writes.
_disk_write_pending = 0
_DISK_WRITE_MAX_PENDING = 96
_disk_write_executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="diskw")


def _schedule_disk_write(chat_id: int, message_id: int, chunk_idx: int, data: bytes):
    global _disk_write_pending
    if _disk_write_pending >= _DISK_WRITE_MAX_PENDING:
        return

    async def _do():
        global _disk_write_pending
        try:
            await asyncio.get_running_loop().run_in_executor(
                _disk_write_executor, _disk_cache.put, chat_id, message_id, chunk_idx, data
            )
        finally:
            _disk_write_pending -= 1

    _disk_write_pending += 1
    asyncio.get_running_loop().create_task(_do())

# ── Ahead-prefetcher (fills L1 RAM + L2 disk ahead of the playhead) ────────────
# Follows the highest chunk the player has served ("hwm") and keeps pulling the
# next PREFETCH_MAX_AHEAD_CHUNKS (192 MB) into RAM + disk in the background so
# the player's *next* request is already cached. Throttled so concurrent live
# streams are never starved:
#   1. global Semaphore(2) across ALL users/movies,
#   2. per-client courtesy acquire (0.5s timeout) — busy bots are skipped,
#   3. load gate: pause only past STREAM_PREFETCH_MAX_STREAMS active streams
#      (gentler pacing below that), so concurrent streams still get headroom,
#   4. short fetch timeout per mini-batch (2 chunks) so a slow bot is released.
PREFETCH_MAX_AHEAD_CHUNKS = STREAM_PREFETCH_AHEAD_MB  # ~N MB ahead (1 MB chunks)
PREFETCH_BATCH_LIMIT = 2                 # chunks per client hold (short)
PREFETCH_ACQUIRE_TIMEOUT = 0.5           # courtesy acquire on a client (s)
PREFETCH_FETCH_TIMEOUT = 5               # max seconds holding a client
PREFETCH_IDLE_TIMEOUT = 30               # stop prefetch 30s after playback stops
_YIELD_CHUNK_TIMEOUT = 30                # safety net: try a fresh single-chunk fetch
                                         # if a chunk can't be resolved this long
_STALL_REFETCH_LIMIT = 3                 # emergency refetches before aborting a
                                         # stalled stream (each ~15s) — a transient
                                         # Telegram slowdown must not truncate the
                                         # response, but a dead DC can't hold the
                                         # HTTP connection open forever.
_prefetch_semaphore = asyncio.Semaphore(STREAM_PREFETCH_CONCURRENCY)
_prefetch_ro = 0
_prefetch_tasks: dict[tuple[int, int], asyncio.Task] = {}
_prefetch_hwm: dict[tuple[int, int], int] = {}
_prefetch_cursor: dict[tuple[int, int], int] = {}
_prefetch_last_activity: dict[tuple[int, int], float] = {}
_prefetch_size: dict[tuple[int, int], int] = {}


_MEM_PRESSURE_RATIO = float(os.environ.get("STREAM_MEM_PRESSURE_RATIO", "0.6"))


def _process_rss_bytes() -> int:
    """Current RSS of THIS process (bytes) from /proc/self/statm."""
    try:
        with open("/proc/self/statm") as f:
            parts = f.read().split()
            pages = int(parts[1])
        return pages * os.sysconf("SC_PAGE_SIZE")
    except (OSError, ValueError):
        return 0


def _memory_pressure() -> bool:
    """True when this backend's own RSS exceeds _MEM_PRESSURE_RATIO of the cgroup
    limit. Measures ONLY the process the RAM caches live in: the container-wide
    cgroup is shared with unrelated processes (browsers, editors, CI), and using
    it used to stall the prefetcher whenever anything else used memory."""
    cur = _process_rss_bytes()
    if cur <= 0:
        # Fallback: container-wide cgroup current usage.
        for p in ("/sys/fs/cgroup/memory.current", "/sys/fs/cgroup/memory/memory.usage_in_bytes"):
            try:
                with open(p) as f:
                    cur = int(f.read().strip())
                    break
            except OSError:
                continue
    if cur <= 0:
        return False
    mx = None
    for p in ("/sys/fs/cgroup/memory.max", "/sys/fs/cgroup/memory/memory.limit_in_bytes"):
        try:
            with open(p) as f:
                v = int(f.read().strip())
                if 0 < v < 10**18:
                    mx = v
                    break
        except OSError:
            continue
    if mx is None:
        return False
    return cur > _MEM_PRESSURE_RATIO * mx


def _report_playhead(chat_id: int, message_id: int, chunk_idx: int):
    """Update the prefetch playhead (highest chunk served). Called by the yield
    loop on every yielded chunk. Restarts the prefetch task if it was cancelled
    by the idle timeout (e.g. the player paused and resumed)."""
    key = (chat_id, message_id)
    _prefetch_last_activity[key] = time.monotonic()
    prev = _prefetch_hwm.get(key, -1)
    if chunk_idx > prev:
        _prefetch_hwm[key] = chunk_idx
    cur = _prefetch_cursor.get(key, chunk_idx + 1)
    if chunk_idx >= cur:  # playhead passed the cursor — advance it
        _prefetch_cursor[key] = chunk_idx + 1
    task = _prefetch_tasks.get(key)
    if task is None or task.done():
        size = _prefetch_size.get(key, 0)
        if size > 0:
            _prefetch_last_activity[key] = time.monotonic()
            _prefetch_tasks[key] = asyncio.create_task(_ahead_prefetch_loop(key, size))


async def _collect_ahead_batch(cl, msg, start_chunk: int, count: int) -> bytes:
    """Fetch up to ``count`` 1MB chunks starting at start_chunk (whole chunks)."""
    d = bytearray()
    async for part in cl.stream_media(msg, limit=count, offset=start_chunk):
        d.extend(part)
        if len(d) >= count * CHUNK_SIZE:
            break
    return bytes(d)


async def _prefetch_fetch_batch(chat_id: int, message_id: int, start_chunk: int, batch_end: int, cache) -> int | None:
    """Fetch chunks [start_chunk..batch_end] from one free bot into RAM + disk.
    Returns the last chunk index written, or None if no bot was available."""
    global _prefetch_ro
    n = len(clients)
    if n == 0:
        return None
    start_idx = _prefetch_ro % n
    _prefetch_ro += 1
    for k in range(n):
        cl = clients[(start_idx + k) % n]
        if not getattr(cl, "is_connected", False):
            continue
        c_idx = getattr(cl, "pool_index", 0)
        sem = get_client_semaphore(c_idx)
        # get_messages is a lightweight RPC on the main session — do it OUTSIDE
        # the media-session semaphore so we never block a live stream's worker
        # while round-tripping to Telegram (workers follow the same pattern).
        try:
            msg = await asyncio.wait_for(
                _fetch_message(cl, chat_id, message_id), timeout=PREFETCH_FETCH_TIMEOUT
            )
        except asyncio.TimeoutError:
            continue
        except Exception as e:
            logger.warning("prefetch: get_messages failed on bot %d: %s", c_idx, e)
            continue
        if not msg:
            continue
        count = min(batch_end - start_chunk + 1, PREFETCH_BATCH_LIMIT)
        try:
            await asyncio.wait_for(sem.acquire(), timeout=PREFETCH_ACQUIRE_TIMEOUT)
        except asyncio.TimeoutError:
            continue  # bot busy serving a live stream — skip it
        try:
            data = await asyncio.wait_for(
                _collect_ahead_batch(cl, msg, start_chunk, count),
                timeout=PREFETCH_FETCH_TIMEOUT,
            )
            if not data:
                return None
            wrote = start_chunk
            for i in range(count):
                offset = i * CHUNK_SIZE
                if offset >= len(data):
                    break
                chunk = data[offset:offset + CHUNK_SIZE]
                cache.put(start_chunk + i, chunk)
                _schedule_disk_write(chat_id, message_id, start_chunk + i, chunk)
                wrote = start_chunk + i
            return wrote
        except asyncio.TimeoutError:
            return None
        except Exception as e:
            logger.warning("prefetch: bot %d fetch failed: %s", c_idx, e)
            return None
        finally:
            try:
                sem.release()
            except Exception:
                pass
    return None


async def _ahead_prefetch_loop(key: tuple[int, int], file_size: int):
    chat_id, message_id = key
    total_chunks = (file_size + CHUNK_SIZE - 1) // CHUNK_SIZE
    this_task = asyncio.current_task()
    try:
        while True:
            try:
                # Load gate: past STREAM_PREFETCH_MAX_STREAMS concurrent streams,
                # stop pre-filling entirely (live fetches win the bots). Below
                # that, just pace gentler so live fetches usually win, but the
                # 2nd+ stream still gets buffer headroom from prefetch.
                active = len(_forward_streams)
                if active >= STREAM_PREFETCH_MAX_STREAMS:
                    await asyncio.sleep(0.5)
                    continue
                if active >= 2:
                    await asyncio.sleep(0.2)
                # RAM gate: stop pulling ahead (RAM+disk) when the box is
                # under pressure — the stream's own workers still serve chunks
                # on demand, so playback continues, we just stop pre-filling.
                if _memory_pressure():
                    await asyncio.sleep(1.0)
                    continue
                hwm = _prefetch_hwm.get(key, -1)
                if hwm < 0:
                    await asyncio.sleep(0.5)
                    continue
                if time.monotonic() - _prefetch_last_activity.get(key, 0) > PREFETCH_IDLE_TIMEOUT:
                    break
                cur = _prefetch_cursor.get(key, hwm + 1)
                if cur > total_chunks - 1:
                    break
                if cur - hwm > PREFETCH_MAX_AHEAD_CHUNKS:
                    await asyncio.sleep(0.5)
                    continue
                cache = _cache_manager.get_cache(chat_id, message_id)
                try:
                    on_disk = await asyncio.to_thread(_disk_cache.contains, chat_id, message_id, cur)
                except Exception:
                    on_disk = False
                if cache.get(cur) is not None or on_disk:
                    _prefetch_cursor[key] = cur + 1
                    continue
                batch_end = min(cur + PREFETCH_BATCH_LIMIT - 1, total_chunks - 1)
                try:
                    await asyncio.wait_for(_prefetch_semaphore.acquire(), timeout=2.0)
                except asyncio.TimeoutError:
                    await asyncio.sleep(0.5)
                    continue
                try:
                    wrote = await _prefetch_fetch_batch(chat_id, message_id, cur, batch_end, cache)
                finally:
                    try:
                        _prefetch_semaphore.release()
                    except Exception:
                        pass
                if wrote is None:
                    await asyncio.sleep(0.5)  # no bot/capacity — back off
                else:
                    _prefetch_cursor[key] = wrote + 1
                await asyncio.sleep(0.2)  # brief pause so live fetches win the bots
            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.warning("prefetch: loop error: %s", e)
                await asyncio.sleep(0.5)
    except asyncio.CancelledError:
        raise
    finally:
        # Only clear this task's own state. A restart from _report_playhead /
        # start_ahead_prefetch may have installed a NEW task for the same key
        # while this one was winding down; a blind pop would orphan that task
        # and trigger duplicate prefetch loops on the next playhead tick.
        if _prefetch_tasks.get(key) is this_task:
            _prefetch_tasks.pop(key, None)
        _prefetch_hwm.pop(key, None)
        _prefetch_cursor.pop(key, None)
        _prefetch_last_activity.pop(key, None)


def start_ahead_prefetch(chat_id: int, message_id: int, file_size: int):
    """Start (or keep) the ahead-prefetch task for a movie. Idempotent."""
    key = (chat_id, message_id)
    task = _prefetch_tasks.get(key)
    if task is not None and not task.done():
        return
    if file_size <= 0:
        return
    _prefetch_size[key] = file_size
    _prefetch_last_activity[key] = time.monotonic()
    _prefetch_tasks[key] = asyncio.create_task(_ahead_prefetch_loop(key, file_size))

settings = get_settings()

logger = logging.getLogger("streamer")
logger.setLevel(logging.INFO)
if not logger.handlers:
    _h = logging.StreamHandler()
    _h.setLevel(logging.DEBUG)
    _h.setFormatter(logging.Formatter("streamer %(levelname)s: %(message)s"))
    logger.addHandler(_h)
    logger.propagate = False


# Global semaphores to limit concurrency per client across all streams
_client_semaphores = {}

# Serialize Telegram media-session establishment process-wide. When N concurrent
# streams ALL cold-start at once, each would otherwise perform its own
# auth.ImportAuthorization on its assigned bot simultaneously, flooding Telegram
# and stalling every stream at ~0 progress. By holding this lock across the first
# fetch that establishes a (client, dc) media session, only ONE auth import runs
# at a time; the rest wait, then reuse the established session (Pyrogram caches
# it in client.media_sessions[dc_id]).
_media_session_lock = asyncio.Lock()

# Set by telegram._warm_media_sessions() once the serial boot warm-up has
# finished (or been abandoned). A cold fetch waits (bounded) for this before
# establishing its own media session, so a stream that starts while the boot
# warm-up is still serializing auth does not race it and stall. Disk-resident
# chunks never wait: they don't touch a media session at all.
_media_sessions_warmed = asyncio.Event()
_WARMUP_WAIT = 60  # max seconds a cold fetch waits for the boot warm-up

# Circuit breaker: after a (client, dc) media session dies with
# AUTH_BYTES_INVALID / AUTH_KEY_UNREGISTERED, Telegram rate-limits fresh
# auth.ExportAuthorization/ImportAuthorization for that DC. Mark the DC degraded
# so every cold stream backs off (bounded) instead of stampeding a fresh auth
# attempt per batch. Re-establishment is still serialized by _media_session_lock.
_DC_AUTH_COOLDOWN = 30.0
_dc_auth_failure_until: dict[int, float] = {}


def _mark_dc_degraded(dc_id):
    if not dc_id:
        return
    deadline = time.monotonic() + _DC_AUTH_COOLDOWN
    if _dc_auth_failure_until.get(dc_id, 0) < deadline:
        _dc_auth_failure_until[dc_id] = deadline
        logger.warning("DC %d media auth degraded, cooldown %.0fs", dc_id, _DC_AUTH_COOLDOWN)


async def _wait_dc_cooldown(dc_id):
    if not dc_id:
        return
    remaining = _dc_auth_failure_until.get(dc_id, 0) - time.monotonic()
    if remaining > 0:
        logger.warning("DC %d on media-auth cooldown, waiting %.0fs", dc_id, remaining)
        await asyncio.sleep(remaining)


def _msg_dc_id(msg):
    try:
        return FileId.decode(_get_media(msg).file_id).dc_id
    except Exception:
        return None


@asynccontextmanager
async def _media_session_scope(cl, msg):
    """Context that serializes the creation of a (client, dc) media session.

    If the client already has a live media session for the message's DC, this is
    a no-op. Otherwise the caller enters a process-wide lock so that the cold
    auth.ImportAuthorization (which Telegram rate-limits) runs alone. During the
    boot window, wait (bounded) for the serial warm-up to finish first, so we
    never race it. If the DC is on the auth-failure cooldown, wait it out first
    so concurrent streams resume together instead of tripping the breaker again.
    """
    dc_id = _msg_dc_id(msg)
    if dc_id is not None and cl.media_sessions.get(dc_id) is None:
        await _wait_dc_cooldown(dc_id)
        if not _media_sessions_warmed.is_set():
            try:
                await asyncio.wait_for(_media_sessions_warmed.wait(), timeout=_WARMUP_WAIT)
            except asyncio.TimeoutError:
                pass  # warm-up stuck on a bad DC — proceed anyway, lock still serializes
        async with _media_session_lock:
            yield
    else:
        yield

# Limit total concurrent streams. Each stream holds up to STREAM_INFLIGHT_MB of
# resolved 1 MB chunks awaiting yield plus a small RAM backward cache; the bulk
# of data lives on the disk tier. With STREAM_MAX_CONCURRENT=4 and the default
# RAM profile (~24 MB cache + ~96 MB in-flight + shared prefetch), worst case is
# ~1 GB of hot RAM — safe on the ~3 GB production box.
_stream_semaphore = asyncio.Semaphore(STREAM_MAX_CONCURRENT)
class ClientPoolEmpty(Exception):
    """No connected client available in the pool."""
    pass


class SourceMessageGone(Exception):
    """Set on chunk futures when the source Telegram message is unretrievable.
    Aborts the stream loudly instead of yielding empty chunks — the client
    would otherwise receive a short body against the advertised length with
    no error anywhere."""


class ClientPool:
    """Weighted-least-loaded client assignment pool.

    Tracks active workers, success rate (EMA), and flood-wait cooldown
    per client. Assigns by highest score: connected(+100) - active(x10)
    - remaining_cooldown(x100) - (1-success_rate)(x50).
    """

    def __init__(self, clients: list):
        self._clients = clients
        self._active: dict[int, int] = {}
        self._cooldown: dict[int, float] = {}  # monotonic deadline
        self._success: dict[int, float] = {}  # EMA success rate
        self._lock = asyncio.Lock()

    def _get_active(self, idx: int) -> int:
        return self._active.get(idx, 0)

    def _score(self, idx: int) -> float:
        client = self._clients[idx]
        if not client.is_connected:
            return 0.0
        score = 100.0  # base for being connected
        score -= self._get_active(idx) * 10.0
        remaining = max(0, self._cooldown.get(idx, 0) - time.monotonic())
        score -= remaining * 100.0  # heavy penalty while in cooldown
        score -= (1 - self._success.get(idx, 0.5)) * 50.0
        return max(score, 1.0)  # keep barely-positive so it's available

    async def acquire(self, timeout: float = 30.0):
        """Acquire the best available client. Raises ClientPoolEmpty if none."""
        deadline = time.monotonic() + timeout
        while True:
            async with self._lock:
                best_idx = -1
                best_score = -1.0
                for i in range(len(self._clients)):
                    s = self._score(i)
                    if s > best_score:
                        best_score = s
                        best_idx = i
                if best_idx >= 0 and best_score > 0:
                    self._active[best_idx] = self._get_active(best_idx) + 1
                    return self._clients[best_idx], best_idx
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise ClientPoolEmpty("No connected client available")
            await asyncio.sleep(min(0.5, remaining))

    async def release(self, idx: int):
        async with self._lock:
            current = self._get_active(idx)
            if current > 0:
                self._active[idx] = current - 1

    def report_success(self, idx: int):
        rate = self._success.get(idx, 0.5)
        # EMA: alpha=0.3
        self._success[idx] = 0.3 * 1.0 + 0.7 * rate

    def report_failure(self, idx: int, flood_wait: int = 0):
        rate = self._success.get(idx, 0.5)
        self._success[idx] = 0.3 * 0.0 + 0.7 * rate
        if flood_wait > 0:
            deadline = time.monotonic() + min(max(flood_wait * 2, 30), 300)
            existing = self._cooldown.get(idx, 0)
            # Don't shorten existing cooldown
            if existing < deadline:
                self._cooldown[idx] = deadline

    @asynccontextmanager
    async def use_client(self, timeout: float = 30.0):
        client, idx = await self.acquire(timeout)
        try:
            yield client, idx
        finally:
            await self.release(idx)


# Lazy module-level pool instance
_client_pool: ClientPool | None = None

def get_client_pool() -> ClientPool:
    global _client_pool
    if _client_pool is None:
        _client_pool = ClientPool(clients)
    return _client_pool

def get_client_semaphore(client_index: int) -> asyncio.Semaphore:
    if client_index not in _client_semaphores:
        # Use the configured concurrency limit
        _client_semaphores[client_index] = asyncio.Semaphore(settings.telegram_client_concurrency)
    return _client_semaphores[client_index]

# Per-client reconnection lock: prevents concurrent reconnect racing with in-flight RPCs
_client_reconnect_locks: dict[int, asyncio.Lock] = {}

def get_client_reconnect_lock(client_index: int) -> asyncio.Lock:
    if client_index not in _client_reconnect_locks:
        _client_reconnect_locks[client_index] = asyncio.Lock()
    return _client_reconnect_locks[client_index]


def _is_auth_bytes_invalid(e) -> bool:
    """True for Pyrogram AuthBytesInvalid (400 AUTH_BYTES_INVALID)."""
    return isinstance(e, AuthBytesInvalid) or "AUTH_BYTES_INVALID" in str(e)


async def _invalidate_media_sessions(client, dc_id=None):
    """Drop Pyrogram's cached media sessions for a client.

    Pyrogram caches the media session in ``client.media_sessions[dc_id]``
    BEFORE the cross-DC auth export succeeds; if the export fails with
    AUTH_BYTES_INVALID it stops the session but leaves the poisoned entry
    cached, so every later stream_media on that DC reuses dead auth bytes.
    Clearing the cache forces a fresh ExportAuthorization on the next call.

    Also trips the per-DC auth cooldown so concurrent cold streams back off
    instead of immediately hammering auth again.
    """
    try:
        sessions = getattr(client, "media_sessions", {})
        for dc, sess in list(sessions.items()):
            _mark_dc_degraded(dc_id or dc)
            try:
                await sess.stop()
            except Exception:
                pass
        sessions.clear()
    except Exception:
        pass


# ── Chunk fetch helpers ────────────────────────────────────────────────────────

# ── Byte-accurate stream (GDrive) ───────────────────────────────────────────────

async def _byte_accurate_file_stream(client, message, file_size: int, offset_start: int, offset_end: int):
    """Download a byte range via Kurigram's native get_file.

    Kurigram handles the media session (cached per DC, warm at boot), CDN
    redirects (FileCdnRedirect → temporary CDN session → decrypt → hash verify),
    and the per-client concurrency semaphore internally — so GDrive downloads
    get the same CDN + session-reuse performance as streaming. Only this
    wrapper adds byte-exact trimming of the 1MB chunks to the requested range.
    Yields (byte_offset, chunk_data) tuples.
    """
    media = _get_media(message)
    if not media:
        raise ValueError("Message has no streamable media")
    file_id_obj = FileId.decode(media.file_id)
    dc_id = file_id_obj.dc_id

    CHUNK = 1024 * 1024
    start_chunk = offset_start // CHUNK
    total_chunks = (offset_end - offset_start + CHUNK - 1) // CHUNK

    def _trim(part: bytes, byte_offset: int):
        if byte_offset < offset_start:
            part = part[offset_start - byte_offset:]
            byte_offset = offset_start
        if byte_offset + len(part) > offset_end:
            part = part[:offset_end - byte_offset]
        return byte_offset, part

    async def _pump(fid, limit_chunks):
        nonlocal start_chunk
        async for part in client.get_file(fid, file_size=file_size, limit=limit_chunks, offset=start_chunk):
            byte_offset, part = _trim(part, start_chunk * CHUNK)
            if part:
                yield byte_offset, bytes(part)
            start_chunk += 1

    try:
        async for item in _pump(file_id_obj, total_chunks):
            yield item
    except (FileReferenceExpired, FileReferenceInvalid):
        refreshed = await _fetch_message(client, message.chat.id, message.id, force=True)
        refreshed_media = _get_media(refreshed) if refreshed else None
        if not refreshed_media:
            return
        remaining = total_chunks - (start_chunk - offset_start // CHUNK)
        if remaining <= 0:
            return
        refreshed_fid = FileId.decode(refreshed_media.file_id)
        async for item in _pump(refreshed_fid, remaining):
            yield item
    except Exception as _e:
        if "AUTH_KEY_UNREGISTERED" in str(_e) or "LIMIT_INVALID" in str(_e):
            client.media_sessions.pop(dc_id, None)
            logger.warning("Evicted stale session for DC %d (%s)", dc_id, str(_e)[:50])
        raise


# ── Prefetch ───────────────────────────────────────────────────────────────────

# Message cache: fetching the same (chat, message) via RPC repeatedly — once in
# the route, once per worker, once per prefetch batch — triggers Telegram
# FLOOD_WAIT on getMessages under load (e.g. concurrent seeks). File references
# are per-client and valid for ~1h, so a short per-client TTL cache is safe.
_msg_cache: dict[tuple[int, int, int], tuple[float, object]] = {}
_MSG_CACHE_TTL = 60.0

# Force-refresh guards. FILE_REFERENCE_EXPIRED can hit several batches of the
# same stream at once; without serialization each would issue its own
# get_messages RPC and re-fetch the batch — a flood-wait / refresh storm.
# A per-key lock coalesces concurrent force refetches, and the min-interval
# throttle stops repeat force refetches of the same (bot, chat, message) from
# hammering Telegram (a fresh reference is valid ~1h, so one per window is enough).
_msg_refresh_locks: dict[tuple[int, int, int], asyncio.Lock] = {}
_msg_last_force: dict[tuple[int, int, int], float] = {}
_msg_poisoned: set[tuple[int, int, int]] = set()
_MSG_REFRESH_MIN_INTERVAL = 15.0

# The four containers below grow one key per (bot, chat, message) ever streamed;
# without a cap they leak (telegram.py evicts its own _msg_cache; this one did
# not). Bound them by count, evicting the oldest entries and dropping the
# matching lock/last-force keys so all three stay in sync. Worst case ~4k
# Message objects (tens of MB) — far better than unbounded growth.
_MSG_CACHE_MAX = 4096


def _prune_msg_state():
    if len(_msg_cache) <= _MSG_CACHE_MAX:
        return
    by_age = sorted(_msg_cache.items(), key=lambda x: x[1][0])
    to_remove = len(_msg_cache) - int(_MSG_CACHE_MAX * 0.8)
    for key, _ in by_age[:to_remove]:
        _msg_cache.pop(key, None)
        _msg_refresh_locks.pop(key, None)
        _msg_last_force.pop(key, None)
        _msg_poisoned.discard(key)


def _get_msg_refresh_lock(key: tuple[int, int, int]) -> asyncio.Lock:
    lock = _msg_refresh_locks.get(key)
    if lock is None:
        lock = _msg_refresh_locks[key] = asyncio.Lock()
    return lock


def _mark_msg_poisoned(client, chat_id: int, message_id: int) -> None:
    """Record that a file-reference error invalidated this (bot, chat, message).
    A subsequent throttled force-refetch will then actually hit Telegram for a
    fresh reference instead of returning the dead cached Message."""
    key = (getattr(client, "pool_index", 0), chat_id, message_id)
    _msg_poisoned.add(key)


async def _fetch_message(client, chat_id: int, message_id: int, force: bool = False):
    """get_messages with a short per-client TTL cache. Pass ``force`` to bypass
    the cache (e.g. after FILE_REFERENCE_INVALID / auth errors need a fresh ref).
    Concurrent force refetches of the same (bot, chat, message) are coalesced
    behind a per-key lock and throttled to one per _MSG_REFRESH_MIN_INTERVAL."""
    key = (getattr(client, "pool_index", 0), chat_id, message_id)
    now = time.monotonic()
    if force:
        async with _get_msg_refresh_lock(key):
            if now - _msg_last_force.get(key, 0) < _MSG_REFRESH_MIN_INTERVAL:
                entry = _msg_cache.get(key)
                # If the cached Message is the dead one that produced the
                # FILE_REFERENCE error, a throttled return would hand workers
                # the same broken reference forever. Refresh for real instead.
                if entry and key not in _msg_poisoned:
                    return entry[1]
            _msg_last_force[key] = now
            _msg_poisoned.discard(key)
            msg = await client.get_messages(chat_id, message_id)
            _msg_cache[key] = (time.monotonic(), msg)
            _prune_msg_state()
            return msg
    entry = _msg_cache.get(key)
    if entry and now - entry[0] < _MSG_CACHE_TTL:
        return entry[1]
    msg = await client.get_messages(chat_id, message_id)
    _msg_cache[key] = (time.monotonic(), msg)
    _prune_msg_state()
    return msg


async def prefetch_first_batch(client, message, from_bytes: int = 0):
    """Fire-and-forget: start caching the first batch before the generator runs."""
    media = _get_media(message) if message else None
    if not media:
        return
    file_size = media.file_size
    if from_bytes >= file_size:
        return
    chat_id = message.chat.id
    message_id = message.id
    CHUNK_SIZE = 1024 * 1024
    start_chunk = from_bytes // CHUNK_SIZE
    cache = _cache_manager.get_cache(chat_id, message_id)
    if cache.get(start_chunk) is not None:
        return
    # Cold tier: already on disk? Then the stream's own workers will serve it
    # lazily — do NOT hit Telegram and hold a bot for a redundant fetch. This
    # also stops N concurrent requests from each warming the same 10MB.
    try:
        if await asyncio.to_thread(_disk_cache.contains, chat_id, message_id, start_chunk):
            return
    except Exception:
        pass
    # Bound concurrent first-batch warmers across ALL users (they share the same
    # Telegram bots). If the bots are busy serving live streams or other warmers,
    # skip — the stream's workers fetch on demand anyway.
    try:
        await asyncio.wait_for(_prefetch_semaphore.acquire(), timeout=2.0)
    except asyncio.TimeoutError:
        return
    try:
        # Prefer the client the caller picked (prefetch_by_ids chooses a helper
        # to keep bot 0 free for forward/storage ops); fall back to the first
        # connected client if the passed one is unavailable.
        prefetch_client = client if (client is not None and client.is_connected) else next(
            (c for c in clients if c.is_connected), None
        )
        if not prefetch_client:
            return
        c_idx = getattr(prefetch_client, "pool_index", 0)
        sem = get_client_semaphore(c_idx)
        msg = await _fetch_message(prefetch_client, chat_id, message_id)
        if not msg:
            return
        async with sem:
            # Per-batch time cap so a slow bot is released rather than held.
            t0 = time.monotonic()
            async for part in prefetch_client.stream_media(msg, limit=BATCH_SIZE, offset=start_chunk):
                data = bytes(part)
                cache.put(start_chunk, data)
                _schedule_disk_write(chat_id, message_id, start_chunk, data)
                start_chunk += 1
                if time.monotonic() - t0 > 8:
                    break
    except Exception as e:
        if _is_auth_bytes_invalid(e):
            raise  # let prefetch_by_ids retry on a different client
        pass  # best-effort: swallow everything else
    finally:
        try:
            _prefetch_semaphore.release()
        except Exception:
            pass


async def prefetch_first_batch_safe(client, message, from_bytes: int = 0):
    """Best-effort wrapper for fire-and-forget prefetch tasks: swallows all
    errors (incl. AuthBytesInvalid) so they never surface as unhandled
    task exceptions."""
    try:
        await prefetch_first_batch(client, message, from_bytes)
    except asyncio.CancelledError:
        raise
    except Exception:
        pass


async def prefetch_by_ids(chat_id: int, message_id: int, from_bytes: int = 0):
    """Fire-and-forget: warm the chunk cache for a file by chat/message id.

    Used before the player issues its first GET (e.g. right after a grab, or on
    the HEAD request the player sends to resolve the file size), so the first
    batch is already cached and playback starts from cache instead of waiting
    on the first Telegram fetch.

    Prefers a helper bot over the main bot (bot 0 is busy with forward/storage
    ops) and retries on another connected client if the first one fails with
    AUTH_BYTES_INVALID or a stale media session.
    """
    connected = [c for c in clients if c.is_connected]
    if not connected:
        return
    ordered = sorted(connected, key=lambda c: getattr(c, "pool_index", 0) == 0)
    for prefetch_client in ordered:
        try:
            c_idx = getattr(prefetch_client, "pool_index", 0)
            sem = get_client_semaphore(c_idx)
            # get_messages is an RPC on the main session — no need to hold the
            # media-session semaphore for it (and the cache avoids flood-waits).
            msg = await _fetch_message(prefetch_client, chat_id, message_id)
            if not msg:
                return
            await prefetch_first_batch(prefetch_client, msg, from_bytes)
            return
        except asyncio.CancelledError:
            raise
        except Exception as e:
            if _is_auth_bytes_invalid(e):
                await _invalidate_media_sessions(prefetch_client)
                logger.warning("prefetch: bot %d AUTH_BYTES_INVALID, trying next client", c_idx)
                continue
            logger.warning("prefetch: bot %d failed: %s", c_idx, e)
            break  # non-auth errors are not client-specific; stop


# ── Main streaming generator ───────────────────────────────────────────────────

async def parallel_stream_generator(
    initial_message,
    offset: int,
    length: int,
    chunk_size: int = 1024 * 1024,
    concurrency: int = None,
    request=None,
):
    """
    Fetch file chunks in parallel using the client pool.
    Each worker uses its own client and fetches its own Message object
    to avoid cross-bot FILE_REFERENCE_INVALID errors.
    """
    pool_size = len(clients)
    if concurrency is None:
        concurrency = max(1, sum(1 for c in clients if c.is_connected))

    start_chunk = offset // chunk_size
    end_chunk = (offset + length - 1) // chunk_size
    total_chunks = end_chunk - start_chunk + 1

    chat_id = initial_message.chat.id
    message_id = initial_message.id

    # Pre-create Futures for ordered yielding
    loop = asyncio.get_running_loop()
    results = {
        (start_chunk + i): loop.create_future()
        for i in range(total_chunks)
    }

    # Cancel any pending auto-restart — a new stream just started
    _cancel_restart()

    # Register forward stream for monitor (done futures = prebuffer depth).
    # Keep a reference so the finally-block only removes THIS registration —
    # a seek can start a second generator on the same message_id (overwriting
    # this entry); a blind pop would unregister the newer stream and make the
    # monitor + restart-scheduler think no stream is active.
    _backpressure = CappedSemaphore(STREAM_INFLIGHT_MB)  # ~200 MB in-flight per stream
    _forward_stream = {"chat_id": chat_id, "results": results, "total_chunks": total_chunks, "updated_at": time.monotonic()}
    _forward_streams[(chat_id, message_id)] = _forward_stream

    async def _resolve_chunk_now(chunk_idx: int, data: bytes) -> bool:
        """Resolve a chunk future, acquiring a backpressure permit ONLY when we
        actually transition it not-done → done. Re-fetched chunks that another
        attempt already resolved (batch retries after FileReferenceExpired etc.)
        skip the acquire so every permit stays paired with a yield-loop release;
        otherwise refetch storms silently drain the in-flight budget."""
        if chunk_idx not in results:
            return False
        future = results[chunk_idx]
        if future.done():
            return False
        await _backpressure.acquire()
        try:
            future.set_result(data)
            return True
        except asyncio.InvalidStateError:
            _backpressure.release()
            return False

    # Keep this movie alive on disk while it is streaming (TTL counts from the
    # last touch, i.e. "30 min after the active stream ends"), and start the
    # ahead-prefetcher that fills RAM + disk before the player asks.
    try:
        _disk_cache.touch(chat_id, message_id)
    except Exception:
        pass
    _media = _get_media(initial_message)
    start_ahead_prefetch(chat_id, message_id, _media.file_size if _media else 0)

    # Check backward cache — pre-set futures for already-cached chunks
    video_cache = _cache_manager.get_cache(chat_id, message_id)
    cache_hits = 0
    for chunk_idx in range(start_chunk, end_chunk + 1):
        cached = video_cache.get(chunk_idx)
        if cached is not None:
            results[chunk_idx].set_result(cached)
            cache_hits += 1

    # Disk cold tier: serve chunks previously written to disk (survives restarts).
    # Disk-resident chunks are NOT pre-loaded into RAM (a full-movie range would
    # burst the whole file into memory); they are resolved lazily, one chunk at a
    # time, inside the yield loop. Only chunks missing from BOTH RAM and disk are
    # queued to the Telegram fetch workers.
    disk_resident: set[int] = set()

    def _scan_disk_resident() -> set[int]:
        # One directory scan builds the set of disk-resident chunk indices;
        # membership checks are then O(1) in memory. Offloaded to a thread
        # anyway so even this single scan never blocks the event loop.
        found: set[int] = set()
        present = _disk_cache.chunk_indices(chat_id, message_id)
        for chunk_idx in range(start_chunk, end_chunk + 1):
            if results[chunk_idx].done():
                continue
            if chunk_idx in present:
                found.add(chunk_idx)
        return found

    disk_resident = await asyncio.to_thread(_scan_disk_resident)
    cache_hits += len(disk_resident)

    # Rebuild uncached ranges now that RAM + disk-served chunks are covered.
    uncached_ranges = []
    range_start = None
    for chunk_idx in range(start_chunk, end_chunk + 1):
        if results[chunk_idx].done() or chunk_idx in disk_resident:
            if range_start is not None:
                uncached_ranges.append((range_start, chunk_idx - 1))
                range_start = None
        else:
            if range_start is None:
                range_start = chunk_idx
    if range_start is not None:
        uncached_ranges.append((range_start, end_chunk))

    if cache_hits:
        logger.info("%d/%d cached (%d ranges)", cache_hits, total_chunks, len(uncached_ranges))
    else:
        logger.debug("No cache: fetching %d", total_chunks)

    # Task queue with batch ranges — only uncached chunks
    task_queue = asyncio.Queue()
    for rstart, rend in uncached_ranges:
        for batch_start in range(rstart, rend + 1, BATCH_SIZE):
            batch_end = min(batch_start + BATCH_SIZE - 1, rend)
            task_queue.put_nowait((batch_start, batch_end))

    async def _fetch_batch(batch_start, batch_end, cl, msg, sem, timeout=None, stall=None):
        """Fetch a batch, assigning each chunk as it arrives.
        Forward-caches each chunk immediately so concurrent streams
        of the same file benefit before the yield loop.
        Acquires a backpressure permit per chunk to cap in-flight
        resolved-but-unyielded data — prevents OOM for huge files.

        Uses a stall-based timeout: aborts only when *no chunk* has arrived
        for ``stall`` seconds, so a batch that is making slow-but-steady
        progress (Telegram throttling) isn't aborted and re-fetched.
        """
        if timeout is None:
            timeout = STREAM_BATCH_TIMEOUT_S
        if stall is None:
            stall = STREAM_BATCH_STALL_S
        t0 = time.perf_counter()
        last_progress = t0
        current = batch_start
        # Order matters: DC-cooldown wait (unbounded-ish) → transmission slot
        # (bounded 10s) → global session lock. Waiting on the semaphore while
        # inside _media_session_scope held the process-wide lock for up to
        # STREAM_SEM_WAIT_TIMEOUT_S, stalling every OTHER bot's cold-session
        # establishment behind an unrelated, saturated bot.
        dc_id = _msg_dc_id(msg)
        if dc_id is not None and cl.media_sessions.get(dc_id) is None:
            await _wait_dc_cooldown(dc_id)
        # Acquire the transmission slot with a short, separate timeout so
        # queueing behind a busy bot never eats the fetch budget.
        try:
            await asyncio.wait_for(sem.acquire(), timeout=STREAM_SEM_WAIT_TIMEOUT_S)
        except asyncio.TimeoutError:
            logger.warning("Batch %d-%d waited %.0fs for bot %d — skipping",
                batch_start, batch_end, STREAM_SEM_WAIT_TIMEOUT_S,
                getattr(cl, 'pool_index', '?'))
            return False
        try:
            async with _media_session_scope(cl, msg):
                # The wall-clock budget covers the fetch only — a batch whose
                # media session is stuck (Telegram auth throttling under
                # concurrent cold starts) would otherwise retry upload.GetFile
                # forever and hold the stream open indefinitely.
                async with asyncio.timeout(timeout):
                    async for part in cl.stream_media(msg, limit=batch_end - batch_start + 1, offset=batch_start):
                        now = time.perf_counter()
                        if current > batch_start and now - last_progress > stall:
                            logger.warning("Batch %d-%d stalled %.0fs (bot %d, got %d/%d)",
                                batch_start, batch_end, now - last_progress,
                                getattr(cl, 'pool_index', '?'), current - batch_start,
                                batch_end - batch_start + 1)
                            break
                        data = bytes(part)
                        video_cache.put(current, data)
                        _schedule_disk_write(chat_id, message_id, current, data)
                        await _resolve_chunk_now(current, data)
                        current += 1
                        last_progress = time.perf_counter()
        except asyncio.TimeoutError:
            logger.warning("Batch %d-%d timed out after %.0fs (bot %d, got %d/%d)",
                batch_start, batch_end, timeout, getattr(cl, 'pool_index', '?'), current - batch_start,
                batch_end - batch_start + 1)
            return False
        finally:
            sem.release()
        elapsed = time.perf_counter() - t0
        if elapsed > 2.5:
            logger.warning("Slow batch %d-%d: %.1fs (bot %d)", batch_start, batch_end, elapsed, getattr(cl, 'pool_index', '?'))
        return current - 1 == batch_end

    async def _fetch_one(chunk_offset, cl, msg, sem, timeout=None):
        """Fetch a single chunk, forward-caching it on success. Stops after timeout."""
        if timeout is None:
            timeout = STREAM_CHUNK_TIMEOUT_S
        t0 = time.perf_counter()
        # Same ordering as _fetch_batch: cooldown → transmission slot → session
        # lock, so a busy bot's semaphore never stalls the global lock.
        dc_id = _msg_dc_id(msg)
        if dc_id is not None and cl.media_sessions.get(dc_id) is None:
            await _wait_dc_cooldown(dc_id)
        try:
            await asyncio.wait_for(sem.acquire(), timeout=STREAM_SEM_WAIT_TIMEOUT_S)
        except asyncio.TimeoutError:
            return None
        try:
            async with _media_session_scope(cl, msg):
                # Wall-clock cap covers the wait for the first part too, so a stuck
                # media session (auth throttling) can't hold this chunk forever.
                async with asyncio.timeout(timeout):
                    d = bytearray()
                    async for part in cl.stream_media(msg, limit=1, offset=chunk_offset):
                        d.extend(part)
                data = bytes(d)
                video_cache.put(chunk_offset, data)
                _schedule_disk_write(chat_id, message_id, chunk_offset, data)
                return data
        except asyncio.TimeoutError:
            logger.warning("Chunk %d timed out after %.0fs", chunk_offset, timeout)
            return None
        except (FileReferenceInvalid, FileReferenceExpired, AuthKeyUnregistered, AuthBytesInvalid):
            raise
        except Exception:
            return None
        finally:
            sem.release()

    async def worker(worker_id: int):
        pool = get_client_pool()
        try:
            async with pool.use_client() as (client, c_idx):
                # Fully-cached range? Nothing to fetch — don't even do a
                # get_messages RPC (they flood-wait under load).
                if task_queue.empty():
                    return
                # Each worker normally fetches its own fresh Message so file references
                # are per-client and valid. Bot 0 gets the already-fetched initial_message
                # to save ~1s round-trip on first chunk.
                if c_idx == 0:
                    local_msg = initial_message
                else:
                    try:
                        local_msg = await _fetch_message(client, chat_id, message_id)
                    except Exception as e:
                        logger.error("Bot %d: failed to fetch message %d: %s", c_idx, message_id, e)
                        return
                if not local_msg:
                    logger.error("Bot %d: message %d not found — failing chunks", c_idx, message_id)
                    while not task_queue.empty():
                        try:
                            batch_start, batch_end = task_queue.get_nowait()
                        except asyncio.QueueEmpty:
                            break
                        for chunk_offset in range(batch_start, batch_end + 1):
                            fut = results[chunk_offset]
                            if not fut.done():
                                fut.set_exception(
                                    SourceMessageGone(f"message {message_id} not found in chat {chat_id}")
                                )
                                # Mark retrieved so an early client disconnect
                                # (futures never awaited) doesn't warn at GC.
                                fut.exception()
                        task_queue.task_done()
                    return

                # Get semaphore for this client to ensure we don't exceed max_concurrent_transmissions
                # This prevents the "Request refused" or internal queue buildup in Pyrogram
                semaphore = get_client_semaphore(c_idx)
                worker_failed = False

                while not task_queue.empty():
                    try:
                        batch_start, batch_end = task_queue.get_nowait()
                    except asyncio.QueueEmpty:
                        break

                    batch_ok = False
                    try:
                        # Kurigram's stream_media handles CDN redirects internally
                        # (FileCdnRedirect → temp CDN session → decrypt → hash check),
                        # so a single native path covers both normal and CDN fetches.
                        batch_ok = await _fetch_batch(batch_start, batch_end, client, local_msg, semaphore)
                    except (FileReferenceInvalid, FileReferenceExpired):
                        logger.warning("Bot %d: batch file reference expired, re-fetching message", c_idx)
                        _mark_msg_poisoned(client, chat_id, message_id)
                        try:
                            local_msg = await _fetch_message(client, chat_id, message_id, force=True)
                            batch_ok = await _fetch_batch(batch_start, batch_end, client, local_msg, semaphore)
                        except Exception:
                            pass
                    except AuthKeyUnregistered:
                        logger.warning("Bot %d: auth key expired in batch, reconnecting...", c_idx)
                        async with get_client_reconnect_lock(c_idx):
                            if await reconnect_client(client):
                                try:
                                    local_msg = await _fetch_message(client, chat_id, message_id, force=True)
                                    batch_ok = await _fetch_batch(batch_start, batch_end, client, local_msg, semaphore)
                                except Exception:
                                    pass
                    except AuthBytesInvalid:
                        logger.warning("Bot %d: auth bytes invalid, refreshing media session...", c_idx)
                        async with get_client_reconnect_lock(c_idx):
                            await _invalidate_media_sessions(client, _msg_dc_id(local_msg))
                            if await reconnect_client(client):
                                try:
                                    local_msg = await _fetch_message(client, chat_id, message_id, force=True)
                                    batch_ok = await _fetch_batch(batch_start, batch_end, client, local_msg, semaphore)
                                except Exception:
                                    pass
                    except Exception as e:
                        logger.error("Bot %d failed batch %d-%d: %s", c_idx, batch_start, batch_end, e)
                        worker_failed = True

                    if batch_ok:
                        task_queue.task_done()
                        continue

                    # Fallback: fetch each chunk individually
                    for chunk_offset in range(batch_start, batch_end + 1):
                        if chunk_offset not in results or results[chunk_offset].done():
                            continue
                        try:
                            chunk_data = await _fetch_one(chunk_offset, client, local_msg, semaphore)
                            if chunk_data is not None:
                                await _resolve_chunk_now(chunk_offset, chunk_data)
                                continue
                        except (FileReferenceInvalid, FileReferenceExpired):
                            logger.warning("Bot %d: file reference expired for chunk %d", c_idx, chunk_offset)
                            _mark_msg_poisoned(client, chat_id, message_id)
                            try:
                                local_msg = await _fetch_message(client, chat_id, message_id, force=True)
                                async with semaphore:
                                    d = bytearray()
                                    async for part in client.stream_media(local_msg, limit=1, offset=chunk_offset):
                                        d.extend(part)
                                data = bytes(d)
                                video_cache.put(chunk_offset, data)
                                await _resolve_chunk_now(chunk_offset, data)
                                continue
                            except Exception as e2:
                                logger.error("Bot %d failed chunk %d after re-fetch: %s", c_idx, chunk_offset, e2)
                        except AuthKeyUnregistered:
                            logger.warning("Bot %d: auth key expired for chunk %d", c_idx, chunk_offset)
                            async with get_client_reconnect_lock(c_idx):
                                if await reconnect_client(client):
                                    try:
                                        local_msg = await _fetch_message(client, chat_id, message_id, force=True)
                                        async with semaphore:
                                            d = bytearray()
                                            async for part in client.stream_media(local_msg, limit=1, offset=chunk_offset):
                                                d.extend(part)
                                        data = bytes(d)
                                        video_cache.put(chunk_offset, data)
                                        await _resolve_chunk_now(chunk_offset, data)
                                        continue
                                    except Exception as e2:
                                        logger.error("Bot %d failed chunk %d after reconnect: %s", c_idx, chunk_offset, e2)
                                else:
                                    logger.error("Bot %d: reconnect failed for chunk %d", c_idx, chunk_offset)
                        except AuthBytesInvalid:
                            logger.warning("Bot %d: auth bytes invalid for chunk %d, refreshing media session...", c_idx, chunk_offset)
                            async with get_client_reconnect_lock(c_idx):
                                await _invalidate_media_sessions(client, _msg_dc_id(local_msg))
                                if await reconnect_client(client):
                                    try:
                                        local_msg = await _fetch_message(client, chat_id, message_id, force=True)
                                        async with semaphore:
                                            d = bytearray()
                                            async for part in client.stream_media(local_msg, limit=1, offset=chunk_offset):
                                                d.extend(part)
                                        data = bytes(d)
                                        video_cache.put(chunk_offset, data)
                                        await _resolve_chunk_now(chunk_offset, data)
                                        continue
                                    except Exception as e2:
                                        logger.error("Bot %d failed chunk %d after refresh: %s", c_idx, chunk_offset, e2)
                                else:
                                    logger.error("Bot %d: reconnect failed for chunk %d", c_idx, chunk_offset)
                        except Exception as e:
                            logger.error("Bot %d failed chunk %d: %s", c_idx, chunk_offset, e)
                            worker_failed = True
                    task_queue.task_done()
                if worker_failed:
                    pool.report_failure(c_idx)
                else:
                    pool.report_success(c_idx)
        except ClientPoolEmpty:
            logger.error("Worker %d: no connected client available", worker_id)
        except asyncio.TimeoutError:
            logger.error("Worker %d: timed out waiting for client", worker_id)


    # Launch workers — but only when there are uncached chunks to fetch. A
    # fully RAM/disk-cached range has an empty queue; spawning workers would
    # just have each grab a client slot to find nothing (needless lock churn
    # on cached seeks). Disk-resident chunks are resolved lazily by
    # _resolve_chunk / _fetch_chunk_now, which take clients on demand.
    worker_tasks = []
    if not task_queue.empty():
        worker_tasks = [
            asyncio.create_task(worker(i)) for i in range(concurrency)
        ]

    async def _fetch_chunk_now(chunk_idx: int):
        """Emergency single-chunk fetch used when a chunk that was disk-resident
        at snapshot time is gone by the time the yield loop reaches it (TTL
        sweep / LRU eviction). No worker was assigned to it, so without this
        fallback `await results[chunk_idx]` would hang forever."""
        try:
            async with get_client_pool().use_client() as (fclient, fc_idx):
                fsem = get_client_semaphore(fc_idx)
                fmsg = await _fetch_message(fclient, chat_id, message_id)
                if not fmsg:
                    return None
                return await _fetch_one(chunk_idx, fclient, fmsg, fsem)
        except ClientPoolEmpty:
            return None
        except Exception as e:
            logger.warning("fetch_now chunk %d failed: %s", chunk_idx, e)
            return None

    # ── Yield smoothing: prebuffer before yielding ─────────────────────
    # Wait for MIN_PREBUFFER chunks before the first yield so workers
    # build a pipeline ahead of the HTTP response stream. This absorbs
    # batch-to-batch jitter (flood waits, slow DC) without client-side
    # rebuffering. Raised from 2 → 10 so the player starts with ~10s of
    # video instead of ~2s; media sessions are pre-warmed at boot so the
    # first-batch TTFB stays low (~1-3s healthy, ~5-7s on a slow DC).
    MIN_PREBUFFER = 10
    prebuffer_n = min(MIN_PREBUFFER, total_chunks)
    # Resolve disk-resident prebuffer chunks directly (lazy, no RAM burst).
    # This must cover BOTH branches below: with an empty RAM cache a
    # single-chunk range that is disk-resident has NO worker assigned to it
    # (uncached_ranges is empty), so `await results[start_chunk]` would never
    # resolve and the stream would hang forever.
    #
    # Each chunk is waited on with a BOUNDED timeout: a worker that dies
    # without resolving its future (e.g. ClientPoolEmpty) must not leave the
    # stream hanging before its first byte — the emergency single-chunk fetch
    # recovers it, otherwise the stream aborts loudly instead of stalling.
    async def _prebuffer_chunk(cidx):
        if cidx in disk_resident and not results[cidx].done():
            ddata = await asyncio.to_thread(_disk_cache.get, chat_id, message_id, cidx)
            if ddata is not None:
                results[cidx].set_result(ddata)
                return
        try:
            async with asyncio.timeout(_YIELD_CHUNK_TIMEOUT):
                await results[cidx]
        except asyncio.TimeoutError:
            data = await _fetch_chunk_now(cidx)
            if data is not None:
                if not results[cidx].done():
                    results[cidx].set_result(data)
                return
            logger.error("Prebuffer chunk %d unrecoverable — aborting stream %d", cidx, message_id)
            raise asyncio.TimeoutError(f"Prebuffer chunk {cidx} unrecoverable")
    if prebuffer_n > 1:
        await asyncio.gather(*(_prebuffer_chunk(start_chunk + i) for i in range(prebuffer_n)))
        logger.info("Prebuffered %d / %d chunks (%.1f MB)",
                    prebuffer_n, total_chunks,
                    prebuffer_n * chunk_size / 1024 / 1024)
    elif prebuffer_n == 1:
        await _prebuffer_chunk(start_chunk)

    stream_start = time.perf_counter()
    first_chunk_logged = False
    cache_served = 0
    bytes_yielded = 0
    try:
        async def _resolve_chunk(chunk_idx: int) -> bytes:
            """Resolve a chunk for the yield loop. A transient Telegram
            slowdown (flood wait, slow DC) must not truncate the response, so
            a stalled worker result is retried via bounded emergency
            single-chunk fetches before giving up."""
            if chunk_idx in disk_resident:
                ddata = await asyncio.to_thread(_disk_cache.get, chat_id, message_id, chunk_idx)
                if ddata is not None:
                    return ddata
                data = await _fetch_chunk_now(chunk_idx)
                if data is not None:
                    return data
            refetches = 0
            while True:
                try:
                    async with asyncio.timeout(_YIELD_CHUNK_TIMEOUT):
                        return await results[chunk_idx]
                except asyncio.TimeoutError:
                    refetches += 1
                    logger.warning("Chunk %d stalled %.0fs — emergency refetch (%d/%d)",
                                   chunk_idx, _YIELD_CHUNK_TIMEOUT, refetches, _STALL_REFETCH_LIMIT)
                    data = await _fetch_chunk_now(chunk_idx)
                    if data is not None:
                        return data
                    if refetches >= _STALL_REFETCH_LIMIT:
                        logger.error("Chunk %d unrecoverable after %d refetches — aborting stream %d",
                                     chunk_idx, refetches, message_id)
                        raise asyncio.TimeoutError(
                            f"Chunk {chunk_idx} unrecoverable after {refetches} refetches"
                        )

        for offset in range(total_chunks):
            chunk_idx = start_chunk + offset

            # Try cache first (backward seek), fall back to fetch result
            # After prebuffer, the first MIN_PREBUFFER chunks are already resolved.
            cached_data = video_cache.get(chunk_idx)
            if cached_data is not None:
                chunk_data = cached_data
                cache_served += 1
            else:
                chunk_data = await _resolve_chunk(chunk_idx)
                video_cache.put(chunk_idx, chunk_data)

            # Report playhead so the ahead-prefetcher follows us.
            try:
                _report_playhead(chat_id, message_id, chunk_idx)
            except Exception:
                pass

            bytes_yielded += len(chunk_data)
            if not first_chunk_logged:
                elapsed = time.perf_counter() - stream_start
                logger.info("Chunk %d in %.1fs (cached=%s)", chunk_idx, elapsed, cached_data is not None)
                first_chunk_logged = True

            # Active client-liveness probe: uvicorn only pushes http.disconnect
            # when it notices the socket died, and half-closed TCP can go
            # unnoticed for a whole range. Poll between chunks so an abandoned
            # stream stops fetching instead of draining the pool to the end.
            if request is not None:
                try:
                    if await request.is_disconnected():
                        logger.info("Streamgen msg %d ended: client disconnected (polled)", message_id)
                        return
                except Exception:
                    pass  # never let a liveness check kill a healthy stream

            yield chunk_data
            # Release backpressure permit — next in-flight chunk may resolve
            _backpressure.release()
            del results[chunk_idx]
            # Refresh forward stream timestamp every 100 chunks
            if offset % 100 == 0:
                fwd_key = (chat_id, message_id)
                if fwd_key in _forward_streams:
                    _forward_streams[fwd_key]["updated_at"] = time.monotonic()
    finally:
        # Diagnose WHY a stream ended short: log the pending exception type so a
        # mid-stream abort is never silent (normally an asyncio.TimeoutError from
        # _resolve_chunk, or a CancelledError from the ASGI/response layer).
        ei = sys.exc_info()
        if ei[0] is not None:
            if ei[0] is GeneratorExit:
                # Client went away mid-stream (seek/stop/close) — routine,
                # not an error. Don't spam the log with tracebacks.
                logger.info("Streamgen msg %d ended: client disconnected", message_id)
            elif ei[0] is asyncio.CancelledError:
                # ASGI layer cancelled us — uvicorn tears down the response
                # task the moment the client socket dies (or on shutdown).
                logger.info("Streamgen msg %d ended: cancelled (client disconnect/shutdown)", message_id)
            else:
                import traceback as _tb
                logger.error("Streamgen msg %d aborted: %s: %s\n%s",
                             message_id, ei[0].__name__, ei[1],
                             "".join(_tb.format_tb(ei[2])))
        # Cancel workers, await drain, then clear results (avoids "Task destroyed but pending").
        # Bounded: a worker wedged in a Telegram RPC (flood wait, broken DC) must
        # never hold the HTTP response open for minutes — abandon it after 5s.
        for w in worker_tasks:
            w.cancel()
        try:
            await asyncio.wait_for(
                asyncio.gather(*worker_tasks, return_exceptions=True), timeout=5
            )
        except (asyncio.TimeoutError, asyncio.CancelledError):
            logger.warning("Worker drain timed out for msg %d (%d tasks)", message_id, len(worker_tasks))
        results.clear()
        if _forward_streams.get((chat_id, message_id)) is _forward_stream:
            _forward_streams.pop((chat_id, message_id), None)
            # Stream over — drop the prefetch size so the key can be re-seeded
            # by start_ahead_prefetch on the next stream. Prevents unbounded
            # growth of _prefetch_size across distinct movies streamed this boot.
            _prefetch_size.pop((chat_id, message_id), None)
        gced = gc.collect()
        _libc.malloc_trim(0)
        if gced > 10000:
            logger.info("Stream cleanup: gc %d objs, malloc_trim", gced)
        # Keep cache alive for CACHE_TTL (30min) — resume after network drop
        _cache_finished_at[(chat_id, message_id)] = time.monotonic()
        # Schedule restart when no streams remain — frees page cache
        if not _forward_streams:
            _schedule_restart()
        # Cache kept alive across seek requests — OOM guard in main.py handles eviction
        elapsed = time.perf_counter() - stream_start
        cinfo = video_cache.info
        logger.info("Done: %d ch, %.1f MB, %.1fs", total_chunks, bytes_yielded / 1024 / 1024, elapsed)
        logger.info("Cache hits/evicts: %d/%d", cinfo["hits"], cinfo["evictions"])


async def stream_file(
    client: Client,          # kept for API compat; pool is used instead
    message,
    from_bytes: int,
    until_bytes: int,
    request=None,
) -> AsyncGenerator[bytes, None]:
    """Stream a file range using the multi-client pool.
    Limits concurrent streams to prevent OOM from prebuffers stacking.
    """
    CHUNK_SIZE = 1024 * 1024

    total_bytes_needed = until_bytes - from_bytes + 1
    bytes_yielded = 0
    bytes_to_skip = from_bytes % CHUNK_SIZE

    t0 = time.perf_counter()
    logger.debug("Streaming %d-%d (%d bytes)", from_bytes, until_bytes, total_bytes_needed)

    await _stream_semaphore.acquire()
    try:
        async for chunk in parallel_stream_generator(
            message, from_bytes, total_bytes_needed, request=request
        ):
            if bytes_to_skip > 0:
                chunk = chunk[bytes_to_skip:]
                bytes_to_skip = 0

            remaining = total_bytes_needed - bytes_yielded
            if len(chunk) > remaining:
                chunk = chunk[:remaining]

            yield chunk
            bytes_yielded += len(chunk)
            if bytes_yielded >= total_bytes_needed:
                break
    finally:
        _stream_semaphore.release()

    elapsed = time.perf_counter() - t0
    logger.info("stream_file %d-%d done: %.1f MB in %.1fs (%.1f Mbps)",
                from_bytes, until_bytes, bytes_yielded / 1024 / 1024, elapsed,
                bytes_yielded * 8 / elapsed / 1024 / 1024 if elapsed > 0 else 0)
