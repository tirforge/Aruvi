"""Disk-backed cold tier for streamed chunks.

Storage is delegated to LMDB (https://www.lmdb.tech/), a memory-mapped B+tree
written in C and shipped as the storage engine behind OpenLDAP. Compared with
the previous pure-Python ``diskcache`` tier on the same 1 MB chunks it is ~8x
faster per write and ~2.5x faster per read (see
``scripts/bench_disk_cache.py``), because a write is a ``memcpy`` into the map
instead of a SQLite transaction plus a separate data file.

What LMDB gives us here:

* one atomic ``copy-on-write`` transaction per chunk, so a reader never sees a
  half-written value,
* an ordered keyspace, so the chunk index for one video is a single cursor
  range scan,
* multi-process read safety through the shared memory map (one writer at a
  time, which is all this process needs),
* a persistent key/value store that survives restarts without any replay.

That last point is the reason for the two extra databases: LMDB itself has no
LRU/TTL policy, so this module keeps one and reuses it as the source of truth
on start-up.

Key layout
----------
``chunks`` DB   ``chunk:{chat_id}:{message_id}:{chunk_idx}`` → 1 MB payload
``meta`` DB     same key                                      → <Q size
``activity`` DB ``@act:{chat_id}:{message_id}``               → <d timestamp

``meta`` mirrors ``chunks`` so ``used_bytes()`` and the per-video / global caps
are an in-memory sum of 8-byte values instead of a walk over payloads. The
whole index (8k entries for the default 8 GB cap) is rebuilt on open.

A video expires DISK_CACHE_TTL seconds after its last *use* (not since-write).
When the global cap is hit, the least-recently-active whole video is evicted;
if only one video exists, its oldest chunks are dropped. The legacy
``{chat_id}_{message_id}/{idx}.bin`` tree from the pre-diskcache implementation
is purged on open so an upgraded deployment does not leak it.

Set ``DISK_CACHE_ENABLED=0`` to make every method a no-op. The LMDB map starts
small and doubles on demand up to ``2 x DISK_CACHE_MAX_BYTES`` (override with
``DISK_CACHE_MAP_BYTES``), so a fresh cache does not reserve the full 8 GB.
"""

import logging
import os
import re
import shutil
import struct
import sys
import threading
import time
from pathlib import Path

try:
    import lmdb
except ImportError:  # pragma: no cover - dependency is in requirements.txt
    lmdb = None

from .byte_sizes import parse_byte_size

logger = logging.getLogger("disk_cache")

CACHE_DIR = Path(os.environ.get("DISK_CACHE_DIR", "./data/vcache"))
DISK_CACHE_TTL = int(os.environ.get("DISK_CACHE_TTL", "1800"))  # 30 minutes
# Byte limits accept human units ("8G", "2Gi", "1.5TB", "8589934592"). These
# used to be plain int(), so DISK_CACHE_MAX_BYTES=8G — the form every other
# size variable in this app accepts — crashed the backend at import time.
DISK_CACHE_MAX_BYTES = parse_byte_size(
    os.environ.get("DISK_CACHE_MAX_BYTES"),
    8 * 1024**3,
    name="DISK_CACHE_MAX_BYTES",
)  # 8 GB total
DISK_CACHE_PER_VIDEO_BYTES = parse_byte_size(
    os.environ.get("DISK_CACHE_PER_VIDEO_BYTES"),
    2 * 1024**3,
    name="DISK_CACHE_PER_VIDEO_BYTES",
)  # 2 GB per video
ENABLED = os.environ.get("DISK_CACHE_ENABLED", "1") == "1"

# How often a video's activity marker is rewritten. Without this every 1 MB
# chunk write would add an extra transaction just to bump the TTL clock.
_ACTIVITY_FLUSH_S = 5.0

# LMDB reserves address space, not disk: the map starts here and doubles as
# data arrives. 64-bit processes have plenty of address space; the file only
# grows when pages are actually written.
_MIN_MAP_BYTES = 16 * 1024 * 1024
_LMDB_SUBDIR = "lmdb"
_DBS = (b"chunks", b"meta", b"activity")
_SIZE = struct.Struct("<Q")
_TIMESTAMP = struct.Struct("<d")

