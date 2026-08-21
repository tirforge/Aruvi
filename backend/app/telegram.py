"""
PyroTGFork MTProto client for Telegram interactions.
Handles both bot commands and file streaming via a client pool.
"""
import re
import time
import os
import traceback
from .patch import Client
from pyrogram.types import Message
from .config import get_settings
from pathlib import Path
import asyncio
import logging


settings = get_settings()

BASE_DIR = Path(__file__).resolve().parent.parent
SESSION_DIR = Path(os.environ.get("TELEGRAM_SESSION_DIR", str(BASE_DIR / "session")))


def get_session_name(index: int) -> str:
    return str(SESSION_DIR / f"bot_{index}")


logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)
if not logger.handlers:
    _h = logging.StreamHandler()
    _h.setLevel(logging.DEBUG)
    _h.setFormatter(logging.Formatter("telegram %(levelname)s: %(message)s"))
    logger.addHandler(_h)
    logger.propagate = False

# In-memory log collector (capped at 200 to prevent memory growth)
_startup_logs: list[str] = []
_MAX_DIAG_LOGS = 200

def diag_log(msg):
    _startup_logs.append(msg)
    if len(_startup_logs) > _MAX_DIAG_LOGS:
        _startup_logs.pop(0)
    logger.info(msg)

def get_diag_logs():
    return list(_startup_logs)

# Build pool at module level
tokens = settings.all_bot_tokens
clients = []

_proxy_kwargs = {}
# HF Spaces sets SPACE_ID — Telegram DCs are reachable directly there
_on_hf = bool(os.environ.get("SPACE_ID"))
if _on_hf and settings.mt_proxy_url:
    diag_log("HF Space detected — ignoring MT_PROXY_URL, connecting directly")
elif settings.mt_proxy_url:
    from urllib.parse import urlparse
    p = urlparse(settings.mt_proxy_url)
    proxy_cfg = dict(
        scheme=p.scheme or "socks5",
        hostname=p.hostname or "127.0.0.1",
        port=p.port or 1080,
    )
    if p.username:
        proxy_cfg["username"] = p.username
    if p.password:
        proxy_cfg["password"] = p.password
    _proxy_kwargs["proxy"] = proxy_cfg
    auth = f"{p.username}@{p.hostname}" if p.username else p.hostname
    diag_log(f"Using MT proxy: {auth}:{p.port or 1080}")
else:
    diag_log("No MT proxy set — connecting directly to Telegram DCs")

diag_log(f"Creating {len(tokens)} client(s)...")
for i, token in enumerate(tokens):
    diag_log(f"Client {i}: building at module level...")
    kwargs = dict(
        api_id=settings.telegram_api_id,
        api_hash=settings.telegram_api_hash,
        bot_token=token,
        ipv6=False,
        max_concurrent_transmissions=settings.telegram_client_concurrency,
        # Kurigram sleeps (up to sleep_threshold) instead of raising on
        # FLOOD_WAIT. Media fetches already hardcode 30s; raising the client
        # default lets get_messages / ExportAuthorization absorb short throttles
        # instead of failing batches under load.
        sleep_threshold=15,
        no_updates=(i > 0),
        **_proxy_kwargs,
    )
    client = Client(name=get_session_name(i), **kwargs)
    diag_log(f"Client {i}: built (is_connected={client.is_connected})")
    client.pool_index = i
    clients.append(client)

tg_client = clients[0]
diag_log("Module-level setup complete")


# ── lifecycle helpers ────────────────────────────────────────────────

# Serialize start() per client: both the lifespan start_all_clients() and
# _finish_startup() fire helpers, and two concurrent starts on one client hit
# connect()'s "already connected" guard, stranding the loser.
_start_locks: dict[int, asyncio.Lock] = {}


def get_start_lock(i: int) -> asyncio.Lock:
    if i not in _start_locks:
        _start_locks[i] = asyncio.Lock()
    return _start_locks[i]


# Fire-and-forget tasks are tracked so shutdown can cancel them instead of
# leaving orphaned coroutines (retries, warmups) running mid-teardown.
_bg_tasks: set[asyncio.Task] = set()


def _spawn(coro) -> asyncio.Task:
    t = asyncio.create_task(coro)
    _bg_tasks.add(t)
    t.add_done_callback(_bg_tasks.discard)
    return t


