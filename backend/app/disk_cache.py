"""
Simple disk-backed cold tier for streamed chunks.

Layout:  {DISK_CACHE_DIR}/{chat_id}_{message_id}/{chunk_index}.bin
Policy:  directories expire DISK_CACHE_TTL seconds after the LAST ACTIVITY
         (a touch from a stream write or a stream start) — i.e. "TTL after the
         active stream ends", not since-write. When total usage exceeds
         DISK_CACHE_MAX_BYTES the oldest dirs (LRU by last activity) are removed.
         Set DISK_CACHE_ENABLED=0 to disable (all methods become no-ops).
"""
import os
import threading
import time
from pathlib import Path

CACHE_DIR = Path(os.environ.get("DISK_CACHE_DIR", "./data/vcache"))
DISK_CACHE_TTL = int(os.environ.get("DISK_CACHE_TTL", "1800"))  # 30 minutes
DISK_CACHE_MAX_BYTES = int(os.environ.get("DISK_CACHE_MAX_BYTES", str(8 * 1024**3)))  # 8 GB total
DISK_CACHE_PER_VIDEO_BYTES = int(os.environ.get("DISK_CACHE_PER_VIDEO_BYTES", str(2 * 1024**3)))  # 2 GB per video
ENABLED = os.environ.get("DISK_CACHE_ENABLED", "1") == "1"


def _parse_key(dir_name: str) -> tuple[int, int] | None:
    """Parse '{chat_id}_{message_id}' from a movie dir name. chat_id may be
    negative, so split on the LAST underscore."""
    try:
        mid, cid = dir_name.rsplit("_", 1)
        return int(mid), int(cid)
    except (ValueError, AttributeError):
        return None


