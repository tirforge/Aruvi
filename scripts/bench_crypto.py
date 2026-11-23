"""Compare the native MTProto crypto backend with Pyrogram's pyaes fallback.

Pyrogram uses `kuricrypt` (Rust) or `tgcrypto` (C) when present and silently
falls back to pure-python `pyaes` otherwise. The fallback decrypts one 1 MiB
chunk in seconds instead of milliseconds, which is the difference between a
1080p stream and a stall; this script measures both in the same process tree.

Usage::

    python scripts/bench_crypto.py
"""

from __future__ import annotations

import os
import pathlib
import subprocess
import sys
import tempfile
import time

CHUNK = 1024 * 1024
SAMPLES = 8


def _block(module: str, directory: pathlib.Path) -> None:
    """Make ``import <module>`` fail from here on.

    Must run before ``pyrogram.crypto.aes`` is imported: the module resolves
    its backend at import time and caches it.
    """
    (directory / f"{module}.py").write_text(
        'raise ImportError("bench_crypto: forcing the fallback")\n',
        encoding="utf-8",
    )
    sys.path.insert(0, str(directory))


def _measure() -> tuple[str, float]:
    from pyrogram.crypto import aes

    key, iv = os.urandom(32), os.urandom(32)
    chunk = os.urandom(CHUNK)
    aes.ige256_decrypt(chunk[:65536], key, iv)  # warm up

    backend = getattr(aes, "_crypto_backend", None)
    name = getattr(backend, "__name__", None) or "pyaes"
    samples = SAMPLES if backend is not None else 4

    started = time.perf_counter()
    for _ in range(samples):
        aes.ige256_decrypt(chunk, key, iv)
    per_chunk = (time.perf_counter() - started) / samples
    return name, per_chunk


def _report(name: str, per_chunk: float) -> float:
    mbps = CHUNK / per_chunk / 1e6
    ceiling = 8 * mbps
    print(
        f"{name:12} {per_chunk * 1000:9.3f} ms/MiB  "
        f"{mbps:8.1f} MB/s  {ceiling:8.0f} Mbit/s per core"
    )
    return ceiling


def main() -> None:
    if "--fallback" in sys.argv:
        with tempfile.TemporaryDirectory(prefix="bench-crypto-") as tmp:
            directory = pathlib.Path(tmp)
            _block("kuricrypt", directory)
            _block("tgcrypto", directory)
            name, per_chunk = _measure()
        _report(name, per_chunk)
        return

    name, per_chunk = _measure()
    native_ceiling = _report(name, per_chunk)

    result = subprocess.run(
        [sys.executable, __file__, "--fallback"],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        print(result.stderr.strip() or "fallback measurement failed")
        return
    print(result.stdout.rstrip())

    try:
        fallback_ceiling = float(result.stdout.split("Mbit/s")[0].split()[-1])
    except (IndexError, ValueError):
        return
    if fallback_ceiling:
        print(f"\nheadroom: {native_ceiling / fallback_ceiling:,.0f}x")


if __name__ == "__main__":
    main()
