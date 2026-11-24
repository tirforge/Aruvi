"""HTTP header parsing and formatting, delegated to Werkzeug.

The parsers here guard behaviour that is easy to get subtly wrong:

* ``Range`` (RFC 9110 §14): suffix ranges, open-ended ranges, clamping,
  case-insensitive units, and unsatisfiable ranges. The old regex accepted
  ``bytes=0-10junk``, returned ``(start > end)`` for ``bytes=50-40``, and
  treated ``bytes=200-300`` on a 100-byte file as satisfiable.
* ``Accept-Encoding`` (RFC 9110 §12.5.3): q-values and the ``*`` wildcard. The
  old check ignored both, so ``br;q=0.1, gzip;q=1.0`` still chose br and
  ``gzip;q=0`` was treated as accepted.

and ``content_disposition`` emits the RFC 6266 form instead of a hand-written
f-string.

Werkzeug is pure Python (no build step on the ARM VPS) and its HTTP parsing is
exercised by every Flask deployment.
"""

from __future__ import annotations

from collections.abc import Iterable
from urllib.parse import quote

from werkzeug.datastructures import Accept
from werkzeug.http import dump_options_header
from werkzeug.http import parse_accept_header
from werkzeug.http import parse_range_header as _parse_range

from .utils import sanitize_filename


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


def content_disposition(disposition: str, filename: str) -> str:
    """Build a ``Content-Disposition`` value for *filename* (RFC 6266).

    Both parameters are emitted, as the RFC recommends:

    * ``filename="..."`` — an ASCII-only, path-safe name for clients that ignore
      the extended form. VLC and many TV players download under this name, and
      the old header omitted it entirely (they fell back to the URL path).
    * ``filename*=UTF-8''...`` — the real name, percent-encoded per RFC 5987.

    Werkzeug's ``dump_options_header`` owns the quoting of the plain parameter
    (embedded quotes/backslashes are escaped); ``quote(..., safe="")`` encodes
    the extended one, including ``/`` — the previous ``quote(name)`` left path
    separators raw.
    """
    ascii_name = filename.encode("ascii", "replace").decode("ascii")
    return dump_options_header(
        disposition,
        {
            "filename": sanitize_filename(ascii_name),
            "filename*": "UTF-8''" + quote(filename, safe=""),
        },
    )
