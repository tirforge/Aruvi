"""Compare compression backends for the JSON/HTML compression middleware.

The middleware runs on the event loop, so CPU cost per response matters.
Brotli compresses text better than gzip at a comparable speed (quality 4),
and the C library is portable (x86_64 + aarch64 wheels), unlike ISA-L.

Usage::

    python scripts/bench_compression.py
"""

from __future__ import annotations

import gzip
import json
import statistics
import time

try:
    import brotli
except ImportError:  # pragma: no cover
    raise SystemExit("pip install brotli to run this benchmark")

# A realistic /api/files payload: 400 rows of metadata.
FILES = [
    {
        "id": i,
        "file_name": "Some.Movie.2024.1080p.WEB-DL.x264-GROUP.mkv",
        "file_size": 2_147_483_648 + i,
        "mime_type": "video/x-matroska",
        "created_at": "2026-01-02T03:04:05",
        "folder_id": i % 17,
        "chat_id": -1003950847652,
        "message_id": 197 + i,
    }
    for i in range(400)
]
PAYLOAD = json.dumps({"files": FILES, "total": len(FILES)}).encode()
HTML = b"<div class='card'><h3>Some Movie</h3><p>1080p WEB-DL</p></div>" * 1500
SAMPLES = 40


def report(name: str, body: bytes, fn) -> None:
    times = []
    size = 0
    for _ in range(SAMPLES):
        t0 = time.perf_counter()
        out = fn()
        times.append(time.perf_counter() - t0)
        size = len(out)
    print(
        f"  {name:<26} {len(body) / 1024:7.1f} KB -> {size / 1024:6.1f} KB "
        f"({size / len(body) * 100:4.1f}%)  p50 {statistics.median(times) * 1000:6.3f} ms"
    )


def main() -> int:
    for label, body in (("JSON (400 files)", PAYLOAD), ("HTML (SPA page)", HTML)):
        print(f"{label}: {len(body) / 1024:.1f} KB")
        report("gzip zlib level 6 (now)", body, lambda b=body: gzip.compress(b, 6))
        for quality in (3, 4, 5):
            report(
                f"brotli quality {quality}",
                body,
                lambda b=body, q=quality: brotli.compress(b, quality=q),
            )
        print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
