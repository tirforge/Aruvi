"""Byte-size environment variables, parsed by humanfriendly.

Operators write sizes the way they think about them — ``MEMORY=16Gi``,
``DISK_CACHE_MAX_BYTES=8G`` — not as raw integers. ``humanfriendly.parse_size``
knows every unit people actually type (``GiB``, ``Gi``, ``G``, ``MiB``, ``MB``,
``TB`` …), accepts a space between the number and the unit, and raises
``InvalidSize`` on junk instead of guessing.

``binary=True`` makes ``M``/``MB``/``MiB`` all mean 1024², matching how cgroup
limits are reported and what the previous hand-rolled parsers assumed.

Anything unset, empty, unparseable or non-positive becomes *default*. A bad
value is logged once per variable name, not once per status poll.
"""

from __future__ import annotations

import logging

from humanfriendly import InvalidSize, parse_size

_log = logging.getLogger("byte_sizes")

# Names already warned about. A module-level set, not a per-call flag: several
# call sites may read the same variable, and each should warn at most once.
_warned: set[str] = set()


def parse_byte_size(value, default: int, *, name: str = "value") -> int:
    """Return *value* in bytes, or *default* when it is unset or unusable.

    ``value`` may be ``None`` (variable unset), which silently yields *default*:
    the default is the documented behaviour, not an error.
    """
    if value is None or (isinstance(value, str) and not value.strip()):
        return default
    try:
        size = int(parse_size(value, binary=True))
    except (InvalidSize, TypeError, ValueError):
        size = 0
    if size > 0:
        return size
    if name not in _warned:
        _warned.add(name)
        _log.warning(
            "%s=%r is not a valid size — using %d bytes", name, value, default
        )
    return default
