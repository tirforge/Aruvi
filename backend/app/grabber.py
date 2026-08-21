"""
Grab movies from auto-filter Telegram groups.
Phase 1: search -> return filtered options (<=15, 1GB-3GB)
Phase 2: grab selected option -> forward, DB record, stream URL
"""
import asyncio
import re
import logging
import os
from dataclasses import dataclass, field

from pyrogram import Client

from .database import async_session
from .models import User, File
from .config import get_settings
from .media_types import classify_file_type

_log = logging.getLogger(__name__)

import time  # noqa: E402

_SIZE_RE = re.compile(r'(\d+\.?\d*)\s*(GB|MB)', re.IGNORECASE)
_DEEP_LINK_RE = re.compile(r'[?&]start=([^&]+)')
_DEEP_LINK_BOT_RE = re.compile(r'https?://t\.me/([A-Za-z0-9_]{3,64})\?[^&\s]*start=', re.IGNORECASE)


class _GrabError(Exception):
    """User-visible grab failure (clear message, not a server bug)."""


class _SlowError(Exception):
    """Search aborted because the account is slowmode/flood-limited.

    Distinct from a dead group: the bot may be fine, we just can't post the
    query within the search budget. Not counted as a dead-group strike.
    """


_GROUP_CHAT_ID_CACHE: dict[str, int] = {}

_BOT_USER_CACHE: dict[str, tuple[float, object]] = {}
_BOT_USER_CACHE_TTL = 3600  # 1h — resolves the bot once per hour, not per grab
_BOT_USER_CACHE_MAX = 200


MAX_OPTIONS = 30  # merged across channels (final response cap)
MAX_PER_CHANNEL = 20  # per-channel pagination cap
MAX_PAGES = 10  # safety cap on pages walked per message
MIN_PAGE_INTERVAL = 0.6  # min wait between next-page clicks (avoid flood/race)
MAX_SIZE = int(2.5 * 1024**3)  # 2.5 GB
MIN_SIZE = int(700 * 1024**2)  # 700 MB

# Cold-search tuning. Auto-filter bots enforce ~3s between GetBotCallbackAnswer
# calls per user, so page clicks are paced (not flood-retried) and page-walks of
# different bots run in parallel instead of being serialized behind one lock.
SEARCH_REPLY_WINDOW = 8  # seconds to wait for a group's bot to answer a query
SEARCH_GROUP_TIMEOUT = 20  # hard cap per group (reply + page-walk)
SEARCH_GROUP_FAST_TIMEOUT = 8  # per-group cap once a group is suspect (dead/slow)
PAGE1_MIN_OPTIONS = 5  # if page 1 has at least this many options, skip the slow page-walk
EARLY_RETURN_OPTIONS = 8  # return as soon as this many options are merged (fast group wins)
_BOT_CLICK_SPACING = 3.2  # min gap between callback clicks on the same bot
GROUP_COOLDOWN_NONE_TTL = 45  # skip groups that returned nothing (short)
GROUP_COOLDOWN_TIMEOUT_TTL = 120  # skip groups that hard-timed out (long)
GROUP_DEAD_COOLDOWN_TTL = 300  # long skip after repeated failures (treat as dead)
SUSPECT_STRIKES = 2  # consecutive failures before a group is treated as dead/suspect
_GROUP_COOLDOWN: dict[str, float] = {}
_GROUP_STRIKES: dict[str, int] = {}

# Global lock: serialize live searches so concurrent users' queries don't all
# fire into the groups at once and compound Telegram's account-level flood.
_search_lock = asyncio.Lock()

# Per-bot pacing + locks so different groups' page-walks interleave instead of
# queueing behind a single global lock (the flood is per-bot, not per-connection).
_last_click_at: dict[int, float] = {}
_bot_flood_until: dict[int, float] = {}  # bot-id -> time() when flood wait expires
_bot_click_locks: dict[int, asyncio.Lock] = {}
_bot_click_locks_guard = asyncio.Lock()


# ---------------------------------------------------------------------------
# Ivy pool — per-session-string slot pool for concurrent operations
# ---------------------------------------------------------------------------

@dataclass
class _IvySlot:
    session: str
    client: object | None = None
    start_lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    active: int = 0  # concurrent users of this slot's client
    needs_rebuild: bool = False  # client broken; rebuild once idle


class _IvyPool:
    """
    Pool of Ivy slots. Each slot holds one session string and a persistent
    client that is started lazily and reused across calls.

    AUTH_KEY_DUPLICATED happens when two *separate* clients start with the
    same session string at the same time, so client creation is guarded by a
    per-slot lock (only one start per session string). Once started, Pyrogram
    multiplexes concurrent invokes over the single connection.

    A pool-level semaphore bounds total concurrency to 3 so that searches on
    multiple groups run in parallel (each group wait happens concurrently),
    while keeping the single connection under control.

    Configure session strings via GRAB_SESSION_STRINGS (comma-separated)
    in .env. Falls back to GRAB_SESSION_STRING, then
    TELEGRAM_BOT_SESSION_STRINGS.
    """
    _slots: list[_IvySlot] = []
    _init_lock = asyncio.Lock()
    _initialized = False
    _round_robin = 0
    _sem: asyncio.Semaphore | None = None

    @classmethod
    async def _ensure(cls):
        if cls._initialized:
            return
        async with cls._init_lock:
            if cls._initialized:
                return
            sessions = _collect_sessions()
            if not sessions:
                raise RuntimeError("no Ivy session strings available")
            cls._slots = [_IvySlot(session=s) for s in sessions]
            cls._sem = asyncio.Semaphore(3)
            cls._initialized = True
            _log.info("grabber: IvyPool ready with %d slot(s)", len(sessions))

    @classmethod
    async def execute(cls, fn):
        """Run fn on a shared Ivy client, bounded by pool concurrency."""
        await cls._ensure()
        async with cls._sem:
            idx = cls._round_robin % len(cls._slots)
            cls._round_robin += 1
            slot = cls._slots[idx]
            # Per-slot lock: never start two clients from the same session
            # string concurrently (would trigger AUTH_KEY_DUPLICATED), and
            # never tear a client down while other callers still hold it.
            async with slot.start_lock:
                if slot.client is None or slot.needs_rebuild:
                    if slot.active == 0:
                        if slot.client is not None:
                            await _stop_client_safe(slot.client)
                            slot.client = None
                        slot.client = await _start_client(slot.session)
                        slot.needs_rebuild = False
                slot.active += 1
            try:
                return await fn(slot.client)
            except (_GrabError, _SlowError):
                # User-visible / transient failures (channel join pending,
                # account slowmode-limited) — the client is fine, don't drop it.
                raise
            except Exception:
                # The client may be broken — don't stop it while others still
                # hold it; flag it for rebuild by the last active caller.
                slot.needs_rebuild = True
                raise
            finally:
                async with slot.start_lock:
                    slot.active -= 1
                    if slot.active == 0 and slot.needs_rebuild and slot.client is not None:
                        await _stop_client_safe(slot.client)
                        slot.client = None
                        slot.needs_rebuild = False


