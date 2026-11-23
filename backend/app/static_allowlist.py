"""Startup allowlist for SPA static files (path-traversal defense).

The map is built once at startup by walking ``app/static``:
relative URL path -> absolute file path. ``serve_spa`` only ever serves
files from this map, so the response file NEVER derives from user input —
traversal payloads (``..``, absolute paths, encoded tricks, symlink
escapes) simply miss the lookup and fall through to the SPA fallback.

Pure stdlib on purpose: unit tests import this without pulling in the
whole FastAPI app.
"""

# Transport encodings the frontend build emits next to each asset. Kept out
# of the allowlist so a client can never fetch the compressed bytes as if
# they were the asset (they're only reachable through the plain entry).
ENCODING_SUFFIXES = (".gz", ".br")


def build_static_allowlist(base: str = "app/static") -> dict:
    """Walk *base* and return {url-relative-path: absolute-file-path}.

    Precompressed siblings (``.gz``, ``.br``) are NOT keys — they are
    resolved from the allowlisted plain entry (``plain + ".gz"``), so they
    can't be addressed directly either.
    """
    import os

    allow: dict = {}
    base_abs = os.path.abspath(base)
    if not os.path.isdir(base_abs):
        return allow
    for root, _dirs, files in os.walk(base_abs):
        for name in files:
            if name.endswith(ENCODING_SUFFIXES):
                continue
            abs_path = os.path.join(root, name)
            # Never allowlist a symlink — FileResponse would follow it out
            # of base at serve time.
            if os.path.islink(abs_path):
                continue
            rel = os.path.relpath(abs_path, base_abs).replace(os.sep, "/")
            allow[rel] = abs_path
    return allow
