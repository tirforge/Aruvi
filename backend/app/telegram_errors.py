r"""Classify Telegram RPC failures by type, never by English message text.

Kurigram raises one class per RPC error and exposes the number Telegram
embedded as ``.value`` (``errors.FloodWait(42).value == 42``). Matching on
``str(exc)`` instead is fragile: the wording can change with the error, the
server language, or a test double, and a naive ``re.search(r"\d+")`` grabs the
first number in the sentence — including unrelated ones.

Every Telegram error decision in the backend goes through these helpers.
"""

from __future__ import annotations

import re

from pyrogram import errors

_FLOOD_TYPES = (errors.FloodWait, errors.SlowmodeWait)

# A stale authorization key or file reference is fixed by rebuilding the
# client / re-fetching the message, so callers retry once with a fresh session.
_STALE_SESSION_TYPES = (
    errors.AuthKeyUnregistered,
    errors.AuthKeyInvalid,
    errors.AuthKeyDuplicated,
    errors.SessionRevoked,
    errors.LimitInvalid,
)
_STALE_SESSION_IDS = (
    "AUTH_KEY_UNREGISTERED",
    "AUTH_KEY_INVALID",
    "AUTH_KEY_DUPLICATED",
    "SESSION_REVOKED",
    "LIMIT_INVALID",
)

_FLOOD_ID_RE = re.compile(r"(?:FLOOD|SLOWMODE)_WAIT_(\d+)", re.IGNORECASE)
_FLOOD_TEXT_RE = re.compile(r"\bwait(?: of)? (\d+) ?s(?:econds?)?\b", re.IGNORECASE)


def flood_wait_seconds(exc: BaseException) -> int | None:
    """Seconds Telegram asks us to wait, or ``None`` when it is not a flood error.

    Prefers the typed exception's ``.value``; the text patterns are only a
    fallback for wrapped/foreign exceptions that lost their class.
    """
    if isinstance(exc, _FLOOD_TYPES):
        value = exc.value
        if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
            return value

    text = str(exc)
    match = _FLOOD_ID_RE.search(text) or _FLOOD_TEXT_RE.search(text)
    if match is None:
        return None
    try:
        return int(match.group(1))
    except (TypeError, ValueError):
        return None


def is_flood(exc: BaseException) -> bool:
    """True for any FLOOD_WAIT / SLOWMODE_WAIT (typed or wrapped)."""
    return isinstance(exc, _FLOOD_TYPES) or "FLOOD" in str(exc).upper()


def is_slowmode(exc: BaseException) -> bool:
    """True only for SlowmodeWait — a group restriction, not account flooding."""
    return isinstance(exc, errors.SlowmodeWait) or "SLOWMODE" in str(exc).upper()


def is_stale_session(exc: BaseException) -> bool:
    """True when retrying with a fresh client/session can fix the failure."""
    return isinstance(exc, _STALE_SESSION_TYPES) or any(
        token in str(exc) for token in _STALE_SESSION_IDS
    )


def is_auth_bytes_invalid(exc: BaseException) -> bool:
    """True for AUTH_BYTES_INVALID — poisoned cross-DC media session auth."""
    return isinstance(exc, errors.AuthBytesInvalid) or "AUTH_BYTES_INVALID" in str(exc)