_ivy_pool = _IvyPool()


def _collect_sessions() -> list[str]:
    """Collect all available session strings (preferred first)."""
    sessions: list[str] = []
    try:
        s = get_settings()
        # 1. GRAB_SESSION_STRINGS (plural, comma-separated)
        if s.grab_session_strings:
            sessions.extend(s.grab_session_strings)
        # 2. GRAB_SESSION_STRING (single, legacy)
        if not sessions and s.grab_session_string:
            sessions.append(s.grab_session_string)
        # 3. TELEGRAM_BOT_SESSION_STRINGS
        if not sessions and s.telegram_bot_session_strings:
            sessions.extend(s.telegram_bot_session_strings)
    except Exception:
        pass
    # 4. Env var fallback
    if not sessions:
        env = os.environ.get("TELEGRAM_BOT_SESSION_STRINGS", "")
        sessions = [ss.strip() for ss in env.split(",") if ss.strip()]
    if sessions:
        _log.info("grabber: collected %d session string(s)", len(sessions))
    return sessions


async def _start_client(session_str: str) -> Client:
    """Create and start a Pyrogram Client with the given session string."""
    t0 = time.monotonic()
    if not session_str:
        raise RuntimeError("empty Ivy session string")
    settings = get_settings()
    ivy = Client(
        "ivy_grab", session_string=session_str, in_memory=True,
        api_id=settings.telegram_api_id, api_hash=settings.telegram_api_hash,
        no_updates=True, sleep_threshold=30,
    )
    _log.info("grabber: ivy client created, starting...")
    try:
        await asyncio.wait_for(ivy.start(), timeout=30)
        _log.info("grabber: ivy client started in %.1fs", time.monotonic() - t0)
    except asyncio.TimeoutError:
        try:
            await ivy.stop()
        except Exception:
            pass
        raise RuntimeError("Ivy client start timed out")
    return ivy


async def _stop_client_safe(client) -> None:
    """Stop a client that may already be stopped/disconnected."""
    try:
        if client is not None:
            await client.stop()
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _send_with_retry(client, chat_id, text, max_retries=5, deadline=None):
    for attempt in range(max_retries):
        if deadline is not None and asyncio.get_event_loop().time() >= deadline:
            raise _SlowError("search send budget exhausted")
        try:
            return await client.send_message(chat_id, text)
        except Exception as e:
            wait_s = _flood_seconds(e)
            if 'SLOWMODE' in str(e) and wait_s:
                if attempt >= max_retries - 1:
                    raise _SlowError(
                        f"send still slowmode-limited after {max_retries} attempts ({wait_s}s)"
                    ) from e
                wait = wait_s + 2
                if deadline is not None:
                    left = deadline - asyncio.get_event_loop().time()
                    if wait >= left:
                        # The slowmode wait can't fit in the search budget. Bail
                        # immediately so the group gets a short cooldown instead
                        # of burning the whole budget and timing out — which was
                        # counting a healthy-but-limited group as "dead".
                        raise _SlowError(
                            f"slowmode wait {wait_s}s exceeds search budget ({left:.1f}s left)"
                        ) from e
                _log.warning("grabber: slowmode on attempt %d/%d, waiting %ds", attempt + 1, max_retries, wait)
                await asyncio.sleep(wait)
            else:
                raise


async def _collect_bot_replies(
    ivy: Client,
    chat_id: int,
    sent: object,
    bot_user: object | None,
    seconds: int = 15,
) -> list[object]:
    """Collect bot reply messages after a search post.

    A message is accepted when it either:
      1. is a direct reply to ``sent`` (robust across bot switches), or
      2. comes from the configured ``bot_user`` (or any bot when auto-detecting).

    Direct replies are preferred so concurrent searches by other users in busy
    groups don't pollute our results, and a group that swapped its bot still
    works because we don't require the configured identity for direct replies.
    """
    collected: list[object] = []
    direct: list[object] = []
    seen: set[int] = set()
    for _ in range(seconds):
        try:
            history = [m async for m in ivy.get_chat_history(chat_id, limit=20)]
        except Exception as e:
            _log.warning("grabber: history fetch failed in %s: %s", chat_id, e)
            await asyncio.sleep(1)
            continue
        for msg in history:
            if msg.id <= sent.id or not msg.reply_markup or not msg.from_user:
                continue
            if msg.id in seen:
                continue
            seen.add(msg.id)
            is_direct = getattr(msg, "reply_to_message_id", None) == sent.id
            bot_ok = bot_user is None or msg.from_user.id == bot_user.id
            if is_direct:
                direct.append(msg)
            elif bot_ok:
                # Non-direct bot posts may belong to a *concurrent* search by
                # another user in a busy shared group. Only use them as a
                # fallback, and keep scanning the window so our own direct
                # reply still gets a chance instead of breaking early.
                collected.append(msg)
        if direct:
            break
        await asyncio.sleep(1)
    if direct:
        return direct
    return collected


_NEXT_KEYWORDS = ("next", "»", "➡", ">", "forward", "more", "⬅", "«", "<", "back", "prev")
_PAGE_RE = re.compile(r"(next|back|prev|page|»|«|➡|⬅|>|<)", re.IGNORECASE)


def _bot_key_from_msg(msg) -> int:
    """Return the bot user id that authored a result message (0 if unknown)."""
    fu = getattr(msg, "from_user", None)
    return getattr(fu, "id", None) or 0


async def _bot_click_lock(bot_id: int) -> asyncio.Lock:
    """Per-bot lock — different bots' callback clicks are never serialized."""
    async with _bot_click_locks_guard:
        lock = _bot_click_locks.get(bot_id)
        if lock is None:
            lock = asyncio.Lock()
            _bot_click_locks[bot_id] = lock
        return lock


def _flood_seconds(e) -> int | None:
    """Extract the required wait from a flood/slowmode error, if any.

    Handles the real error shapes: "A wait of 10 seconds is required",
    "FLOOD_WAIT_10", "SLOWMODE_WAIT_10", "wait_10".
    """
    msg = str(e)
    m = re.search(r"\bwait(?: of)? (\d+) (?:seconds?|s)\b", msg, re.IGNORECASE)
    if not m:
        m = re.search(r"(?:FLOOD|SLOWMODE)_WAIT_(\d+)", msg, re.IGNORECASE)
    if not m:
        m = re.search(r"\bwait[_\s]*(\d+)\b", msg, re.IGNORECASE)
    if not m:
        return None
    try:
        return int(m.group(1))
    except ValueError:
        return None


async def _pace_click(bot_id: int) -> None:
    """Sleep until the configured spacing since this bot's last click has passed.

    Auto-filter bots answer GetBotCallbackAnswer at ~one call per 3s per user.
    Clicking faster triggers a FLOOD_WAIT(3) retry (extra RPC + log noise, and a
    risk of the retry timing out into a 5s backoff). Pacing up front makes every
    click succeed on the first attempt, and lets page-walks of different bots
    overlap because the flood is per-bot, not per-connection. When a flood is
    observed anyway, ``_bot_flood_until`` raises the pace until it expires so
    the throttle is never tripped twice.
    """
    if not bot_id:
        return
    loop = asyncio.get_event_loop()
    now = loop.time()
    wait_until = _last_click_at.get(bot_id, 0.0) + _BOT_CLICK_SPACING
    flooded = _bot_flood_until.get(bot_id, 0.0)
    if flooded > wait_until:
        wait_until = flooded
    wait = wait_until - now
    if wait > 0:
        await asyncio.sleep(wait)


