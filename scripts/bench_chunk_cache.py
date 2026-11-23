"""Benchmark the RAM chunk cache: cachebox (Rust) vs a Python dict+deque FIFO.

The streaming hot path looks up one entry per 1 MB chunk it serves, so this
measures the per-chunk cost of the in-process tier plus the eviction policy
difference (LRU keeps the chunks a backward seek is about to reuse, FIFO
drops them in write order).

Usage::

    python scripts/bench_chunk_cache.py
"""

from __future__ import annotations

import statistics
import time
from collections import deque

try:
    from cachebox import LRUCache
except ImportError:  # pragma: no cover
    raise SystemExit("pip install 'cachebox>=6.2.11' to run this benchmark")

CHUNK = b"x" * (1024 * 1024)
N = 400


class FifoChunkCache:
    """Pre-cachebox implementation, kept here as the baseline."""

    def __init__(self, max_bytes: int):
        self._data: dict[int, bytes] = {}
        self._order: deque[int] = deque()
        self._size = 0
        self._max = max_bytes

    def get(self, key: int) -> bytes | None:
        return self._data.get(key)

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


class CacheboxChunkCache:
    def __init__(self, max_bytes: int):
        self._c = LRUCache(maxsize=max_bytes, getsizeof=lambda _k, v: len(v))

    def get(self, key: int) -> bytes | None:
        return self._c.get(key)

    def put(self, key: int, data: bytes):
        if not data:
            return
        self._c.insert(key, data)


def measure(impl, max_bytes: int) -> tuple[list[float], list[float]]:
    cache = impl(max_bytes)
    puts: list[float] = []
    for i in range(N):
        t0 = time.perf_counter()
        cache.put(i, CHUNK)
        puts.append(time.perf_counter() - t0)
    gets: list[float] = []
    for i in range(N):
        t0 = time.perf_counter()
        cache.get(i)
        gets.append(time.perf_counter() - t0)
    return puts, gets


def report(label: str, puts: list[float], gets: list[float]):
    print(
        f"  {label:<22} put p50 {statistics.median(puts) * 1e6:6.2f} us  "
        f"p95 {sorted(puts)[int(len(puts) * 0.95) - 1] * 1e6:6.2f} us   "
        f"get p50 {statistics.median(gets) * 1e6:6.2f} us  "
        f"p95 {sorted(gets)[int(len(gets) * 0.95) - 1] * 1e6:6.2f} us"
    )


def main() -> int:
    max_bytes = 100 * 1024 * 1024  # 100 chunks live at once
    print(f"{N} x 1 MB chunks, {max_bytes // 1024 // 1024} MB live")
    report("dict+deque FIFO", *measure(FifoChunkCache, max_bytes))
    report("cachebox LRU (Rust)", *measure(CacheboxChunkCache, max_bytes))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
