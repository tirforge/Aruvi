"""In-process wake-up for the login long-poll.

The bot handlers and the HTTP routers run in the same process, so when the bot
claims a code it can hand the wake-up straight to the waiting
``/auth/verify-code`` request instead of leaving it to re-query Postgres.

That matters here because the database is remote: this deployment's Supabase
pooler answers in ~400 ms, so a poll tick (SELECT + ROLLBACK + sleep) cost ~1 s
and the client could sit for several seconds after the bot already said
"Success!".

``signal()`` is called by the bot right AFTER the claim is committed, so the
woken request's next SELECT is guaranteed to see it. If the bot ever runs in a
separate process the event simply never fires and the caller's own timeout
still re-checks the database — nothing breaks, it just falls back to polling.
"""

import asyncio
import time

# How long a claim stays "fresh" for a request that registers after the bot
# already signalled. Codes expire in 10 minutes, so 2 minutes is plenty and
# keeps the dict from growing.
_MAX_AGE = 120.0

_waiters: dict[str, set[asyncio.Event]] = {}
_claimed: dict[str, float] = {}


def _prune() -> None:
    cutoff = time.monotonic() - _MAX_AGE
    for code in [c for c, t in _claimed.items() if t < cutoff]:
        _claimed.pop(code, None)


def register(code: str) -> asyncio.Event:
    """Return an event that fires when ``code`` is claimed.

    Pre-set if the claim already happened (the bot may win the race against the
    request that is about to start waiting).
    """
    _prune()
    event = asyncio.Event()
    if code in _claimed:
        event.set()
    _waiters.setdefault(code, set()).add(event)
    return event


def unregister(code: str, event: asyncio.Event) -> None:
    waiting = _waiters.get(code)
    if waiting is None:
        return
    waiting.discard(event)
    if not waiting:
        _waiters.pop(code, None)


def signal(code: str) -> None:
    """Wake every request waiting on ``code``. Call after the claim commits."""
    _prune()
    _claimed[code] = time.monotonic()
    for event in _waiters.pop(code, ()):
        event.set()
