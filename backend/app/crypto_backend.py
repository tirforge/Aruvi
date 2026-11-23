"""Which MTProto crypto backend Pyrogram actually loaded.

Pyrogram tries `kuricrypt` (Rust), then `tgcrypto` (C), and finally falls back
to pure-Python `pyaes`. The fallback is not a rounding error: on one 1 MiB
chunk it costs ~2.5 s (~0.4 MB/s, a ~3 Mbit/s per-core ceiling) against ~1.3 ms
(~787 MiB/s) with a native backend, and the GIL serialises that across the
11 bot clients. A deployment that silently lands on pyaes cannot stream 1080p,
so it must be visible in the startup log instead of hidden behind the
``kurigram[fast]`` extra.
"""

from __future__ import annotations

import logging

from pyrogram.crypto import aes

NATIVE_BACKENDS = ("kuricrypt", "tgcrypto")


def backend_name() -> str:
    """Name of the active backend (``"pyaes"`` for the pure-Python fallback)."""
    backend = getattr(aes, "_crypto_backend", None)
    return getattr(backend, "__name__", None) or "pyaes"


def is_native() -> bool:
    return backend_name() in NATIVE_BACKENDS


def log_backend(logger: logging.Logger, diag=None) -> str:
    """Log the active backend; ERROR when the slow fallback is in use.

    ``diag`` is ``telegram.diag_log``, which also mirrors the line into the
    startup log shown by the diagnostics endpoint.
    """
    name = backend_name()
    if is_native():
        if diag is not None:
            diag(f"MTProto crypto backend: {name} (native)")
        else:
            logger.info("MTProto crypto backend: %s (native)", name)
    else:
        logger.error(
            "MTProto crypto backend: %s (PURE PYTHON fallback, ~3 Mbit/s per "
            "core) - install kuricrypt (backend/requirements.txt)",
            name,
        )
        if diag is not None:
            diag(f"MTProto crypto backend: {name} (PURE PYTHON fallback)")
    return name