def _note_click(bot_id: int) -> None:
    if bot_id:
        _last_click_at[bot_id] = asyncio.get_event_loop().time()


def _is_nav_button(text: str) -> bool:
    """Heuristic: button that navigates pages rather than a file option.

    File buttons carry a size in brackets (e.g. "[2.06 GB] ..."), nav buttons
    usually don't. A short text with a page/arrow keyword is treated as nav.
    """
    t = text.strip()
    if not t or len(t) > 20:
        return False
    return bool(_PAGE_RE.search(t))


def _find_next_button(msg) -> object | None:
    """Return the button that advances to the next page, or None."""
    if not msg or not msg.reply_markup or not msg.reply_markup.inline_keyboard:
        return None
    for row in msg.reply_markup.inline_keyboard:
        for btn in row:
            t = (btn.text or "").strip().lower()
            if not t or len(t) > 20:
                continue
            if any(k in t for k in ("next", "»", "➡", ">", "forward", "more")):
                return btn
    return None


def _find_prev_button(msg) -> object | None:
    """Return the button that goes to the previous page, or None."""
    if not msg or not msg.reply_markup or not msg.reply_markup.inline_keyboard:
        return None
    for row in msg.reply_markup.inline_keyboard:
        for btn in row:
            t = (btn.text or "").strip().lower()
            if not t or len(t) > 20:
                continue
            if any(k in t for k in ("prev", "back", "«", "<", "⬅")):
                return btn
    return None


async def _page_step(ivy: Client, msg, find_fn, timeout: float = 8.0) -> object | None:
    """Click a page-nav button and wait for the edited message.

    Auto-filter bots typically edit the SAME message in place when paging, so
    we capture the current message id and poll until its buttons change.
    ``find_fn`` selects the nav button to click (next or prev). Returns the
    updated message or None if there is no such button / it never changed
    (which can be a race or the edge of the menu).

    Clicks are paced per bot (>=_BOT_CLICK_SPACING between them) so the bot's
    ``GetBotCallbackAnswer`` throttle is never tripped, and locked per bot so
    page-walks of different bots overlap instead of queueing behind one global
    lock. Remaining failures are retried with backoff.
    """
    if not msg:
        return None
    nav_btn = find_fn(msg)
    if nav_btn is None:
        return None
    msg_id = msg.id
    before = [(b.text or "") for r in (msg.reply_markup.inline_keyboard or []) for b in r]
    bot_id = _bot_key_from_msg(msg)

    clicked = False
    for attempt in range(1, 4):
        try:
            lock = await _bot_click_lock(bot_id)
            async with lock:
                await _pace_click(bot_id)
                await msg.click(nav_btn.text, timeout=10)
                _note_click(bot_id)
            clicked = True
            break
        except asyncio.CancelledError:
            raise
        except Exception as e:
            # The invoke may have gone through server-side even though the
            # response was lost. Re-fetch the message: if the buttons changed,
            # the click landed — return it rather than retrying (a retry would
            # double-advance past the next page).
            try:
                fresh = await ivy.get_messages(msg.chat.id, msg.id)
                if fresh and fresh.reply_markup and fresh.reply_markup.inline_keyboard:
                    after = [(b.text or "") for r in fresh.reply_markup.inline_keyboard for b in r]
                    if after and after != before:
                        return fresh
            except Exception:
                pass
            flood = _flood_seconds(e)
            if flood is not None:
                # The bot is flood-limited right now — remember the wait so
                # every subsequent click paces above it instead of tripping
                # the same throttle again.
                _bot_flood_until[bot_id] = max(
                    _bot_flood_until.get(bot_id, 0.0),
                    asyncio.get_event_loop().time() + flood + 0.5,
                )
                backoff = flood + 0.5
            else:
                backoff = 2 + attempt
            _log.warning(
                "grabber: page-nav click attempt %d/3 failed (%s); retrying in %.1fs",
                attempt, e, backoff,
            )
            await asyncio.sleep(backoff)
    if not clicked:
        _log.warning("grabber: page-nav click failed: %s", nav_btn.text)
        return None

    deadline = asyncio.get_event_loop().time() + timeout
    last = msg
    while asyncio.get_event_loop().time() < deadline:
        await asyncio.sleep(0.5)
        try:
            last = await ivy.get_messages(msg.chat.id, msg_id)
        except Exception:
            continue
        if last and last.reply_markup and last.reply_markup.inline_keyboard:
            after = [(b.text or "") for r in last.reply_markup.inline_keyboard for b in r]
            if after and after != before:
                return last
    return None


async def _advance_page(ivy: Client, msg, timeout: float = 8.0) -> object | None:
    """Click the next-page button and wait for the edited message."""
    return await _page_step(ivy, msg, _find_next_button, timeout)


async def _rewind_page(ivy: Client, msg, timeout: float = 8.0) -> object | None:
    """Click the previous-page button and wait for the edited message."""
    return await _page_step(ivy, msg, _find_prev_button, timeout)


async def _rewind_to_first(ivy: Client, msg) -> object | None:
    """Navigate back to page 1 of the inline menu (best-effort).

    Returns the message on page 1, or None if it could not be rewound (no
    prev button exists — some bots only page forward).
    """
    if not msg:
        return None
    for _ in range(MAX_PAGES):
        if _find_prev_button(msg) is None:
            return msg
        before = [(b.text or "") for r in (msg.reply_markup.inline_keyboard or []) for b in r]
        rewound = await _rewind_page(ivy, msg)
        if rewound is None:
            return msg
        after = [(b.text or "") for r in (rewound.reply_markup.inline_keyboard or []) for b in r]
        if after == before:
            return msg
        msg = rewound
    return msg


async def _rewind_to_first_bg(chat_id: int, msg_id: int) -> None:
    """Best-effort rewind of an inline menu back to page 1, off the search path.

    Runs through the client pool so it is serialized against other RPCs, and
    never raises (so the pool client is not dropped). If it has not finished by
    the time the user picks a result, ``grab_selected`` rewinds the message
    itself (or falls back to a fresh query).
    """
    async def _run(ivy: Client):
        try:
            msg = await ivy.get_messages(chat_id, msg_id)
        except Exception:
            return
        if msg is None:
            return
        try:
            await _rewind_to_first(ivy, msg)
        except Exception as e:
            _log.warning("grabber: background rewind of msg %s failed: %s", msg_id, e)

    try:
        await _ivy_pool.execute(_run)
    except Exception as e:
        _log.warning("grabber: background rewind task failed: %s", e)


