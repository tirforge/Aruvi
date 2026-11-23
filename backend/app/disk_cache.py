"""Disk-backed cold tier for streamed chunks.

Storage is delegated to `diskcache` (https://github.com/grantjenks/python-diskcache),
a battle-tested SQLite-indexed on-disk cache. It gives us, without any
hand-rolled bookkeeping:

* atomic writes — a reader never sees a half-written chunk,
* a size-capped LRU that evicts by itself as new chunks are written,
* TTL expiry per entry,
* a thread/process-safe metadata store (SQLite WAL), so the cache stays
  consistent if the backend is ever run with more than one worker,
* O(1) size/volume reporting instead of walking the whole cache tree.

This module is only an adapter: it maps Aruvi's ``(chat_id, message_id,
chunk_idx)`` keys onto the cache, keeps a per-video activity map so a video
expires DISK_CACHE_TTL seconds after its last *use* (not since-write), and
purges the legacy ``{chat_id}_{message_id}/{idx}.bin`` directories written by
the previous implementation so an upgraded deployment does not leak them.

Key layout
----------
``chunk:{chat_id}:{message_id}:{chunk_idx}``  → the 1 MB chunk payload
``@act:{chat_id}:{message_id}``              → last-activity timestamp

Every chunk is tagged ``video:{chat_id}:{message_id}`` so a whole video can be
evicted in one SQL statement (``Cache.evict(tag=...)``).

Set ``DISK_CACHE_ENABLED=0`` to make every method a no-op.
"""

import logging
import os
import threading
import time
from pathlib import Path

try:
    import diskcache
except ImportError:  # pragma: no cover - dependency is in requirements.txt
    diskcache = None

logger = logging.getLogger("disk_cache")

CACHE_DIR = Path(os.environ.get("DISK_CACHE_DIR", "./data/vcache"))
DISK_CACHE_TTL = int(os.environ.get("DISK_CACHE_TTL", "1800"))  # 30 minutes
DISK_CACHE_MAX_BYTES = int(
    os.environ.get("DISK_CACHE_MAX_BYTES", str(8 * 1024**3))
)  # 8 GB total
DISK_CACHE_PER_VIDEO_BYTES = int(
    os.environ.get("DISK_CACHE_PER_VIDEO_BYTES", str(2 * 1024**3))
)  # 2 GB per video
ENABLED = os.environ.get("DISK_CACHE_ENABLED", "1") == "1"

# How often a video's activity marker is rewritten. Without this every 1 MB
# chunk write would add an extra SQLite transaction just to bump the TTL clock.
_ACTIVITY_FLUSH_S = 5.0


def _parse_key(dir_name: str) -> tuple[int, int] | None:
    """Parse '{chat_id}_{message_id}' from a legacy movie dir name. chat_id may
    be negative, so split on the LAST underscore."""
    try:
        mid, cid = dir_name.rsplit("_", 1)
        return int(mid), int(cid)
    except (ValueError, AttributeError):
        return None


def _chunk_key(chat_id: int, message_id: int, chunk_idx: int) -> str:
    return f"chunk:{chat_id}:{message_id}:{chunk_idx}"


def _video_key(chat_id: int, message_id: int) -> str:
    return f"{chat_id}:{message_id}"


def _video_tag(chat_id: int, message_id: int) -> str:
    return f"video:{chat_id}:{message_id}"


def _activity_key(chat_id: int, message_id: int) -> str:
    return f"@act:{chat_id}:{message_id}"