async def start_one_client(i, c):
    max_attempts = 3
    # Full logins (ImportBotAuthorization on a fresh session) + crypto cold
    # start can exceed the old 20s on a slow DC; 45s absorbs that without
    # letting a hung auth hold the boot too long.
    connect_timeout = 45
    async with get_start_lock(i):
        for attempt in range(1, max_attempts + 1):
            if c.is_connected:
                diag_log(f"Client {i}: already connected — skipping start")
                return
            try:
                diag_log(f"Client {i}: starting (attempt {attempt}, is_connected={c.is_connected})")
                await asyncio.wait_for(c.start(), timeout=connect_timeout)
                diag_log(f"Client {i}: start() returned (is_connected={c.is_connected})")
                me = await c.get_me()
                label = "Main" if i == 0 else "Helper"
                diag_log(f"Client {i} ({label}) started → @{me.username}")
                return
            except ConnectionError as e:
                err_str = str(e).lower()
                if "already connected" in err_str:
                    # Another coroutine won the race and finished the start.
                    diag_log(f"Client {i}: already connected (caught) — treating as started")
                    return
                raise
            except Exception as e:
                err_str = str(e).lower()
                # Flood wait: sleep and retry
                if "flood_wait" in err_str or "flood" in err_str:
                    match = re.search(r"(\d+)", err_str)
                    wait = min(int(match.group(1)) if match else 60, 120)
                    diag_log(f"Client {i}: flood wait {wait}s, retrying...")
                    await asyncio.sleep(wait)
                    continue
                if attempt < max_attempts:
                    delay = 2 ** attempt
                    diag_log(f"Client {i}: transient error (attempt {attempt}): {e}. Retrying in {delay}s...")
                    await asyncio.sleep(delay)
                    continue
                tb = traceback.format_exc()
                diag_log(f"Client {i} failed to start after {max_attempts} attempts: {e}\n{tb}")
    # If all attempts exhausted and this is main bot, log and continue
    # (server starts without it; background retries in _finish_startup)
    if i == 0 and not c.is_connected:
        diag_log(f"Bot 0 failed to connect after {max_attempts} attempts — starting server anyway")


async def start_all_clients():
    logger.info("Starting %d Telegram client(s)...", len(clients))
    tasks = [start_one_client(i, c) for i, c in enumerate(clients)]
    await asyncio.gather(*tasks)


async def stop_one_client(c):
    try:
        if c.is_connected:
            await c.stop()
    except Exception:
        pass


async def stop_all_clients():
    for c in clients:
        await stop_one_client(c)


# Reconnect circuit breaker: per-client cooldown after a failed re-auth so
# concurrent workers/streams back off instead of hammering Telegram's auth.
_reconnect_cooldown_until: dict[int, float] = {}
_RECONNECT_COOLDOWN = 60.0


async def reconnect_client(client: Client) -> bool:
    """Disconnect, re-authorize, and reconnect a Pyrogram client.
    
    Uses start() (not just connect()) so a new auth key is obtained
    when the old one was invalidated (AuthKeyUnregistered).
    Returns True if reconnection succeeded, False otherwise.
    """
    idx = getattr(client, "pool_index", 0)
    now = time.monotonic()
    if _reconnect_cooldown_until.get(idx, 0) > now:
        diag_log(f"Client {idx}: reconnect on cooldown, skipping")
        return False
    try:
        # Serialize with start_one_client/_retry_bot_0 on the same client —
        # two concurrent starts strand the loser in connect()'s
        # "already connected" guard.
        async with get_start_lock(idx):
            if client.is_connected:
                await client.disconnect()
            await client.start()
        diag_log(f"Client {getattr(client, 'pool_index', '?')} re-authorized successfully")
        return True
    except Exception as e:
        # Circuit breaker: failed reconnects are often Telegram-side auth
        # rate-limiting — retrying immediately across many workers just hammers
        # it. Back off before the next attempt.
        _reconnect_cooldown_until[idx] = now + _RECONNECT_COOLDOWN
        diag_log(f"Client {getattr(client, 'pool_index', '?')} re-auth failed: {e} (cooldown {_RECONNECT_COOLDOWN:.0f}s)")
        return False


async def start_telegram_client():
    """Called from app lifespan — starts main bot and warms DC before returning.

    The server will NOT yield until the main bot is connected and has
    established a connection to the storage channel DC. This eliminates
    the 5-7s Telegram DC auth init on the first user request (cold start).
    Helper bots continue starting in background.
    Returns the background task so the caller can cancel it on shutdown.
    """
    # Await main bot connection so DC is warm for streaming
    await start_one_client(0, clients[0])

    # Force DC connection by fetching one message from storage channel
    channel_id = settings.telegram_storage_channel_id
    if channel_id and clients[0].is_connected:
        try:
            msg = await asyncio.wait_for(
                clients[0].get_messages(channel_id, 1),
                timeout=15
            )
            if msg:
                diag_log(f"Main bot DC warmed — message {msg.id} fetched from channel")
            else:
                diag_log("Main bot DC warmup: channel returned empty")
        except Exception as e:
            diag_log(f"Main bot DC warmup failed: {e}")
    else:
        diag_log("Main bot DC warmup skipped (no channel or not connected)")

    # Fire helpers in background (non-blocking)
    task = _spawn(_finish_startup())
    return task