def _parse_size(text: str) -> int | None:
    m = _SIZE_RE.search(text)
    if not m:
        return None
    val = float(m.group(1))
    unit = m.group(2).upper()
    if unit == "GB":
        return int(val * 1024**3)
    return int(val * 1024**2)


_TITLE_STOPWORDS = {
    "the", "a", "an", "and", "with", "of", "in", "on", "for", "vs", "part",
    "movie", "film", "english", "hindi", "tamil", "telugu", "malayalam",
    "korean", "japanese", "chinese", "multi", "audio", "dual", "dubbed",
    "ac3", "dts", "dd", "web", "hdrip", "bdrip", "bluray", "brrip", "hdtv",
    "webrip", "webdl", "x264", "x265", "h264", "h265", "hevc",
    "aac", "mp4", "mkv", "avi", "264", "265", "org", "hd",
}
_RES_RE = re.compile(r"\b(4k|\d{3,4}p)\b", re.IGNORECASE)


def _title_tokens(name: str) -> set[str]:
    """Meaningful title words (>=4 letters, excluding stopwords/quality tags)."""
    tokens = set()
    for m in re.finditer(r"[A-Za-z]{4,}", name or ""):
        t = m.group(0).lower()
        if t in _TITLE_STOPWORDS:
            continue
        tokens.add(t)
    return tokens


def _res_token(name: str) -> str:
    m = _RES_RE.search(name or "")
    return m.group(1).lower() if m else ""


def _label_file_check(label: str, file_name: str) -> tuple[bool, str]:
    """Compare the selected button label with the delivered file name.

    Auto-filter bots occasionally link a button to a *different* file than the
    label describes (wrong movie, or a worse/higher resolution). Returns
    ``(ok, warning)``: ``ok=False`` means the bot delivered a clearly different
    movie and the grab should be aborted; ``warning`` carries soft mismatches
    (e.g. resolution) that are safe to show without failing the grab.
    """
    lt = _title_tokens(label)
    ft = _title_tokens(file_name)
    if lt and ft and not (lt & ft):
        return False, (
            f"Delivered file doesn't match the selected option "
            f"({label!r} -> {file_name!r}). The bot may have linked a different movie."
        )
    warnings = []
    lr = _res_token(label)
    fr = _res_token(file_name)
    if lr and fr and lr != fr:
        warnings.append(f"Resolution differs: selected {lr}, delivered {fr}")
    return True, "; ".join(warnings)


async def _resolve_group(ivy: Client, ref: str) -> int:
    """Join via invite link if needed, return resolved chat_id."""
    ref = ref.strip().lstrip("@")
    if not ref:
        raise ValueError("empty group reference")
    if ref.lstrip("-").isdigit():
        return int(ref)
    cached = _GROUP_CHAT_ID_CACHE.get(ref)
    if cached is not None:
        return cached
    invite_hash = None
    if ref.startswith("+"):
        invite_hash = ref.lstrip("+")
    elif ref.startswith("joinchat/"):
        invite_hash = ref.replace("joinchat/", "")
    elif "t.me/+" in ref:
        invite_hash = ref.split("t.me/+")[-1].split("?")[0].split("/")[0]
    if invite_hash:
        res = await ivy.join_chat(f"https://t.me/+{invite_hash}")
        chat_id = getattr(res, "id", None)
        if chat_id is None:
            # Private invite that requires admin approval (ChatJoinResultRequestSent)
            raise ValueError(f"group invite +{invite_hash} requires admin approval (join request sent)")
        _log.info("grabber: joined group via invite link, chat_id=%s", chat_id)
        _GROUP_CHAT_ID_CACHE[ref] = chat_id
        return chat_id
    chat = await ivy.get_chat(ref)
    try:
        await ivy.join_chat(ref)
        _log.info("grabber: joined group @%s", ref)
    except Exception:
        pass  # already a member, private, or restricted — send will surface issues
    _GROUP_CHAT_ID_CACHE[ref] = chat.id
    return chat.id


async def _resolve_entity(ivy: Client, ref: str) -> str:
    """Join the channel/group referenced by ref.

    Returns a status string: 'joined' | 'already' | 'requested' | 'failed' | ''.
    'requested' means the invite needs admin approval — the join request was
    sent but membership is pending, so the bot will not deliver the file.
    """
    ref = ref.strip().lstrip("@")
    if not ref:
        return ""

    def _join_result(res) -> str:
        name = type(res).__name__
        if name == "ChatJoinResultRequestSent":
            return "requested"
        if name == "ChatJoinResultAlreadyMember":
            return "already"
        return "joined"

    def _already(e: Exception) -> bool:
        msg = str(e).lower()
        return "already" in msg or "participant" in msg

    if ref.startswith("+") or ref.startswith("joinchat/"):
        ref = ref.lstrip("+").replace("joinchat/", "")
        try:
            res = await ivy.join_chat(f"https://t.me/+{ref}")
        except Exception as e:
            if _already(e):
                return "already"
            _log.warning("grabber: join invite +%s failed: %s", ref, e)
            return "failed"
        status = _join_result(res)
        if status == "requested":
            _log.warning("grabber: join request sent for +%s — awaiting admin approval", ref)
        elif status == "joined":
            _log.info("grabber: joined via invite link +%s", ref)
        return status

    try:
        res = await ivy.join_chat(ref)
    except Exception as e:
        if _already(e):
            return "already"
        _log.warning("grabber: join @%s failed: %s", ref, e)
        return "failed"
    status = _join_result(res)
    if status == "requested":
        _log.warning("grabber: join request sent for @%s — awaiting admin approval", ref)
    elif status == "joined":
        _log.info("grabber: joined @%s", ref)
    return status


_JOIN_KEYWORDS = ["join", "subscribe", "channel", "force", "follow"]
_NON_JOINABLE_TME = {"share", "telegram", "addtheme", "proxy", "bg", "s"}


def _tme_entity_from_url(url: str) -> str:
    """Normalize a t.me URL to a joinable entity ref (+hash | joinchat/hash | username)."""
    if not url:
        return ""
    if url.startswith("t.me/"):
        url = "https://" + url
    u = url.replace("https://t.me/", "").replace("http://t.me/", "").split("?")[0]
    if u.startswith("joinchat/"):
        return "joinchat/" + u[len("joinchat/"):]
    u = u.split("/")[0]
    if u.startswith("+"):
        return "+" + u[1:]
    if u in _NON_JOINABLE_TME:
        return ""
    return u


def _join_targets_from_message(msg) -> set:
    """Every channel/group referenced by a force-sub message, as entity refs."""
    targets = set()
    text = (msg.text or msg.caption or "")
    for ref in re.findall(r"@(\w+)", text):
        targets.add(ref)
    if msg.reply_markup:
        for row in msg.reply_markup.inline_keyboard:
            for btn in row:
                url = (getattr(btn, "url", None) or "")
                if url.startswith("t.me"):
                    url = "https://" + url
                ref = _tme_entity_from_url(url)
                if ref:
                    targets.add(ref)
    return targets