_CHUNK_PREFIX = "chunk:"
_ACTIVITY_PREFIX = "@act:"

# diskcache left its SQLite index next to two levels of hex payload dirs
# (<dir>/ab/cd/<name>.val). Detect the index first so an unrelated hex-named
# directory is never touched.
_DISKCACHE_FILES = ("cache.db", "cache.db-wal", "cache.db-shm", "cache.db-journal")
_HEX_DIR = re.compile(r"[0-9a-f]{2}\Z")


def _parse_key(dir_name: str) -> tuple[int, int] | None:
    """Parse '{chat_id}_{message_id}' from a legacy movie dir name. chat_id may
    be negative, so split on the LAST underscore."""
    try:
        mid, cid = dir_name.rsplit("_", 1)
        return int(mid), int(cid)
    except (ValueError, AttributeError):
        return None


def _chunk_key(chat_id: int, message_id: int, chunk_idx: int) -> str:
    return f"{_CHUNK_PREFIX}{chat_id}:{message_id}:{chunk_idx}"


def _chunk_prefix(chat_id: int, message_id: int) -> str:
    return f"{_CHUNK_PREFIX}{chat_id}:{message_id}:"


def _video_key(chat_id: int, message_id: int) -> str:
    return f"{chat_id}:{message_id}"


def _activity_key(chat_id: int, message_id: int) -> str:
    return f"{_ACTIVITY_PREFIX}{chat_id}:{message_id}"


def _split_chunk_key(key: str) -> tuple[int, int, int] | None:
    """``chunk:{chat}:{msg}:{idx}`` → ``(chat, msg, idx)``."""
    if not key.startswith(_CHUNK_PREFIX):
        return None
    parts = key[len(_CHUNK_PREFIX) :].split(":")
    if len(parts) != 3:
        return None
    try:
        return int(parts[0]), int(parts[1]), int(parts[2])
    except ValueError:
        return None


def _split_activity_key(key: str) -> tuple[int, int] | None:
    if not key.startswith(_ACTIVITY_PREFIX):
        return None
    parts = key[len(_ACTIVITY_PREFIX) :].split(":")
    if len(parts) != 2:
        return None
    try:
        return int(parts[0]), int(parts[1])
    except ValueError:
        return None