async def _warmup_messages():
    """Pre-fetch recent messages from the storage channel using ALL bots
    to warm message cache, connection pool, and channel entities.
    Every connected bot fetches the same set so each one has an active
    connection to the channel with cached file references."""
    channel_id = settings.telegram_storage_channel_id
    if not channel_id:
        return
    connected = [c for c in clients if c.is_connected]
    if not connected:
        return
    try:
        diag_log(f"Warming up {len(connected)} bot(s)...")
        mids = list(range(1, 21))

        async def _warm_one(client):
            count = 0
            for mid in mids:
                try:
                    msg = await client.get_messages(channel_id, mid)
                    if msg:
                        # Only cache keys the reader can actually hit —
                        # get_message_from_channel reads tg_client's pool_index
                        # only, so per-helper keys would be dead weight.
                        if getattr(client, "pool_index", 0) == getattr(tg_client, "pool_index", 0):
                            key = (getattr(client, "pool_index", 0), msg.id)
                            if key not in _msg_cache:
                                _msg_cache[key] = (time.monotonic(), msg)
                                count += 1
                                _msg_cache_evict()
                except Exception:
                    pass
            return count

        results = await asyncio.gather(*[_warm_one(c) for c in connected])
        total = sum(results)
        diag_log(f"Warmup done — all bots, {len(_msg_cache)} cached ({total} new)")
    except Exception:
        pass  # Warmup is best-effort


async def _finish_startup():
    """Start helper bots in background, wait for ≥13 to connect, then warm up."""
    if len(clients) > 1:
        # Fire all helpers as background tasks (never block on all)
        for i, c in enumerate(clients[1:], 1):
            _spawn(start_one_client(i, c))

        # Poll until at least MIN_HELPERS are connected (or 30s timeout).
        # Clamp to the actual helper count so a low-bot deployment doesn't
        # always burn the full 30s poll window waiting for an unreachable cap.
        MIN_HELPERS = min(16, len(clients) - 1)  #TW
        for _ in range(60):
            connected = sum(
                1 for c in clients
                if getattr(c, 'pool_index', 0) != 0 and c.is_connected
            )
            if connected >= MIN_HELPERS:
                break
            await asyncio.sleep(0.5)
        diag_log(f"Helper check: {connected}/{len(clients)-1} connected")

    # Verify each bot can access the storage channel
    channel_id = settings.telegram_storage_channel_id
    if channel_id:
        for i, c in enumerate(clients):
            if not c.is_connected:
                diag_log(f"Client {i}: skipped channel check (not connected)")
                continue
            try:
                me = await c.get_me()
                msg = await c.get_messages(channel_id, 1)
                if msg:
                    diag_log(f"Client {i} (@{me.username}): channel access OK")
                else:
                    diag_log(f"Client {i} (@{me.username}): channel returned empty — add bot as admin")
            except Exception as e:
                diag_log(f"Client {i} (@{me.username}): CHANNEL_INVALID — add this bot as admin to channel {channel_id}")
                diag_log(f"  Bot token starts with: {getattr(c, 'bot_token', '?')[:8]}...")
                diag_log(f"  Error: {e}")

    # Retry bot 0 if it failed earlier (transient Telegram DC issue)
    if not clients[0].is_connected:
        _spawn(_retry_bot_0())

    # Warm up: pre-fetch recent messages so first user request is fast
    _spawn(_warmup_messages())

    # Warm media sessions SERIALLY. Telegram rate-limits the auth.ExportAuthorization /
    # auth.ImportAuthorization RPC that establishes a media session. If N concurrent
    # cold streams each establish their own session at once, they flood Telegram and
    # every stream stalls (~0 progress). Warming one bot at a time at boot absorbs
    # that one-time throttle risk before any user traffic, so streams reuse the
    # warmed sessions (Pyrogram caches them in client.media_sessions[dc_id]).
    _spawn(_warm_media_sessions())