class DiskChunkCache:
    """Adapter over ``diskcache.Cache`` with a per-video TTL/LRU policy."""

    def __init__(self, cache_dir: Path | None = None):
        self.cache_dir = cache_dir or CACHE_DIR
        self._lock = threading.RLock()
        self._last_active: dict[tuple[int, int], float] = {}
        self._last_flush: dict[tuple[int, int], float] = {}
        self._video_bytes: dict[tuple[int, int], int] = {}
        self._chunk_sizes: dict[str, int] = {}
        self._cache = None

        if not ENABLED or diskcache is None:
            if diskcache is None:
                logger.warning(
                    "diskcache is not installed - the disk cache tier is DISABLED. "
                    "Install it with: pip install 'diskcache>=5.6.3'"
                )
            return

        # A path that exists but is not a directory (a file was created at the
        # cache location) means there is nowhere to cache: stay a no-op rather
        # than crashing the streaming backend at import time.
        try:
            if self.cache_dir.exists() and not self.cache_dir.is_dir():
                logger.warning(
                    "Disk cache path %s is not a directory - disk cache disabled",
                    self.cache_dir,
                )
                return
            self.cache_dir.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            logger.warning("Cannot create disk cache dir %s: %s", self.cache_dir, e)
            return

        try:
            self._cache = diskcache.Cache(
                str(self.cache_dir),
                size_limit=DISK_CACHE_MAX_BYTES,
                cull_limit=16,
                eviction_policy="least-recently-used",
                tag_index=True,
            )
        except Exception as e:  # diskcache/sqlite can fail on a broken FS
            logger.warning("Cannot open disk cache at %s: %s", self.cache_dir, e)
            self._cache = None
            return

        # One-time upgrade step: the old implementation stored one directory
        # per video ({chat}_{msg}/*.bin) which the library knows nothing about.
        # Purge it now so an upgraded box reclaims that disk immediately.
        try:
            freed = self._purge_legacy_dirs()
            if freed:
                logger.info(
                    "Disk cache: purged %.1f MB of legacy chunk files",
                    freed / 1024 / 1024,
                )
        except OSError:
            pass

    # ── helpers ─────────────────────────────────────────────────────────────
    @property
    def enabled(self) -> bool:
        return self._cache is not None

    @staticmethod
    def _chunk_key(chat_id: int, message_id: int, chunk_idx: int) -> str:
        return _chunk_key(chat_id, message_id, chunk_idx)

    def _note_activity(self, chat_id: int, message_id: int) -> None:
        now = time.time()
        key = (chat_id, message_id)
        with self._lock:
            self._last_active[key] = now
            flush = now - self._last_flush.get(key, 0.0) >= _ACTIVITY_FLUSH_S
            if flush:
                self._last_flush[key] = now
        # Persist the marker at most every _ACTIVITY_FLUSH_S so a TTL survives
        # a restart without paying a transaction per chunk.
        if flush:
            try:
                self._cache.set(
                    _activity_key(chat_id, message_id),
                    now,
                    tag=_video_tag(chat_id, message_id),
                    expire=DISK_CACHE_TTL * 4,
                )
            except Exception:
                pass

    def _record(self, chat_id: int, message_id: int, chunk_idx: int, nbytes: int):
        key = (chat_id, message_id)
        with self._lock:
            self._chunk_sizes[_chunk_key(chat_id, message_id, chunk_idx)] = nbytes
            self._video_bytes[key] = self._video_bytes.get(key, 0) + nbytes

    def _enforce_per_video_cap(self, chat_id: int, message_id: int) -> int:
        """Evict the oldest chunks of one video once it exceeds the per-video
        cap. Returns bytes freed."""
        key = (chat_id, message_id)
        with self._lock:
            over = self._video_bytes.get(key, 0) - DISK_CACHE_PER_VIDEO_BYTES
            if over <= 0:
                return 0
            prefix = f"chunk:{chat_id}:{message_id}:"
            cached = []
            for ck in self._chunk_sizes:
                if ck.startswith(prefix):
                    try:
                        cached.append((int(ck[len(prefix) :]), ck))
                    except ValueError:
                        continue
            cached.sort()  # oldest chunk index first == oldest written chunk
        freed = 0
        for _, ck in cached:
            if over <= 0:
                break
            with self._lock:
                size = self._chunk_sizes.pop(ck, 0)
            try:
                self._cache.delete(ck)
            except Exception:
                pass
            with self._lock:
                self._video_bytes[key] = self._video_bytes.get(key, 0) - size
            over -= size
            freed += size
        return freed

    def _evict_video(self, chat_id: int, message_id: int) -> int:
        """Drop every chunk (and the activity marker) of one video."""
        prefix = f"chunk:{chat_id}:{message_id}:"
        with self._lock:
            freed = self._video_bytes.pop((chat_id, message_id), 0)
            for ck in [k for k in self._chunk_sizes if k.startswith(prefix)]:
                self._chunk_sizes.pop(ck, None)
            self._last_active.pop((chat_id, message_id), None)
            self._last_flush.pop((chat_id, message_id), None)
        try:
            self._cache.evict(tag=_video_tag(chat_id, message_id))
        except Exception:
            pass
        return freed

    # ── public API (unchanged for callers) ──────────────────────────────────
    def contains(self, chat_id: int, message_id: int, chunk_idx: int) -> bool:
        """Cheap existence check (SQLite index probe, no payload read)."""
        if self._cache is None:
            return False
        try:
            return _chunk_key(chat_id, message_id, chunk_idx) in self._cache
        except Exception:
            return False

    def chunk_indices(self, chat_id: int, message_id: int) -> frozenset[int]:
        """All cached chunk indices for a video.

        One prefix scan of the SQLite index (no file stats); the result is
        cheap enough to run at stream start, which is the only caller.
        """
        if self._cache is None:
            return frozenset()
        prefix = f"chunk:{chat_id}:{message_id}:"
        out: set[int] = set()
        try:
            for key in self._cache.iterkeys():
                if isinstance(key, str) and key.startswith(prefix):
                    try:
                        out.add(int(key[len(prefix) :]))
                    except ValueError:
                        continue
        except Exception:
            return frozenset()
        return frozenset(out)

    def touch(self, chat_id: int, message_id: int):
        """Record activity so the sweep does not expire a running stream."""
        if self._cache is None:
            return
        self._note_activity(chat_id, message_id)

    def used_bytes(self, max_age: float = 15.0) -> int:
        """Total bytes currently stored on disk (cheap: SQLite index sum).

        ``max_age`` is accepted for backwards compatibility; the library keeps
        its own size bookkeeping so no scan is ever needed.
        """
        if self._cache is None:
            return 0
        try:
            return int(self._cache.volume())
        except Exception:
            return 0

    def get(self, chat_id: int, message_id: int, chunk_idx: int) -> bytes | None:
        if self._cache is None:
            return None
        try:
            data = self._cache.get(_chunk_key(chat_id, message_id, chunk_idx))
        except Exception:
            return None
        if not data:
            return None
        self._note_activity(chat_id, message_id)
        return data

    def put(self, chat_id: int, message_id: int, chunk_idx: int, data: bytes):
        """Store one chunk. Never overwrites an existing chunk (first writer
        wins), matching the previous behaviour and the prefetcher's contract."""
        if self._cache is None or not data:
            return
        ck = _chunk_key(chat_id, message_id, chunk_idx)
        try:
            # Already written by this process: skip the redundant write. A
            # chunk written before a restart is simply rewritten (same bytes),
            # which is cheaper than a size-only probe the library doesn't offer.
            with self._lock:
                duplicate = ck in self._chunk_sizes
            if duplicate:
                self._note_activity(chat_id, message_id)
                return
            self._cache.set(
                ck,
                data,
                tag=_video_tag(chat_id, message_id),
                expire=DISK_CACHE_TTL,
            )
        except Exception:
            return
        self._record(chat_id, message_id, chunk_idx, len(data))
        self._note_activity(chat_id, message_id)
        self._enforce_per_video_cap(chat_id, message_id)

    def sweep(self) -> int:
        """Enforce TTL, per-video and total caps. Returns bytes freed."""
        if self._cache is None:
            return 0
        before = self.used_bytes()
        now = time.time()

        # 1. Force lazy TTL expiry so entries that lapsed while idle are
        #    reclaimed now instead of on their next read.
        try:
            self._cache.expire()
        except Exception:
            pass

        # 2. Drop videos that have been idle for the TTL window.
        for key, ts in list(self._last_active.items()):
            if now - ts > DISK_CACHE_TTL:
                self._evict_video(*key)
                continue
            # Forget bookkeeping for videos that no longer have chunks (e.g.
            # evicted by the global LRU) so the map cannot grow unbounded.
            if key not in self._video_bytes:
                try:
                    if self._cache.get(_activity_key(*key)) is None:
                        self._last_active.pop(key, None)
                        self._last_flush.pop(key, None)
                except Exception:
                    pass

        # 3. Remove legacy `{chat}_{msg}/{idx}.bin` dirs from the pre-diskcache
        #    layout. Never follow a symlink (see _remove_dir).
        self._purge_legacy_dirs()

        # 4. Global cap. diskcache culls on write, but an explicit pass keeps
        #    the cap honest after a config change (e.g. lowering the limit).
        try:
            if self.used_bytes() > DISK_CACHE_MAX_BYTES:
                self._cache.cull()
        except Exception:
            pass
        return max(0, before - self.used_bytes())

    def close(self):
        if self._cache is not None:
            try:
                self._cache.close()
            except Exception:
                pass

    # ── legacy layout cleanup ───────────────────────────────────────────────
    def _purge_legacy_dirs(self) -> int:
        try:
            entries = list(self.cache_dir.iterdir())
        except OSError:
            return 0
        freed = 0
        for d in entries:
            try:
                if d.is_symlink() or not d.is_dir():
                    continue
            except OSError:
                continue
            if _parse_key(d.name) is None:
                continue
            freed += self._dir_size(d)
            self._remove_dir(d)
        return freed

    @staticmethod
    def _dir_size(d: Path) -> int:
        total = 0
        try:
            for f in d.iterdir():
                try:
                    if f.is_file():
                        total += f.stat().st_size
                except OSError:
                    continue
        except OSError:
            return 0
        return total

    @staticmethod
    def _remove_dir(d: Path):
        # Never follow a symlinked dir: unlink the link itself so a planted
        # symlink can't make the purge delete outside the cache.
        try:
            if d.is_symlink():
                try:
                    d.unlink()
                except OSError:
                    pass
                return
        except OSError:
            return
        try:
            children = list(d.iterdir())
        except OSError:
            return
        for f in children:
            try:
                if f.is_symlink() or f.is_file():
                    f.unlink()
            except OSError:
                pass
        try:
            d.rmdir()
        except OSError:
            pass


_disk_cache = DiskChunkCache()