class DiskChunkCache:
    def __init__(self, cache_dir: Path | None = None):
        self.cache_dir = cache_dir or CACHE_DIR
        self._last_active: dict[tuple[int, int], float] = {}
        self._lock = threading.Lock()
        self._used_bytes = 0
        self._used_at: float | None = None

    def _movie_dir(self, chat_id: int, message_id: int) -> Path:
        return self.cache_dir / f"{chat_id}_{message_id}"

    def contains(self, chat_id: int, message_id: int, chunk_idx: int) -> bool:
        """Cheap existence check (no file read) — used to plan lazy disk serving."""
        if not ENABLED:
            return False
        return (self._movie_dir(chat_id, message_id) / f"{chunk_idx}.bin").is_file()

    def chunk_indices(self, chat_id: int, message_id: int) -> frozenset[int]:
        """All cached chunk indices for a movie via ONE directory scan.

        Used to plan lazy disk serving for a whole range: scanning a movie dir
        once and doing in-membership checks is far cheaper than ~2k per-chunk
        stat() calls on large streams."""
        if not ENABLED:
            return frozenset()
        d = self._movie_dir(chat_id, message_id)
        try:
            return frozenset(
                int(entry.name[:-4])
                for entry in os.scandir(d)
                if entry.is_file() and entry.name.endswith(".bin")
            )
        except (OSError, ValueError):
            return frozenset()

    def touch(self, chat_id: int, message_id: int):
        """Record activity for a movie so the sweep does not expire it while a
        stream is running (TTL counts from the last touch, i.e. after the
        active stream ends). Also bumps the dir mtime as a disk-side fallback."""
        if not ENABLED:
            return
        now = time.time()
        with self._lock:
            self._last_active[(chat_id, message_id)] = now
        try:
            d = self._movie_dir(chat_id, message_id)
            if d.is_dir():
                os.utime(d, None)
        except OSError:
            pass

    def used_bytes(self, max_age: float = 15.0) -> int:
        """Total bytes currently stored in the disk cache, cached for ``max_age``
        seconds so status/diag polls don't stat every chunk on each request."""
        if not ENABLED:
            return 0
        now = time.time()
        with self._lock:
            cached_at = self._used_at
            cached = self._used_bytes
        if cached_at is not None and now - cached_at < max_age:
            return cached
        total = 0
        try:
            it = os.scandir(self.cache_dir)
        except OSError:
            return 0
        with it:
            for d in it:
                if not d.is_dir():
                    continue
                try:
                    total += sum(e.stat().st_size for e in os.scandir(d.path) if e.is_file())
                except OSError:
                    continue
        with self._lock:
            self._used_at = now
            self._used_bytes = total
        return total

    def _activity_time(self, chat_id: int, message_id: int, d: Path) -> float:
        with self._lock:
            ts = self._last_active.get((chat_id, message_id))
        if ts is not None:
            return ts
        try:
            return d.stat().st_mtime
        except OSError:
            return time.time()

    def get(self, chat_id: int, message_id: int, chunk_idx: int) -> bytes | None:
        if not ENABLED:
            return None
        p = self._movie_dir(chat_id, message_id) / f"{chunk_idx}.bin"
        try:
            with open(p, "rb") as f:
                data = f.read()
        except OSError:
            return None
        if not data:
            return None
        try:
            os.utime(p, None)  # LRU touch
        except OSError:
            pass
        return data

    def put(self, chat_id: int, message_id: int, chunk_idx: int, data: bytes):
        """Write-through with atomic replace so a concurrent reader never sees
        a partially-written chunk (would corrupt the stream)."""
        if not ENABLED or not data:
            return
        try:
            d = self._movie_dir(chat_id, message_id)
            d.mkdir(parents=True, exist_ok=True)
            tmp = d / f"{chunk_idx}.bin.tmp"
            final = d / f"{chunk_idx}.bin"
            with open(tmp, "wb") as f:
                f.write(data)
            os.replace(tmp, final)
        except OSError:
            pass
        self.touch(chat_id, message_id)

    def sweep(self) -> int:
        """Remove dirs whose last activity is older than TTL (i.e. inactive for
        the TTL window), then evict oldest until under the cap. Returns freed bytes."""
        if not ENABLED:
            return 0
        if not self.cache_dir.exists():
            return 0
        now = time.time()
        total = 0
        entries: list[tuple[float, Path, int]] = []
        for d in self.cache_dir.iterdir():
            if not d.is_dir():
                continue
            key = _parse_key(d.name)
            if key is None:
                continue
            chat_id, message_id = key
            try:
                size = sum(f.stat().st_size for f in d.iterdir() if f.is_file())
            except OSError:
                continue
            total += size
            active_ts = self._activity_time(chat_id, message_id, d)
            if now - active_ts > DISK_CACHE_TTL:
                self._remove_dir(d)
                total -= size
            else:
                entries.append((active_ts, d, size))
        # Enforce per-video cap: evict oldest chunks within each movie dir.
        for _, d, _ in list(entries):
            try:
                files = sorted(d.iterdir(), key=lambda p: p.stat().st_mtime)
                size = sum(f.stat().st_size for f in files if f.is_file())
            except OSError:
                continue
            over = size - DISK_CACHE_PER_VIDEO_BYTES
            for f in files:
                if over <= 0:
                    break
                try:
                    over -= f.stat().st_size
                    f.unlink()
                except OSError:
                    pass
        # Recompute totals now that per-video caps may have shrunk dirs.
        entries = []
        total = 0
        for d in self.cache_dir.iterdir():
            if not d.is_dir():
                continue
            key = _parse_key(d.name)
            if key is None:
                continue
            chat_id, message_id = key
            try:
                size = sum(f.stat().st_size for f in d.iterdir() if f.is_file())
            except OSError:
                continue
            if size == 0:
                self._remove_dir(d)
                continue
            total += size
            entries.append((self._activity_time(chat_id, message_id, d), d, size))
        entries.sort(key=lambda x: x[0])
        freed = 0
        while total > DISK_CACHE_MAX_BYTES and entries:
            _, d, size = entries.pop(0)
            self._remove_dir(d)
            total -= size
            freed += size
        return freed

    @staticmethod
    def _remove_dir(d: Path):
        for f in d.iterdir():
            try:
                f.unlink()
            except OSError:
                pass
        try:
            d.rmdir()
        except OSError:
            pass


_disk_cache = DiskChunkCache()