class DiskChunkCache:
    """LMDB-backed cold tier with a per-video TTL and size caps."""

    def __init__(self, cache_dir: Path | None = None):
        self.cache_dir = Path(cache_dir or CACHE_DIR)
        self._lock = threading.RLock()
        self._last_active: dict[tuple[int, int], float] = {}
        self._last_flush: dict[tuple[int, int], float] = {}
        self._video_bytes: dict[tuple[int, int], int] = {}
        self._chunk_sizes: dict[str, int] = {}
        self._total_bytes = 0
        self._env = None
        self._chunks = None
        self._meta = None
        self._activity = None
        self._map_size = 0
        self._max_map_bytes = max(
            parse_byte_size(
                os.environ.get("DISK_CACHE_MAP_BYTES"),
                0,
                name="DISK_CACHE_MAP_BYTES",
            ),
            DISK_CACHE_MAX_BYTES * 2,
            _MIN_MAP_BYTES * 8,
        )

        if not ENABLED or lmdb is None:
            if lmdb is None:
                logger.warning(
                    "lmdb is not installed - the disk cache tier is DISABLED. "
                    "Install it with: pip install 'lmdb>=1.6'"
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
            self._open_env()
        except Exception as e:  # broken FS, corrupt map, no address space
            logger.warning("Cannot open disk cache at %s: %s", self.cache_dir, e)
            self._env = None
            return

        # One-time upgrade step: the old implementation stored one directory
        # per video ({chat}_{msg}/*.bin) which LMDB knows nothing about. Purge
        # it now so an upgraded box reclaims that disk immediately.
        try:
            freed = self._purge_legacy_dirs()
            if freed:
                logger.info(
                    "Disk cache: purged %.1f MB of legacy chunk files",
                    freed / 1024 / 1024,
                )
        except OSError:
            pass

        # The previous tier (diskcache) left a SQLite index and hex payload
        # directories behind; LMDB cannot see them, so reclaim that disk now.
        try:
            freed = self._purge_old_tier()
            if freed:
                logger.info(
                    "Disk cache: purged %.1f MB of pre-LMDB cache files",
                    freed / 1024 / 1024,
                )
        except OSError:
            pass

        self._rebuild_index()

    # ── LMDB plumbing ───────────────────────────────────────────────────────
    def _open_env(self) -> None:
        path = self.cache_dir / _LMDB_SUBDIR
        last_error = None
        for attempt in (0, 1):
            env = None
            try:
                env = lmdb.open(
                    str(path),
                    map_size=_MIN_MAP_BYTES,
                    subdir=True,
                    max_dbs=len(_DBS),
                    writemap=sys.maxsize > 2**32,
                    sync=False,
                    metasync=False,
                    readahead=False,
                    meminit=False,
                )
                self._chunks = env.open_db(b"chunks", create=True)
                self._meta = env.open_db(b"meta", create=True)
                self._activity = env.open_db(b"activity", create=True)
                self._env = env
                self._map_size = _MIN_MAP_BYTES
                return
            except lmdb.Error as exc:  # crash left a torn meta page
                last_error = exc
                if env is not None:
                    try:
                        env.close()
                    except Exception:  # noqa: BLE001
                        pass
                if attempt == 0:
                    logger.warning(
                        "Disk cache at %s is unreadable (%s) - rebuilding it",
                        path,
                        exc,
                    )
                    shutil.rmtree(path, ignore_errors=True)
        raise lmdb.Error(f"cannot open {path}: {last_error}")

    def _rebuild_index(self) -> None:
        """Load sizes and activity from LMDB so TTL/used_bytes survive a restart."""
        chunks = 0
        with self._lock:
            with self._env.begin(db=self._meta) as txn:
                cursor = txn.cursor()
                for raw_key, raw_value in cursor:
                    key = raw_key.decode("ascii", "ignore")
                    parsed = _split_chunk_key(key)
                    if parsed is None or len(raw_value) != _SIZE.size:
                        continue
                    nbytes = _SIZE.unpack(raw_value)[0]
                    self._chunk_sizes[key] = nbytes
                    video = (parsed[0], parsed[1])
                    self._video_bytes[video] = (
                        self._video_bytes.get(video, 0) + nbytes
                    )
                    self._total_bytes += nbytes
                    chunks += 1
            with self._env.begin(db=self._activity) as txn:
                for raw_key, raw_value in txn.cursor():
                    key = raw_key.decode("ascii", "ignore")
                    parsed = _split_activity_key(key)
                    if parsed is None or len(raw_value) != _TIMESTAMP.size:
                        continue
                    self._last_active[parsed] = _TIMESTAMP.unpack(raw_value)[0]

        now = time.time()
        for video in self._video_bytes:
            # A crash between the chunk write and the throttled activity write
            # would leave no marker; treat it as just-used instead of instantly
            # expiring a video the user is still watching.
            self._last_active.setdefault(video, now)
        if chunks:
            logger.info(
                "Disk cache: recovered %d chunks (%.1f MB) from LMDB",
                chunks,
                self._total_bytes / 1024 / 1024,
            )

    def _grow_map(self, needed: int) -> bool:
        """Double the map until ``needed`` bytes fit. Caller holds ``_lock``."""
        info = self._env.info()
        page_size = self._env.stat()["psize"]
        used = (info["last_pgno"] + 1) * page_size
        target = min(
            self._max_map_bytes,
            max(self._map_size * 2, used + needed + page_size * 8),
        )
        if target <= self._map_size:
            return False
        for _ in range(20):
            try:
                self._env.set_mapsize(target)
            except lmdb.Error:
                # Another thread's reader can transiently block the resize.
                time.sleep(0.01)
                continue
            self._map_size = target
            return True
        return False

    def _write_chunk(self, key: str, data: bytes) -> bool:
        """Atomic first-writer-wins put. Caller holds ``_lock``.

        ``overwrite=False`` makes the existence check and the insert one
        transaction, so two threads racing on the same chunk cannot tear it.
        """
        raw_key = key.encode()
        needed = len(data) + 4096
        for _ in range(4):
            try:
                info = self._env.info()
                page_size = self._env.stat()["psize"]
                if (info["last_pgno"] + 1) * page_size + needed > self._map_size:
                    self._grow_map(needed)
                with self._env.begin(write=True) as txn:
                    if not txn.put(raw_key, data, db=self._chunks, overwrite=False):
                        return False
                    txn.put(raw_key, _SIZE.pack(len(data)), db=self._meta)
                    return True
            except lmdb.MapFullError:
                if not self._grow_map(needed):
                    return False
            except lmdb.Error:
                logger.warning("Disk cache write failed", exc_info=True)
                return False
        return False

    def _delete_chunks(self, victims: list[tuple[str, int]]) -> int:
        """Delete ``(key, size)`` pairs in one transaction."""
        if not victims:
            return 0
        with self._lock:
            try:
                with self._env.begin(write=True) as txn:
                    for key, _ in victims:
                        raw_key = key.encode()
                        txn.delete(raw_key, db=self._chunks)
                        txn.delete(raw_key, db=self._meta)
            except lmdb.Error:
                return 0
            freed = 0
            for key, fallback in victims:
                size = self._chunk_sizes.pop(key, fallback)
                parsed = _split_chunk_key(key)
                if parsed is not None:
                    video = (parsed[0], parsed[1])
                    remaining = self._video_bytes.get(video, 0) - size
                    if remaining > 0:
                        self._video_bytes[video] = remaining
                    else:
                        self._video_bytes.pop(video, None)
                self._total_bytes -= size
                freed += size
            if self._total_bytes < 0:
                self._total_bytes = 0
            return freed

    # ── helpers ─────────────────────────────────────────────────────────────
    @property
    def enabled(self) -> bool:
        return self._env is not None

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
                try:
                    with self._env.begin(write=True) as txn:
                        txn.put(
                            _activity_key(*key).encode(),
                            _TIMESTAMP.pack(now),
                            db=self._activity,
                        )
                except Exception:  # noqa: BLE001 - a lost marker is not fatal
                    pass

    def _record(self, chat_id: int, message_id: int, chunk_idx: int, nbytes: int):
        key = (chat_id, message_id)
        with self._lock:
            ck = _chunk_key(chat_id, message_id, chunk_idx)
            if ck in self._chunk_sizes:  # lost a race, already counted
                return
            self._chunk_sizes[ck] = nbytes
            self._video_bytes[key] = self._video_bytes.get(key, 0) + nbytes
            self._total_bytes += nbytes

    def _enforce_per_video_cap(self, chat_id: int, message_id: int) -> int:
        """Evict the oldest chunks of one video once it exceeds the per-video
        cap. Returns bytes freed."""
        key = (chat_id, message_id)
        with self._lock:
            over = self._video_bytes.get(key, 0) - DISK_CACHE_PER_VIDEO_BYTES
            if over <= 0:
                return 0
            prefix = _chunk_prefix(chat_id, message_id)
            cached = []
            for ck in self._chunk_sizes:
                if ck.startswith(prefix):
                    try:
                        cached.append((int(ck[len(prefix) :]), ck))
                    except ValueError:
                        continue
            cached.sort()  # oldest chunk index first == oldest written chunk
            victims: list[tuple[str, int]] = []
            for _, ck in cached:
                if over <= 0:
                    break
                size = self._chunk_sizes.get(ck, 0)
                victims.append((ck, size))
                over -= size
        return self._delete_chunks(victims)

    def _enforce_global_cap(self) -> int:
        """Evict whole videos (least-recently-used first) until under the cap."""
        freed = 0
        with self._lock:
            while self._total_bytes > DISK_CACHE_MAX_BYTES:
                # Every eviction step must strictly reduce _total_bytes. LMDB
                # errors make _evict_video/_delete_chunks return 0 *without*
                # changing the counter, so looping on the byte total alone
                # would spin forever while holding the cache lock — blocking
                # every get/put/sweep in the process. Break when a step makes
                # no progress instead.
                before = self._total_bytes
                candidates = [vk for vk, n in self._video_bytes.items() if n > 0]
                if not candidates:
                    break
                candidates.sort(key=lambda vk: self._last_active.get(vk, 0.0))
                oldest = candidates[0]
                if len(candidates) > 1:
                    freed += self._evict_video(*oldest)
                else:
                    # A single video larger than the whole cache: drop its oldest
                    # chunks, never the newest one that was just written.
                    prefix = _chunk_prefix(*oldest)
                    over = self._total_bytes - DISK_CACHE_MAX_BYTES
                    cached = sorted(
                        (int(ck[len(prefix) :]), ck)
                        for ck in self._chunk_sizes
                        if ck.startswith(prefix)
                    )
                    victims: list[tuple[str, int]] = []
                    for _, ck in cached:
                        if over <= 0:
                            break
                        size = self._chunk_sizes.get(ck, 0)
                        victims.append((ck, size))
                        over -= size
                    if not victims:
                        break
                    freed += self._delete_chunks(victims)
                if self._total_bytes >= before:
                    logger.warning(
                        "Disk cache: eviction made no progress (%d > %d bytes) — "
                        "stopping until the next sweep",
                        self._total_bytes,
                        DISK_CACHE_MAX_BYTES,
                    )
                    break
        return freed

    def _evict_video(self, chat_id: int, message_id: int) -> int:
        """Drop every chunk (and the activity marker) of one video."""
        prefix = _chunk_prefix(chat_id, message_id)
        with self._lock:
            try:
                with self._env.begin(write=True) as txn:
                    cursor = txn.cursor(db=self._meta)
                    victims: list[tuple[bytes, int]] = []
                    if cursor.set_range(prefix.encode()):
                        while cursor.key().startswith(prefix.encode()):
                            raw_value = cursor.value()
                            size = (
                                _SIZE.unpack(raw_value)[0]
                                if len(raw_value) == _SIZE.size
                                else 0
                            )
                            victims.append((cursor.key(), size))
                            if not cursor.next():
                                break
                    for raw_key, _ in victims:
                        txn.delete(raw_key, db=self._chunks)
                        txn.delete(raw_key, db=self._meta)
                    txn.delete(
                        _activity_key(chat_id, message_id).encode(),
                        db=self._activity,
                    )
            except lmdb.Error:
                return 0

            freed = 0
            for raw_key, size in victims:
                key = raw_key.decode("ascii", "ignore")
                size = self._chunk_sizes.pop(key, size)
                self._total_bytes -= size
                freed += size
            self._video_bytes.pop((chat_id, message_id), None)
            self._last_active.pop((chat_id, message_id), None)
            self._last_flush.pop((chat_id, message_id), None)
            if self._total_bytes < 0:
                self._total_bytes = 0
            return freed

    # ── public API (unchanged for callers) ──────────────────────────────────
    def contains(self, chat_id: int, message_id: int, chunk_idx: int) -> bool:
        """Cheap existence check (one B+tree probe, no payload copy)."""
        if self._env is None:
            return False
        try:
            with self._env.begin(db=self._chunks) as txn:
                return txn.get(_chunk_key(chat_id, message_id, chunk_idx).encode()) is not None
        except Exception:  # noqa: BLE001
            return False

    def chunk_indices(self, chat_id: int, message_id: int) -> frozenset[int]:
        """All cached chunk indices for a video.

        One ordered range scan of the ``meta`` keyspace (8-byte values, no
        payload reads); cheap enough to run at stream start.
        """
        if self._env is None:
            return frozenset()
        prefix = _chunk_prefix(chat_id, message_id).encode()
        out: set[int] = set()
        try:
            with self._env.begin(db=self._meta) as txn:
                cursor = txn.cursor()
                if not cursor.set_range(prefix):
                    return frozenset()
                while cursor.key().startswith(prefix):
                    key = cursor.key().decode("ascii", "ignore")
                    try:
                        out.add(int(key[len(prefix) :]))
                    except ValueError:
                        pass
                    if not cursor.next():
                        break
        except Exception:  # noqa: BLE001
            return frozenset()
        return frozenset(out)

    def touch(self, chat_id: int, message_id: int):
        """Record activity so the sweep does not expire a running stream."""
        if self._env is None:
            return
        self._note_activity(chat_id, message_id)

    def used_bytes(self, max_age: float = 15.0) -> int:
        """Live payload bytes on disk (O(1): a running total kept in memory).

        ``max_age`` is accepted for backwards compatibility; the total is
        updated on every put/evict instead of being recomputed.
        """
        if self._env is None:
            return 0
        with self._lock:
            return self._total_bytes

    def get(self, chat_id: int, message_id: int, chunk_idx: int) -> bytes | None:
        if self._env is None:
            return None
        try:
            with self._env.begin(db=self._chunks) as txn:
                data = txn.get(_chunk_key(chat_id, message_id, chunk_idx).encode())
        except Exception:  # noqa: BLE001
            return None
        if not data:
            return None
        self._note_activity(chat_id, message_id)
        return data

    def put(self, chat_id: int, message_id: int, chunk_idx: int, data: bytes):
        """Store one chunk. Never overwrites an existing chunk (first writer
        wins), matching the previous behaviour and the prefetcher's contract."""
        if self._env is None or not data:
            return
        key = _chunk_key(chat_id, message_id, chunk_idx)
        with self._lock:
            if self._write_chunk(key, data):
                self._record(chat_id, message_id, chunk_idx, len(data))
            self._note_activity(chat_id, message_id)
            self._enforce_per_video_cap(chat_id, message_id)
            self._enforce_global_cap()

    def sweep(self) -> int:
        """Enforce TTL, per-video and total caps. Returns bytes freed."""
        if self._env is None:
            return 0
        with self._lock:
            before = self._total_bytes
            now = time.time()

            # 1. Drop videos that have been idle for the TTL window.
            for key, ts in list(self._last_active.items()):
                if now - ts > DISK_CACHE_TTL:
                    self._evict_video(*key)
                    continue
                # Forget bookkeeping for videos that no longer have chunks
                # (e.g. already evicted) so the map cannot grow unbounded.
                if key not in self._video_bytes:
                    self._last_active.pop(key, None)
                    self._last_flush.pop(key, None)

            # 2. Remove legacy `{chat}_{msg}/{idx}.bin` dirs from the
            #    pre-diskcache layout. Never follow a symlink (see _remove_dir).
            self._purge_legacy_dirs()

            # 3. Global cap, including after a config change (e.g. lowering
            #    DISK_CACHE_MAX_BYTES on a running box).
            self._enforce_global_cap()
            return max(0, before - self._total_bytes)

    def close(self):
        if self._env is not None:
            with self._lock:
                env = self._env
                self._env = None
                self._chunks = None
                self._meta = None
                self._activity = None
            try:
                env.close()
            except Exception:  # noqa: BLE001
                pass

    # ── legacy layout cleanup ───────────────────────────────────────────────
    def _purge_old_tier(self) -> int:
        """Remove the pre-LMDB ``diskcache`` tree (SQLite index + value dirs)."""
        try:
            entries = list(self.cache_dir.iterdir())
        except OSError:
            return 0
        if not any(e.name == "cache.db" for e in entries):
            return 0
        freed = 0
        for entry in entries:
            try:
                if entry.is_symlink():
                    continue
                if entry.is_file() and entry.name in _DISKCACHE_FILES:
                    freed += entry.stat().st_size
                    entry.unlink()
                elif entry.is_dir() and _HEX_DIR.fullmatch(entry.name):
                    freed += self._tree_size(entry)
                    shutil.rmtree(entry, ignore_errors=True)
            except OSError:
                continue
        return freed

    @staticmethod
    def _tree_size(d: Path) -> int:
        total = 0
        for root, _dirs, files in os.walk(d, followlinks=False):
            for name in files:
                try:
                    total += os.path.getsize(os.path.join(root, name))
                except OSError:
                    continue
        return total

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