def _is_join_required(msg) -> bool:
    """True when the bot is gating a file behind joining a channel/group."""
    text = (msg.text or msg.caption or "").lower()
    if any(kw in text for kw in _JOIN_KEYWORDS):
        return True
    if msg.reply_markup:
        for row in msg.reply_markup.inline_keyboard:
            for btn in row:
                url = (getattr(btn, "url", None) or "")
                if url.startswith("t.me"):
                    url = "https://" + url
                if _tme_entity_from_url(url):
                    return True
    return False


async def _get_bot_user(ivy: Client, username: str):
    """Resolve a bot username, cached for _BOT_USER_CACHE_TTL seconds.

    Only the resolved User object's attributes (id, username) are ever read,
    so reusing the cached object across calls is safe. The search phase resolves
    the bot already; grab re-uses that instead of paying a second RPC.
    """
    if not username:
        return None
    now = asyncio.get_event_loop().time()
    cached = _BOT_USER_CACHE.get(username)
    if cached and now - cached[0] < _BOT_USER_CACHE_TTL:
        return cached[1]
    try:
        bot_user = await ivy.get_users(username)
    except Exception as e:
        _log.warning("grabber: get_users(%s) failed: %s — will auto-detect from replies", username, e)
        return None
    _BOT_USER_CACHE[username] = (now, bot_user)
    # Evict expired entries and cap size — keys can come from arbitrary
    # t.me/<name>?start= URLs inside bot messages, so the dict must not be
    # allowed to grow without bound.
    if len(_BOT_USER_CACHE) > _BOT_USER_CACHE_MAX:
        for k in [k for k, (ts, _) in _BOT_USER_CACHE.items() if now - ts >= _BOT_USER_CACHE_TTL]:
            _BOT_USER_CACHE.pop(k, None)
        while len(_BOT_USER_CACHE) > _BOT_USER_CACHE_MAX:
            _BOT_USER_CACHE.pop(next(iter(_BOT_USER_CACHE)))
    return bot_user


async def _wait_for_file_auto_join(
    ivy: Client,
    chat_id: int,
    start_command: str,
    max_attempts: int = 2,
) -> object | None:
    from pyrogram.enums import MessageMediaType

    # Cap flood-wait sleeps: without a deadline one long FLOOD_WAIT pins an
    # _ivy_pool slot (and the HTTP request) for minutes.
    send_deadline = asyncio.get_event_loop().time() + 60
    for attempt in range(max_attempts):
        await _send_with_retry(ivy, chat_id, start_command, deadline=send_deadline)

        file_msg = None
        pending_approval = False
        re_start_after_join = True
        for _ in range(15):
            await asyncio.sleep(1)
            found_force_sub = False
            try:
                async for msg in ivy.get_chat_history(chat_id, limit=5):
                    if msg.media and msg.media in (
                        MessageMediaType.VIDEO, MessageMediaType.DOCUMENT,
                        MessageMediaType.AUDIO, MessageMediaType.PHOTO,
                    ):
                        file_msg = msg
                        break
                    if _is_join_required(msg):
                        # Auto-join every channel/group the bot wants, then send
                        # /start once more so the bot re-checks membership.
                        for ref in _join_targets_from_message(msg):
                            status = await _resolve_entity(ivy, ref)
                            if status == "requested":
                                pending_approval = True
                        if re_start_after_join:
                            await _send_with_retry(ivy, chat_id, start_command, deadline=send_deadline)
                            re_start_after_join = False
                        found_force_sub = True
                        break
            except Exception:
                pass
            if file_msg:
                return file_msg
            if pending_approval:
                # A join request is awaiting admin approval — the bot can't see
                # membership yet, so further polling cannot deliver the file.
                break
            if found_force_sub:
                await asyncio.sleep(2)
                continue

        if pending_approval:
            raise _GrabError(
                "File requires joining a channel that needs admin approval "
                "(join request sent, pending). Approve it in Telegram, or pick another option."
            )

        if attempt < max_attempts - 1:
            await asyncio.sleep(2)

    return None


# ---------------------------------------------------------------------------
# Phase 1: search
# ---------------------------------------------------------------------------

async def search_results(
    query: str,
    group_username: str,
    bot_username: str,
    timeout: float = SEARCH_GROUP_TIMEOUT,
) -> dict | None:
    """
    Search in group, collect file buttons from bot response.

    Returns dict with keys ``results`` (list[dict]), ``chat_id`` (int),
    ``bot_user_id`` (int | None), or ``None`` on failure.
    Each result: {label, row, col, msg_id, file_name, file_size}
    Raises ``_SlowError`` when the account is slowmode-limited and the wait
    can't fit inside ``timeout``.
    """
    if not query.strip() or len(query.strip()) < 2:
        return None

    if not bot_username:
        _log.warning("grabber: GRAB_BOT_USERNAME not set — accepting any bot's reply")

    async def _run(ivy: Client):
        _t = time.monotonic()
        deadline = asyncio.get_event_loop().time() + timeout
        bot_user = await _get_bot_user(ivy, bot_username)
        chat_id = await _resolve_group(ivy, group_username)

        # 1. Post search query in group
        try:
            sent = await _send_with_retry(ivy, chat_id, query, deadline=deadline)
        except _SlowError:
            raise
        except Exception as e:
            _log.warning("grabber: search send failed in %s: %s", group_username, e)
            return None

        # 2. Wait for bot response(s) with buttons
        result_msgs = await _collect_bot_replies(ivy, chat_id, sent, bot_user, seconds=SEARCH_REPLY_WINDOW)
        _log.info("grabber: %s search replied in %.1fs (%d msg(s))", group_username, time.monotonic() - _t, len(result_msgs))
        if bot_user is None and result_msgs:
            bot_user = result_msgs[0].from_user

        # Cleanup search message
        try:
            await ivy.delete_messages(chat_id, sent.id)
        except Exception:
            pass

        if not result_msgs:
            return None

        # 3. Collect buttons across pages (deduplicated, capped per channel).
        # Page-walking is expensive: the click itself is fast, but the bot then
        # takes several seconds to re-render the message, so every extra page
        # costs ~8s. Page 1 is already thick (10-12 options), so only walk when
        # page 1 is thin — common movies get a fast page-1-only result.
        seen = set()
        options = []
        for res_msg in result_msgs:
            page_msg = res_msg
            for _page in range(2):  # page 1 + at most one more page
                if len(options) >= MAX_PER_CHANNEL:
                    break
                if not page_msg or not page_msg.reply_markup or not page_msg.reply_markup.inline_keyboard:
                    break
                for row_idx, row in enumerate(page_msg.reply_markup.inline_keyboard):
                    for col_idx, btn in enumerate(row):
                        text = btn.text
                        if _is_nav_button(text):
                            continue

                        if text in seen:
                            continue
                        seen.add(text)

                        if "hevc" in text.lower():
                            continue

                        parsed_size = _parse_size(text)
                        if parsed_size is None or parsed_size < MIN_SIZE or parsed_size > MAX_SIZE:
                            continue

                        if parsed_size:
                            sz = f"{parsed_size // 1048576}MB" if parsed_size < 1024**3 else f"{parsed_size / 1024**3:.1f}GB"
                            label = f"[{sz}] {text[:50]}"
                        else:
                            label = text[:60]
                        options.append({
                            "label": label[:60],
                            "row": row_idx,
                            "col": col_idx,
                            "msg_id": page_msg.id,
                            "depth": _page,
                            "file_name": text[:200],
                            "file_size": parsed_size or 0,
                        })
                        if len(options) >= MAX_PER_CHANNEL:
                            break
                    if len(options) >= MAX_PER_CHANNEL:
                        break
                if len(options) >= MAX_PER_CHANNEL:
                    break
                # Only advance to the next page when page 1 came up thin.
                if len(options) >= PAGE1_MIN_OPTIONS:
                    break
                page_msg = await _advance_page(ivy, page_msg)
                if page_msg is None:
                    break
            # Restore the shared message to page 1 so grab_selected can reuse
            # it (no second query + slowmode wait). Done in the background so
            # the search response is not held up by rewind clicks; grab_selected
            # verifies page 1 itself and falls back to a fresh query if the
            # rewind has not finished in time.
            if page_msg is not None:
                asyncio.create_task(_rewind_to_first_bg(page_msg.chat.id, page_msg.id))

        return {
            "results": options,
            "chat_id": chat_id,
            "bot_user_id": bot_user.id if bot_user else None,
        }

    try:
        return await _ivy_pool.execute(_run)
    except _SlowError:
        raise
    except RuntimeError as e:
        _log.error("grabber: %s", e)
        return None
    except Exception as e:
        _log.exception("grabber: unexpected search error")
        return None