_WARM_PROBE_N = 40            # recent channel messages probed to discover DCs
_WARM_BOTS_PER_DC = 3         # bots warmed per secondary DC (primary DC: all)
_WARM_STREAM_TIMEOUT = 15     # per (bot, DC) first-chunk timeout (auth included)
_WARM_TOTAL_TIMEOUT = 120     # whole warm-up deadline — never hold boot >2 min


async def _warm_media_sessions():
    """Serially establish a media session on EVERY storage-channel DC.

    Channel media is spread across several Telegram DCs (observed 4 here). The
    old warm-up only warmed the DC of one arbitrary message, so files on the
    other DCs always cold-started with a flood-risky auth.ImportAuthorization —
    and stalled when that DC was flaky. We take the DCs from the recent DB files
    (falling back to channel probes), then warm each DC on a few bots one auth at
    a time, so concurrent cold streams reuse the sessions instead of racing a
    flood-waited auth.ExportAuthorization. Best-effort: a (bot, DC) that fails
    is skipped (the runtime _media_session_scope lock still serializes any cold
    session it needs on demand), and a flaky DC is bounded by per-op + total
    timeouts so boot is never held longer than _WARM_TOTAL_TIMEOUT.
    """
    try:
        from .streaming import _media_session_lock, _media_sessions_warmed
        from pyrogram.file_id import FileId
        channel_id = settings.telegram_storage_channel_id
        if not channel_id:
            return
        connected = [c for c in clients if getattr(c, "is_connected", False)]
        if not connected:
            return

        # Discover the channel's DCs. DB is authoritative: recent files encode
        # every DC that holds media, so we warm exactly those. Fall back to
        # channel probes if the DB is unavailable at boot.
        dc_mids = {}  # dc_id -> one representative channel_message_id

        def _add_dc(mid, file_id):
            try:
                dc = FileId.decode(file_id).dc_id
            except Exception:
                return
            if dc not in dc_mids:
                dc_mids[dc] = mid

        try:
            from sqlalchemy import text
            from .database import async_session
            async with async_session() as session:
                rows = await session.execute(
                    text("SELECT channel_message_id, file_id FROM files ORDER BY id DESC LIMIT 80")
                )
                for r in rows:
                    if len(dc_mids) >= 4:
                        break
                    _add_dc(r[0], r[1])
        except Exception:
            pass  # DB unavailable at boot — fall back to channel probes

        # Fallback: decode DCs from messages already cached / probed.
        if len(dc_mids) < 2:
            async def _add_candidates(cands):
                for m in cands:
                    if not m:
                        continue
                    media = getattr(m, "video", None) or getattr(m, "document", None) or getattr(m, "audio", None)
                    if media:
                        _add_dc(m.id, media.file_id)

            await _add_candidates([msg for _t, msg in list(_msg_cache.values())[:200]])
            try:
                last = await asyncio.wait_for(clients[0].get_messages(channel_id, 0), timeout=15)
                if last:
                    lo = max(1, last.id - _WARM_PROBE_N + 1)
                    recent = await asyncio.wait_for(
                        clients[0].get_messages(channel_id, list(range(lo, last.id + 1))),
                        timeout=30,
                    )
                    await _add_candidates(reversed(recent or []))
            except Exception:
                pass
            for cand in range(1, 41):
                try:
                    probe = await asyncio.wait_for(clients[0].get_messages(channel_id, cand), timeout=15)
                    if probe:
                        await _add_candidates([probe])
                except Exception:
                    pass
                if len(dc_mids) >= 4:
                    break
        if not dc_mids:
            diag_log("Media-session warm-up: no media message found, skipping")
            return

        dc_order = list(dc_mids)  # order reflects DB recency (primary DC first)
        diag_log(f"Warming media sessions serially for DCs {dc_order} "
                 f"({len(connected)} bots)...")
        warmed = 0
        try:
            async with asyncio.timeout(_WARM_TOTAL_TIMEOUT):
                for dc in dc_order:
                    mid = dc_mids[dc]
                    limit = len(connected) if dc == dc_order[0] else min(_WARM_BOTS_PER_DC, len(connected))
                    for bot in connected[:limit]:  # one auth at a time
                        try:
                            fm = await asyncio.wait_for(bot.get_messages(channel_id, mid), timeout=15)
                            if not fm or not (fm.video or fm.document or fm.audio):
                                continue
                            async with _media_session_lock:  # never race a user stream's cold auth
                                async with asyncio.timeout(_WARM_STREAM_TIMEOUT):
                                    async for _part in bot.stream_media(fm, limit=1, offset=0):
                                        break  # first chunk proves the media session works
                            warmed += 1
                            diag_log(f"  Media-session warm-up: dc {dc}, bot {getattr(bot, 'pool_index', '?')} warm")
                        except Exception as e:
                            diag_log(f"  Media-session warm-up: dc {dc}, bot skip ({e})")
        except asyncio.TimeoutError:
            diag_log(f"Media-session warm-up: hit {_WARM_TOTAL_TIMEOUT}s deadline, releasing")
        diag_log(f"Media-session warm-up done: {warmed} session(s) warm across DCs {dc_order}")
    except Exception as e:
        diag_log(f"Media-session warm-up failed: {e}")
    finally:
        # Always release cold fetches waiting on us — whether warm-up succeeded,
        # was skipped, or failed. They proceed best-effort under the lock.
        _media_sessions_warmed.set()


