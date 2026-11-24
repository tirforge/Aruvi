"""HTTP header parsing, delegated to Werkzeug instead of hand-rolled regexes.

Both parsers here guard behaviour that is easy to get subtly wrong:

* ``Range`` (RFC 9110 §14): suffix ranges, open-ended ranges, clamping,
  case-insensitive units, and unsatisfiable ranges. The old regex accepted
  ``bytes=0-10junk``, returned ``(start > end)`` for ``bytes=50-40``, and
  treated ``bytes=200-300`` on a 100-byte file as satisfiable.
* ``Accept-Encoding`` (RFC 9110 §12.5.3): q-values and the ``*`` wildcard. The
  old check ignored both, so ``br;q=0.1, gzip;q=1.0`` still chose br and
  ``gzip;q=0`` was treated as accepted.

Werkzeug is pure Python (no build step on the ARM VPS) and its HTTP parsing is
exercised by every Flask deployment.
"""

from __future__ import annotations

from collections.abc import Iterable

from werkzeug.datastructures import Accept
from werkzeug.http import parse_accept_header
from werkzeug.http import parse_range_header as _parse_range


def parse_byte_range(range_header: str | None, file_size: int) -> tuple[int, int] | None:
    """Parse a ``Range`` header into an inclusive ``(start, end)`` pair.

    Returns:
        ``(start, end)`` for a satisfiable single byte range,
        ``(0, -1)`` for an empty file with no Range header,
        ``None`` when the header is malformed, multipart, or unsatisfiable
        (the caller answers 416).
    """
    if not range_header:
        return (0, -1) if file_size == 0 else (0, file_size - 1)

    parsed = _parse_range(range_header)
    if parsed is None:
        return None

    span = parsed.range_for_length(file_size)
    if span is None:
        # Multipart, non-byte units, out-of-bounds start, or an empty file.
        return None

    start, stop = span  # stop is exclusive
    if stop <= start:
        return None
    return start, stop - 1


def pick_content_encoding(header: str, codings: Iterable[str]) -> str | None:
    """Return the best coding the client accepts, honouring q-values.

    ``codings`` is the server's preference order; ties go to the earlier entry.
    Returns ``None`` when the client accepts none of them (or sent no header).
    """
    candidates = [coding for coding in codings if coding]
    if not candidates:
        return None
    best = parse_accept_header(header or "", Accept).best_match(candidates)
    return best if best in candidates else None


def accepts_encoding(header: str, coding: str) -> bool:
    """True when the client explicitly (or via ``*``) accepts ``coding``."""
    return pick_content_encoding(header, (coding,)) == coding