def _group_in_cooldown(group: str) -> bool:
    return time.monotonic() < _GROUP_COOLDOWN.get(group, 0.0)


def _put_group_in_cooldown(group: str, ttl: float) -> None:
    _GROUP_COOLDOWN[group] = time.monotonic() + ttl


def _clear_group_cooldown(group: str) -> None:
    _GROUP_COOLDOWN.pop(group, None)


def _group_is_suspect(group: str) -> bool:
    """A group is suspect after repeated failures — dead bots get a short cap."""
    return _GROUP_STRIKES.get(group, 0) >= SUSPECT_STRIKES


def _mark_group_result(group: str, ok: bool) -> None:
    """Track consecutive per-group failures; escalate cooldowns for dead bots."""
    if ok:
        _GROUP_STRIKES.pop(group, None)
        return
    n = _GROUP_STRIKES.get(group, 0) + 1
    _GROUP_STRIKES[group] = n
    if n >= 3:
        _log.warning("grabber: %s failed %d times in a row — treating as dead (cooldown %ds)",
                     group, n, GROUP_DEAD_COOLDOWN_TTL)
        _put_group_in_cooldown(group, GROUP_DEAD_COOLDOWN_TTL)


async def search_results_multi(
    query: str,    group_bot_pairs: list[tuple[str, str]],
) -> dict | None:
    """Search across multiple groups and merge deduplicated results.

    Returns ``{results, group_username, chat_id}`` or ``None`` if every group
    failed. Each result carries ``group_username`` and ``chat_id`` so the grab
    phase can act on the exact group the button came from.
    """
    if not query.strip() or len(query.strip()) < 2 or not group_bot_pairs:
        return None

    active = [(g, b) for g, b in group_bot_pairs if not _group_in_cooldown(g)]
    if not active:
        _log.warning("grabber: all %d group(s) in cooldown — skipping live search", len(group_bot_pairs))
        return None
    if len(active) < len(group_bot_pairs):
        _log.info("grabber: skipping %d cooldown group(s) this search", len(group_bot_pairs) - len(active))

    def _one(group: str, bot: str) -> asyncio.Task:
        # A suspect group (repeated timeouts/no-results) gets a short per-group
        # cap so a dead bot can't stall every search for the full timeout.
        timeout = SEARCH_GROUP_FAST_TIMEOUT if _group_is_suspect(group) else SEARCH_GROUP_TIMEOUT

        async def _run():
            try:
                return await asyncio.wait_for(
                    search_results(query, group, bot, timeout=timeout), timeout=timeout
                )
            except _SlowError:
                # Account is flood-limited — transient, NOT a dead group. Short
                # cooldown so the next search retries, without a dead-strike.
                _log.warning("grabber: search in %s slowmode-limited — short cooldown (not dead)", group)
                _put_group_in_cooldown(group, GROUP_COOLDOWN_NONE_TTL)
                return None
            except asyncio.TimeoutError:
                _log.warning("grabber: search in %s timed out after %ds — cooldown %ds",
                             group, timeout, GROUP_COOLDOWN_TIMEOUT_TTL)
                _mark_group_result(group, False)
                _put_group_in_cooldown(group, GROUP_COOLDOWN_TIMEOUT_TTL)
                return None
            except Exception as e:
                _log.warning("grabber: search in %s raised: %s", group, e)
                _mark_group_result(group, False)
                return None

        return asyncio.create_task(_run())

    # Serialize live searches so concurrent queries don't all fire into the
    # groups at once and compound Telegram's account-level flood/slowmode.
    async with _search_lock:
        tasks = {g: _one(g, b) for g, b in active}
        task_group = {t: g for g, t in tasks.items()}
        rest = set(tasks.values())

        merged: list[dict] = []
        seen: set[str] = set()
        any_ok = False
        first_group = ""
        first_chat_id = None
        deadline = asyncio.get_event_loop().time() + SEARCH_GROUP_TIMEOUT

        try:
            # FIRST_COMPLETED + early return: as soon as the fast groups have
            # yielded enough options we stop waiting on the slow/dead ones, so a
            # dead group never holds a common search at the full timeout.
            while rest:
                remaining = deadline - asyncio.get_event_loop().time()
                if remaining <= 0:
                    break
                done, rest = await asyncio.wait(
                    rest, timeout=remaining, return_when=asyncio.FIRST_COMPLETED
                )
                for t in done:
                    group = task_group[t]
                    try:
                        res = t.result()
                    except asyncio.CancelledError:
                        raise
                    except Exception as e:
                        _log.warning("grabber: search in %s raised: %s", group, e)
                        _mark_group_result(group, False)
                        continue
                    if res is None:
                        # No usable reply inside the reply window — either the bot
                        # is dead or it has nothing for this query. Cooldown so the
                        # next search skips it too (longer once it looks suspect).
                        _mark_group_result(group, False)
                        ttl = GROUP_COOLDOWN_TIMEOUT_TTL if _group_is_suspect(group) else GROUP_COOLDOWN_NONE_TTL
                        _put_group_in_cooldown(group, ttl)
                        continue
                    any_ok = True
                    _mark_group_result(group, True)
                    _clear_group_cooldown(group)
                    if first_chat_id is None:
                        first_group = group
                        first_chat_id = res.get("chat_id")
                    for r in res.get("results", []):
                        if r["label"] in seen:
                            continue
                        seen.add(r["label"])
                        r["group_username"] = group
                        r["chat_id"] = res.get("chat_id")
                        merged.append(r)
                    if len(merged) >= EARLY_RETURN_OPTIONS:
                        break
        finally:
            for t in rest:
                t.cancel()
            if rest:
                await asyncio.gather(*rest, return_exceptions=True)

        if not any_ok or not merged:
            return None
        return {
            "results": merged[:MAX_OPTIONS],
            "group_username": first_group,
            "chat_id": first_chat_id,
        }


