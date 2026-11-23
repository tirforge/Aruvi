"""Benchmark the disk cache tier.

Measures the numbers the streaming path actually cares about:

* ``put`` throughput for 1 MB chunks (writes happen on every fetched chunk),
* ``get`` throughput for 1 MB chunks (one read per chunk served from disk),
* ``contains``/``chunk_indices`` latency used to plan a stream start,
* sweep cost against a cache holding ~1 GB (the old implementation walked the
  whole tree twice per sweep).

Usage (from ``backend/``)::

    python ../scripts/bench_disk_cache.py            # default: 1 GB of chunks
    python ../scripts/bench_disk_cache.py --mb 256   # smaller run
    python ../scripts/bench_disk_cache.py --old      # legacy file-per-chunk impl

``--old`` imports the pre-LMDB implementation from git (``HEAD~1`` by
default) so the two can be compared side by side on the same machine:

    python ../scripts/bench_disk_cache.py --old --old-ref <commit>
"""

from __future__ import annotations

import argparse
import importlib.util
import pathlib
import statistics
import subprocess
import sys
import tempfile
import time

CHUNK = 1024 * 1024  # 1 MB, matches streaming.ChunkCache
PAYLOAD = bytes(range(256)) * (CHUNK // 256)


def _load_module(path: pathlib.Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _extract_old(ref: str, dest: pathlib.Path) -> pathlib.Path:
    """Write the disk_cache.py from ``ref`` into ``dest``."""
    repo = pathlib.Path(__file__).resolve().parent.parent
    try:
        blob = subprocess.check_output(
            ["git", "-C", str(repo), "show", f"{ref}:backend/app/disk_cache.py"]
        )
    except (subprocess.CalledProcessError, FileNotFoundError) as e:
        raise SystemExit(f"cannot read backend/app/disk_cache.py at {ref}: {e}")
    dest.write_bytes(blob)
    return dest


def _timed(fn, n: int) -> tuple[float, list[float]]:
    samples = []
    start = time.perf_counter()
    for i in range(n):
        t0 = time.perf_counter()
        fn(i)
        samples.append(time.perf_counter() - t0)
    return time.perf_counter() - start, samples


def _report(label: str, total_s: float, samples: list[float], n: int, size: int):
    rate = (n * size) / total_s / 1024 / 1024 if total_s else float("inf")
    p50 = statistics.median(samples) * 1000
    p95 = sorted(samples)[max(0, int(len(samples) * 0.95) - 1)] * 1000
    print(
        f"  {label:<22} {n:>5} ops  {total_s:7.2f}s  "
        f"{rate:7.1f} MB/s  p50 {p50:6.2f} ms  p95 {p95:6.2f} ms"
    )


def run(cache, n_chunks: int) -> None:
    key = (1, 2)
    cache.touch(*key)

    total, samples = _timed(lambda i: cache.put(*key, i, PAYLOAD), n_chunks)
    _report("put (1 MB)", total, samples, n_chunks, CHUNK)

    total, samples = _timed(lambda i: cache.get(*key, i), n_chunks)
    misses = sum(1 for i in range(n_chunks) if cache.get(*key, i) is None)
    _report("get (1 MB)", total, samples, n_chunks, CHUNK)
    if misses:
        print(f"  note: {misses} chunks were evicted during the run (cap hit)")

    present = cache.chunk_indices(*key)
    print(f"  chunk_indices()        {len(present)} chunks indexed")

    t0 = time.perf_counter()
    total_bytes = cache.used_bytes()
    print(
        f"  used_bytes()           {total_bytes / 1024 / 1024:8.1f} MB "
        f"in {(time.perf_counter() - t0) * 1000:.2f} ms"
    )

    t0 = time.perf_counter()
    freed = cache.sweep()
    print(
        f"  sweep()                freed {freed / 1024 / 1024:6.1f} MB "
        f"in {(time.perf_counter() - t0) * 1000:.2f} ms"
    )


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--mb", type=int, default=1024, help="MB of chunks to write")
    ap.add_argument("--old", action="store_true", help="also benchmark the legacy impl")
    ap.add_argument("--old-ref", default="HEAD", help="git ref of the legacy impl")
    args = ap.parse_args()

    n_chunks = max(1, args.mb)

    print(f"LMDB backend ({n_chunks} x 1 MB chunks)")
    backend = pathlib.Path(__file__).resolve().parent.parent / "backend"
    new_mod = _load_module(backend / "app" / "disk_cache.py", "aruvi_disk_cache")

    with tempfile.TemporaryDirectory() as td:
        cache = new_mod.DiskChunkCache(cache_dir=pathlib.Path(td) / "new")
        run(cache, n_chunks)
        cache.close()

    if args.old:
        print(f"\nlegacy file-per-chunk backend (from git {args.old_ref})")
        with tempfile.TemporaryDirectory() as td:
            src = _extract_old(args.old_ref, pathlib.Path(td) / "old_disk_cache.py")
            old_mod = _load_module(src, "old_disk_cache")
            cache_dir = pathlib.Path(td) / "old"
            cache_dir.mkdir()
            cache = old_mod.DiskChunkCache(cache_dir=cache_dir)
            # The legacy impl sizes itself from module globals; give it room.
            old_mod.DISK_CACHE_MAX_BYTES = 64 * 1024**3
            old_mod.DISK_CACHE_PER_VIDEO_BYTES = 64 * 1024**3
            run(cache, n_chunks)

    return 0


if __name__ == "__main__":
    sys.exit(main())