async def _retry_bot_0():
    """Retry main bot connection in background with exponential backoff."""
    for attempt in range(1, 11):
        await asyncio.sleep(min(30 * attempt, 300))  # 30s, 60s, ... up to 5min
        if clients[0].is_connected:
            diag_log("Bot 0 reconnected on retry attempt")
            return
        diag_log(f"Retrying bot 0 connection (attempt {attempt}/10)...")
        try:
            async with get_start_lock(0):
                await asyncio.wait_for(clients[0].start(), timeout=20)
            if clients[0].is_connected:
                me = await clients[0].get_me()
                diag_log(f"Bot 0 reconnected → @{me.username}")
                return
        except Exception as e:
            diag_log(f"Bot 0 retry {attempt} failed: {e}")
    diag_log("Bot 0 retry exhausted after 10 attempts — continuing without main bot")


async def stop_telegram_client():
    """Called from app lifespan — cancels tracked background tasks, then
    stops the full pool."""
    for t in list(_bg_tasks):
        t.cancel()
    if _bg_tasks:
        await asyncio.gather(*_bg_tasks, return_exceptions=True)
    await stop_all_clients()


# ── Message cache ────────────────────────────────────────────────────

_msg_cache: dict[tuple[int, int], tuple[float, Message]] = {}
MSG_CACHE_TTL = 3600  # 1 hour (messages in storage channel don't change)
_MSG_CACHE_MAX = 5000

def _msg_cache_key(message_id: int) -> tuple[int, int]:
    """Cache is keyed per-client (pool_index) so we never hand a Message
    fetched by helper bot N to a stream running on tg_client (bot 0)."""
    return (getattr(tg_client, "pool_index", 0), message_id)

def _prune_msg_cache():
    """Remove TTL-expired entries proactively."""
    now = time.monotonic()
    stale = [key for key, (ts, _) in _msg_cache.items() if now - ts > MSG_CACHE_TTL]
    for key in stale:
        _msg_cache.pop(key, None)

def _msg_cache_evict():
    """Remove oldest entries if cache exceeds max size."""
    if len(_msg_cache) <= _MSG_CACHE_MAX:
        return
    # Sort by timestamp and remove oldest 20%
    by_age = sorted(_msg_cache.items(), key=lambda x: x[1][0])
    to_remove = len(_msg_cache) - int(_MSG_CACHE_MAX * 0.8)
    for key, _ in by_age[:to_remove]:
        _msg_cache.pop(key, None)

def invalidate_message_cache(message_id: int):
    for key in [k for k in _msg_cache if k[1] == message_id]:
        _msg_cache.pop(key, None)

def invalidate_message_cache_batch(message_ids: list[int]):
    for mid in message_ids:
        invalidate_message_cache(mid)

# ── convenience helpers (always use tg_client) ───────────────────────

async def get_message_from_channel(message_id: int) -> Message:
    now = time.monotonic()
    key = _msg_cache_key(message_id)
    if key in _msg_cache:
        ts, msg = _msg_cache[key]
        if now - ts < MSG_CACHE_TTL:
            return msg
    msg = await tg_client.get_messages(
        settings.telegram_storage_channel_id,
        message_id,
    )
    # Don't cache empty/missing messages — a transient fetch failure would
    # otherwise pin a useless (or wrong) result for the full TTL hour.
    if msg and not getattr(msg, "empty", False):
        _msg_cache[key] = (now, msg)
        _msg_cache_evict()
    return msg


async def forward_to_storage_channel(message: Message) -> Message:
    return await message.copy(settings.telegram_storage_channel_id)


async def delete_from_storage_channel(message_ids: int | list[int]) -> bool:
    try:
        await tg_client.delete_messages(
            settings.telegram_storage_channel_id,
            message_ids,
        )
        return True
    except Exception:
        return False
