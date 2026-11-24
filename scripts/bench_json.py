"""Compare stdlib ``json`` with ``orjson`` for API response serialization.

Every JSON API response in Aruvi is serialized on the event loop (FastAPI's
``JSONResponse`` uses ``json.dumps``). ``orjson`` is the Rust encoder FastAPI
ships an ``ORJSONResponse`` for; it emits UTF-8 bytes directly and is
materially faster on the list endpoints (``/api/files``, ``/tv/browse``).

Usage::

    python scripts/bench_json.py
"""

from __future__ import annotations

import json
import statistics
import time

try:
    import orjson
except ImportError:  # pragma: no cover
    raise SystemExit("pip install orjson to run this benchmark")

# A realistic /api/files payload: 400 rows with the fields the UI actually uses.
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
        "thumbnail": True,
        "public_hash": "aBcDeFgHiJkLmNoP",
        "duration": 7200 + i,
        "progress": {"position": 120 + i, "updated_at": "2026-01-02T03:04:05"},
        "tags": ["action", "sci-fi", "2024"],
    }
    for i in range(400)
]
PAYLOAD = {"files": FILES, "total": len(FILES)}
SAMPLES = 200


def bench(name: str, fn) -> None:
    times = []
    size = 0
    for _ in range(SAMPLES):
        t0 = time.perf_counter()
        out = fn()
        times.append(time.perf_counter() - t0)
        size = len(out)
    p50 = statistics.median(times)
    p95 = statistics.quantiles(times, n=20)[-1]
    print(
        f"  {name:<22} {size / 1024:7.1f} KB  p50 {p50 * 1000:6.3f} ms  "
        f"p95 {p95 * 1000:6.3f} ms  {size / p50 / 1e6:7.1f} MB/s"
    )


def main() -> int:
    print(f"JSON payload: 400 files, {len(json.dumps(PAYLOAD)) / 1024:.1f} KB")
    bench("json.dumps+encode", lambda: json.dumps(PAYLOAD).encode())
    bench("orjson.dumps", lambda: orjson.dumps(PAYLOAD))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