# ---------------------------------------------------------------------------
# Phase 2: grab
# ---------------------------------------------------------------------------

async def grab_selected(
    query: str,
    row: int,
    col: int,
    telegram_id: int,
    group_username: str,
    bot_username: str,
    msg_id: int | None = None,
    target_file_name: str = "",
    depth: int | None = None,
) -> dict | None:
    """
    Click button[row][col], retrieve file, forward to storage, create DB record.

    Returns {name, size, stream_url, id, file_id, file_unique_id} or None.

    When ``msg_id`` is given the re-query step is skipped and the existing
    result message is re-used directly. The chat is always resolved from
    ``group_username`` (validated by the router); a caller-supplied chat id
    is never trusted.

    ``depth`` is the recorded page (0-based) the button was found on during
    search. It bounds the forward page-walk so grab does not re-scan every page
    and, crucially, does not re-query when the cached message was not rewound
    to page 1 in time. ``None`` (unknown) falls back to the legacy full walk.
    """
    async def _run(ivy: Client):
        bot_user = await _get_bot_user(ivy, bot_username)
        try:
            chat_id = await _resolve_group(ivy, group_username)
        except Exception as e:
            _log.error("grabber: resolve group %s failed: %s", group_username, e)
            return None

        # 1. Get result message (fresh or cached).
        # search_results rewinds the shared message back to page 1 after
        # collecting, so a cached message can be reused safely for either
        # match mode. If the button isn't found on the cached message (stale,
        # or the bot has no prev button so rewind failed), fall back to a
        # fresh query below.
        result_msg = None
        sent = None
        if msg_id is not None and chat_id is not None:
            try:
                result_msg = await ivy.get_messages(chat_id, msg_id)
                if result_msg and result_msg.from_user and bot_user is None:
                    bot_user = result_msg.from_user
            except Exception:
                pass
            if not result_msg or not result_msg.reply_markup:
                _log.warning("grabber: msg_id %s not found or stale, re-querying", msg_id)
                result_msg = None

        # The row/col the user picked is relative to the page the button was
        # found on during search (its ``depth``). Rewind a mid-menu cached
        # message back to page 1 if possible, then walk forward only as far as
        # that recorded depth instead of re-scanning every page — and never
        # re-query just because the background rewind was still in flight.
        if result_msg is not None and _find_prev_button(result_msg) is not None:
            try:
                rewound = await _rewind_to_first(ivy, result_msg)
            except Exception:
                rewound = None
            if rewound is None:
                _log.warning("grabber: msg_id %s could not be rewound to page 1, re-querying", msg_id)
                result_msg = None
            else:
                result_msg = rewound

        if result_msg is None:
            try:
                sent = await _send_with_retry(
                    ivy, chat_id, query,
                    deadline=asyncio.get_event_loop().time() + 60,
                )
            except Exception as e:
                _log.warning("grabber: search send failed in %s: %s", group_username, e)
                return None

            result_msgs = await _collect_bot_replies(ivy, chat_id, sent, bot_user, seconds=15)
            if bot_user is None and result_msgs:
                bot_user = result_msgs[0].from_user
            result_msg = result_msgs[0] if result_msgs else None

            if not result_msg:
                try:
                    await ivy.delete_messages(chat_id, sent.id)
                except Exception:
                    pass
                return None

        # 2. Click the specific button. Walk forward only up to the recorded
        # ``depth`` (legacy callers send None -> full MAX_PAGES walk). Positional
        # (row/col) matching is only trusted on the recorded page; text matching
        # (the frontend always sends file_name) works on any page up to depth.
        btn = None
        page_msg = result_msg
        walk_limit = MAX_PAGES if depth is None else max(depth, 0)
        for _attempt in range(2):
            page_idx = 0
            while page_msg is not None and page_idx <= walk_limit:
                if not page_msg.reply_markup or not page_msg.reply_markup.inline_keyboard:
                    break
                for row_idx, page_row in enumerate(page_msg.reply_markup.inline_keyboard):
                    for col_idx, page_btn in enumerate(page_row):
                        if _is_nav_button(page_btn.text):
                            continue
                        if target_file_name:
                            if page_btn.text == target_file_name:
                                btn = page_btn
                                break
                        elif depth is None:
                            if row_idx == row and col_idx == col:
                                btn = page_btn
                                break
                        elif page_idx == depth and row_idx == row and col_idx == col:
                            btn = page_btn
                            break
                    if btn:
                        break
                if btn:
                    break
                if page_idx >= walk_limit:
                    break
                page_msg = await _advance_page(ivy, page_msg)
                if page_msg is None:
                    break
                page_idx += 1
            if btn:
                break
            if sent is not None:
                # Already used a fresh query — nothing left to retry.
                break
            _log.warning("grabber: button not found on reused msg %s, re-querying", msg_id)
            if result_msg is not None:
                try:
                    await ivy.delete_messages(chat_id, result_msg.id)
                except Exception:
                    pass
            result_msg = None
            try:
                sent = await _send_with_retry(
                    ivy, chat_id, query,
                    deadline=asyncio.get_event_loop().time() + 60,
                )
            except Exception as e:
                _log.warning("grabber: search send failed in %s: %s", group_username, e)
                return None
            result_msgs = await _collect_bot_replies(ivy, chat_id, sent, bot_user, seconds=15)
            if bot_user is None and result_msgs:
                bot_user = result_msgs[0].from_user
            result_msg = result_msgs[0] if result_msgs else None
            if not result_msg:
                try:
                    await ivy.delete_messages(chat_id, sent.id)
                except Exception:
                    pass
                return None
            page_msg = result_msg

        if btn is None:
            _log.error("grabber: button [%s][%s]%s not found",
                       row, col, f" ({target_file_name!r})" if target_file_name else "")
            to_del_ids = [m.id for m in (sent, result_msg) if m]
            try:
                await ivy.delete_messages(chat_id, to_del_ids)
            except Exception:
                pass
            return None

        # ponytail: click by text, not position. Duplicate labels click the first match.
        clicked = None
        bot_id = 0
        for attempt in range(1, 3):
            try:
                bot_id = _bot_key_from_msg(page_msg) or (bot_user.id if bot_user else 0)
                lock = await _bot_click_lock(bot_id)
                async with lock:
                    await _pace_click(bot_id)
                    clicked = await page_msg.click(btn.text, timeout=10)
                    _note_click(bot_id)
                break
            except asyncio.CancelledError:
                raise
            except Exception as e:
                flood = _flood_seconds(e)
                if flood is not None:
                    _bot_flood_until[bot_id] = max(
                        _bot_flood_until.get(bot_id, 0.0),
                        asyncio.get_event_loop().time() + flood + 0.5,
                    )
                    if attempt < 2:
                        _log.warning("grabber: click flood wait %ds, retrying once", flood)
                        await asyncio.sleep(flood + 0.5)
                        continue
                _log.warning("grabber: click failed: %s", e)
                clicked = None
                break
        if clicked is None:
            _log.warning("grabber: click failed")
            to_del_ids = [m.id for m in (sent, result_msg) if m]
            try:
                await ivy.delete_messages(chat_id, to_del_ids)
            except Exception:
                pass
            return None
        _log.warning("grabber: clicked type=%s val=%s", type(clicked).__name__, str(clicked)[:200])

        # 3. Extract deep-link param + owning bot from click response.
        # The file bot named in the deep-link URL (e.g. t.me/MagicMovies1Bot)
        # is the one that delivers the file — NOT necessarily the group's bot.
        param = ""
        file_bot_username = ""

        def _extract_deep_link(url: str) -> bool:
            nonlocal param, file_bot_username
            m = _DEEP_LINK_RE.search(url)
            if not m:
                return False
            param = m.group(1)
            mb = _DEEP_LINK_BOT_RE.search(url)
            if mb and mb.group(1).lower() not in ("share", "telegram"):
                file_bot_username = mb.group(1)
            return True

        if isinstance(clicked, str) and "start=" in clicked:
            _extract_deep_link(clicked)
        elif getattr(clicked, "url", None) and "start=" in clicked.url:
            _extract_deep_link(clicked.url)
        elif bot_user is not None:
            for _ in range(6):
                await asyncio.sleep(1)
                try:
                    # History is newest-first; take the FIRST matching message
                    # and stop — older matches are leftovers from previous grabs
                    # and would overwrite the fresh param with a stale one.
                    async for msg in ivy.get_chat_history(bot_user.id, limit=5):
                        saw_link = False
                        if msg.text and "start=" in msg.text:
                            _extract_deep_link(msg.text)
                            saw_link = True
                        if not saw_link and msg.reply_markup:
                            for row_b in msg.reply_markup.inline_keyboard:
                                for btn in row_b:
                                    if btn.url and "start=" in btn.url:
                                        _extract_deep_link(btn.url)
                                        saw_link = True
                                        break
                                if saw_link:
                                    break
                        if saw_link or param:
                            break
                except Exception:
                    pass
                if param:
                    break

        if not param:
            _log.error("grabber: could not extract deep-link param after click")
            to_del_ids = [m.id for m in (sent, result_msg) if m]
            try:
                await ivy.delete_messages(chat_id, to_del_ids)
            except Exception:
                pass
            return None

        # 4. Send /start to the bot that owns the deep link (fall back to the
        # group bot) and handle force-sub channels.
        start_bot = bot_user
        if file_bot_username:
            file_bot = await _get_bot_user(ivy, file_bot_username)
            if file_bot is not None:
                start_bot = file_bot
                _log.info("grabber: /start targeting file bot @%s", file_bot_username)
            else:
                _log.warning("grabber: could not resolve deep-link bot @%s — using group bot", file_bot_username)
        if start_bot is None:
            _log.error("grabber: could not determine bot user for /start")
            to_del_ids = [m.id for m in (sent, result_msg) if m]
            try:
                await ivy.delete_messages(chat_id, to_del_ids)
            except Exception:
                pass
            return None
        file_msg = await _wait_for_file_auto_join(ivy, start_bot.id, f"/start {param}")

        # Cleanup group messages
        to_del_ids = [m.id for m in (sent, result_msg) if m]
        if sent:
            try:
                await ivy.delete_messages(chat_id, to_del_ids)
            except Exception:
                pass

        if not file_msg:
            return None

        obj = file_msg.video or file_msg.document or file_msg.audio or file_msg.photo
        file_name = getattr(obj, "file_name", "unknown")
        file_size = getattr(obj, "file_size", 0)
        mime_type = getattr(obj, "mime_type", None)
        if file_msg.photo:
            file_type = "image"
            mime_type = mime_type or "image/jpeg"
        elif file_msg.video:
            file_type = "video"
            mime_type = mime_type or "video/mp4"
        elif file_msg.audio:
            file_type = "audio"
            mime_type = mime_type or "audio/mpeg"
        else:
            mime_type = mime_type or "video/mp4"
            file_type = classify_file_type(file_name, mime_type)

        # Sanity-check the delivered file against the button the user picked —
        # the bot can link a label to a completely different movie or a worse
        # resolution. Hard mismatch aborts the grab (nothing stored), soft
        # mismatch (resolution) is surfaced as a warning on the response.
        warning = ""
        if target_file_name:
            ok, warning = _label_file_check(target_file_name, file_name)
            if not ok:
                _log.warning("grabber: label/file mismatch for %r: %s", file_name, warning)
                to_del_ids = [m.id for m in (sent, result_msg) if m]
                try:
                    await ivy.delete_messages(chat_id, to_del_ids)
                except Exception:
                    pass
                raise _GrabError(warning)
            elif warning:
                _log.warning("grabber: label/file soft mismatch for %r: %s", file_name, warning)

        # 5. Forward to storage channel
        from .telegram import forward_to_storage_channel
        try:
            fwd = await forward_to_storage_channel(file_msg)
        except Exception as e:
            _log.error("grabber: forward failed: %s", e)
            return None

        if not fwd:
            return None

        fwd_obj = fwd.video or fwd.document or fwd.audio or fwd.photo
        if not fwd_obj:
            _log.error("grabber: forwarded message has no media")
            return None

        channel_msg_id = fwd.id
        file_id = fwd_obj.file_id
        file_unique_id = fwd_obj.file_unique_id

        # 6. Create DB record
        async with async_session() as db:
            from sqlalchemy import select
            result = await db.execute(select(User).where(User.telegram_id == telegram_id))
            db_user = result.scalar_one_or_none()
            if not db_user:
                _log.warning("grabber: user %s not found in DB", telegram_id)
                return None
            file_record = File(
                user_id=db_user.id,
                file_id=file_id,
                file_unique_id=file_unique_id,
                file_name=file_name,
                file_size=file_size,
                mime_type=mime_type,
                file_type=file_type,
                channel_message_id=channel_msg_id,
            )
            db.add(file_record)
            await db.commit()
            await db.refresh(file_record)
            db_file_id = file_record.id

        from .auth import create_download_token
        token = create_download_token(str(telegram_id), db_file_id)
        s = get_settings()
        stream_url = f"{s.web_base_url.rstrip('/')}/api/stream/{db_file_id}?token={token}"

        return {
            "name": file_name,
            "size": file_size,
            "stream_url": stream_url,
            "id": db_file_id,
            "file_id": file_id,
            "file_unique_id": file_unique_id,
            "channel_message_id": channel_msg_id,
            "warning": warning,
        }

    try:
        return await _ivy_pool.execute(_run)
    except _GrabError:
        # User-visible grab failure (wrong file, pending channel approval) —
        # let the router turn it into a clear HTTP error.
        raise
    except RuntimeError as e:
        _log.error("grabber: %s", e)
        return None
    except Exception as e:
        _log.exception("grabber: unexpected grab error")
        return None
