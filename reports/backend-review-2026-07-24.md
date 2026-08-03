# Aruvi Backend — Comprehensive Review

**Date:** 2026-07-24
**Scope:** All Python source files in `Aruvi-backend/backend/app/`
**Reviewers:** Code Review + Security Audit + Performance Analysis

---

## Summary

The Aruvi backend is a well-architected FastAPI application with a sophisticated multi-client parallel streaming engine for Telegram media. It uses Pyrogram (Kurigram) MTProto clients in a pool, with a weighted-least-loaded scheduler, chunk-level cache, CDN session management, and yield-smoothing prebuffers. The codebase shows good engineering judgment overall, but has several high-severity bugs (unclosed file descriptors, silent exception swallowing in streaming, potential OOM from unbounded cache growth), security concerns (JWT sub types, hardcoded fallback admin ID), and performance bottlenecks (N+1 folder-parent traversal, full table scans for parent paths).

**Issues found: 22 (4 Critical, 7 High, 6 Medium, 5 Low)**

---

## Key Findings

### Critical
1. **Unclosed file descriptor in GDrive download** — `fd` leaked on certain error paths
2. **Streaming semaphore leak** — `_backpressure.acquire()` without corresponding `release()` on CDN failures
3. **Hardcoded fallback admin ID** — exposed in source code
4. **Silent exception swallowing in streaming worker** — `_fetch_batch` errors in exception handlers pass silently, leaving futures unresolved indefinitely

### High
5. **GDrive upload file descriptor never closed on error** — `os.close(fd)` only in `finally`, but `fd` may not be assigned
6. **`results[chunk_idx]` may be awaited before being set** — race between yield loop and worker tasks
7. **No timeout on `_ensure_cdn_session`** — can block a worker forever
8. **JWT `sub` field is string type** — creates subtle type conversion bugs
9. **Folder tree builds full folder map in memory** — loads ALL user folders into a dict for parent path
10. **`web_base_url` hardcoded to REDACTED_DOMAIN in config defaults**
11. **Admin delete doesn't clean up storage channel files**

### Medium
12. **`_utcnow()` strips timezone info** — datetime comparisons may be ambiguous
13. **WatchProgress upsert race condition** — select-then-insert without `ON CONFLICT` or unique constraint handling
14. **Batch file delete ignores Telegram errors silently** — partial failure may lose DB-TG consistency
15. **`tg_client` accessed at module level** — may not be initialized when first imported
16. **HTTP `Range` header parsing can return invalid ranges** — missing validation for negative start
17. **`os.posix_fadvise` usage in GDrive download** — fallback needed for non-Linux

### Low
18. **Module-level `_client_pool` instantiation race** — double-checked locking pattern is broken in Python
19. **`MAX_CDN_FAILURES = 0` disables CDN entirely** — dead code
20. **`_parse_mem_env` silently returns int on unparseable input** — default missing
21. **No health check timeout on `/_diag/ping`** — may block if TG is unreachable
22. **`doubt.txt` and `debug_prompt.txt` committed** — debugging artifacts in source tree

---

## Detailed Analysis

---

### CRITICAL Issues

#### [C1] Unclosed file descriptor in GDrive download path

**File:** `backend/app/gdrive.py` lines 271-323

**Issue:** The file descriptor `fd = os.open(tmp, os.O_RDWR | os.O_DSYNC)` is assigned at line 272. The `finally` block at line 321 closes it only if `fd is not None`, but if an exception occurs BEFORE `fd` is assigned (e.g., `os.open` itself raises `OSError`), the `finally` block will reference an undefined `fd`. Additionally, if `_download_slot` tasks raise an exception that's not caught by `asyncio.gather`, the `finally` block still runs but `fd` may be in an inconsistent state.

```python
# gdrive.py:272
fd = os.open(tmp, os.O_RDWR | os.O_DSYNC)  # Could raise OSError

# gdrive.py:320-323
try:
    await asyncio.gather(*tasks)
finally:
    if fd is not None:  # NameError if os.open failed
        os.close(fd)
```

**Fix:** Use `fd = None` before the try and check `fd is not None`:

```python
fd = None
try:
    fd = os.open(tmp, os.O_RDWR | os.O_DSYNC)
    ...
finally:
    if fd is not None:
        os.close(fd)
```

---

#### [C2] Streaming backpressure semaphore leak on CDN failure

**File:** `backend/app/streaming.py` lines 700, 739-742

**Issue:** The `_backpressure` semaphore is acquired inside `_fetch_batch_cdn` (line 700: `await _backpressure.acquire()`) and `_fetch_batch` (line 742). On the CDN path, when a transport error occurs (line 702-710), the function returns `None` WITHOUT releasing the `_backpressure` permits that were already acquired. This causes the semaphore to leak, eventually blocking ALL future streams when it reaches 2000 (the limit).

```python
# streaming.py:700 (in _fetch_batch_cdn)
await _backpressure.acquire()
...
except (ConnectionError, OSError, TimeoutError) as e:
    _cdn_failures += 1
    return None  # ← LEAK: no _backpressure.release()
```

**Fix:** Use a try/finally or release before returning:

```python
try:
    await _backpressure.acquire()
    ...
except (ConnectionError, OSError, TimeoutError) as e:
    _backpressure.release()
    ...
    return None
```

Or better, wrap the acquire in a context manager pattern: `async with _backpressure:` where possible (though this requires restructuring since `results[current].set_result` needs to happen within the acquire window).

---

#### [C3] Hardcoded fallback admin ID exposed in source

**File:** `backend/app/bot.py` line 65

**Issue:** A hardcoded fallback Telegram user ID is exposed in source code:

```python
ADMIN_IDS: set[int] = settings.admin_ids or {REDACTED_USER_ID}
```

While `REDACTED_USER_ID` is a placeholder here in the review, the actual code uses a real numeric ID. This is a **security exposure** — the admin ID is committed to git history.

**Fix:** Remove the hardcoded fallback entirely. The admin should be set via `ADMIN_IDS` env var:

```python
ADMIN_IDS: set[int] = settings.admin_ids or set()
```

---

#### [C4] Silent exception swallowing in streaming worker leaves futures unresolved

**File:** `backend/app/streaming.py` lines 817-827, 828-829, 860, 881-882

**Issue:** Multiple exception handlers in the `worker()` function have `pass` or `continue` without setting the unresolved futures. When a batch fails for any reason and the fallback `_fetch_one` also fails, the corresponding `results[chunk_idx]` futures are NEVER resolved, causing the yield loop in `parallel_stream_generator` to `await` them forever — effectively hanging the stream.

```python
except Exception:
    pass  # Future never set → stream hangs
```

At line 817-818:
```python
except Exception:
    pass  # ← Future not set, yield loop hangs
```

At lines 828-829, after the `except Exception as e` block, control falls through to the `if batch_ok:` check and then to the single-chunk fallback — but if `_fetch_batch` raised an exception, `batch_ok` is still `False` (its initial value). The fallback runs, but if it also fails, the futures stay unresolved.

**Fix:** In every exception path, resolve the futures with `b""` (empty bytes) so the stream can continue with gaps rather than hanging:

```python
except Exception as e:
    logger.error("Bot %d failed batch %d-%d: %s", c_idx, batch_start, batch_end, e)
    for chunk_offset in range(batch_start, batch_end + 1):
        if chunk_offset in results and not results[chunk_offset].done():
            results[chunk_offset].set_result(b"")
```

---

### HIGH Issues

#### [H1] GDrive upload: `os.close(fd)` only in finally block

**File:** `backend/app/gdrive.py` lines 271-323

**Issue:** The file descriptor `fd` is opened with `os.O_DSYNC` for performance, which is correct. However, if an exception occurs inside `_download_slot` that's not caught, or if `asyncio.gather` raises an exception (e.g., `CancelledError`), the `finally` block still runs but `fd` was already set. The real problem is if `dlerr` is set (line 325), `raise dlerr` is called but the fd is already closed by the finally block (lines 321-323) — this is correct. But the `fd` is NOT assigned defensively:

```python
fd = os.open(tmp, os.O_RDWR | os.O_DSYNC)
...
try:
    await asyncio.gather(*tasks)
finally:
    if fd is not None:  # NameError if os.open failed
        os.close(fd)
```

**Fix:** Same as C1 — initialize `fd = None` before `try`.

---

#### [H2] Race condition: `results[chunk_idx]` awaited before being set

**File:** `backend/app/streaming.py` lines 920-941

**Issue:** The yield loop at line 930 does `chunk_data = await results[chunk_idx]`. The workers set futures via `results[current].set_result(data)`. There's a subtle race: if a worker is in the CDN path (`_fetch_batch_cdn`) and gets a `FileReferenceExpired`, it re-fetches the message (line 669-682). During this re-fetch, the future for that chunk is not yet set. Meanwhile, the yield loop has already passed `MIN_PREBUFFER` (which was 2, now 5) and is now awaiting the future. If the re-fetch ALSO fails (returns None), the future is never set.

Furthermore, when a worker encounters a CDN failure (line 702-710) and returns `None`, the caller at line 810-811 falls through to `_fetch_batch`, which also may fail. If both fail, no chunk data is ever put in the future.

**Fix:** Add a timeout to `await results[chunk_idx]`:

```python
chunk_data = await asyncio.wait_for(results[chunk_idx], timeout=60)
```

Or set a default empty result when the worker loop finishes:

```python
finally:
    # Set any remaining unresolved futures to empty bytes
    for idx, fut in list(results.items()):
        if not fut.done():
            fut.set_result(b"")
```

---

#### [H3] No timeout on `_ensure_cdn_session` — can block worker forever

**File:** `backend/app/streaming.py` lines 604-630 and 642-648

**Issue:** In `_fetch_batch_cdn` (line 650), the call `await _ensure_cdn_session()` has no timeout. If the session creation hangs (e.g., `Auth` creation stalling, `ExportAuthorization` hanging), the entire worker thread blocks forever. This starves the task queue since each worker takes a client from the pool.

```python
sess, loc = await _ensure_cdn_session()  # No timeout!
```

**Fix:** Add a timeout:

```python
sess, loc = await asyncio.wait_for(_ensure_cdn_session(), timeout=15)
```

---

#### [H4] JWT `sub` field is string but used as integer everywhere

**File:** `backend/app/auth.py` lines 31, 39, 50, 77, 96, 137

**Issue:** The JWT spec requires `sub` to be a string. The code correctly stores it as a string (line 39: `"sub": str(telegram_id)`), but then ALL consumers convert it back with `int(payload.get("sub"))` (e.g., line 77, 96, 137). This creates a fragile pattern where:
1. `int()` will fail if `sub` is ever missing or None
2. The `verify_token` function at line 70 returns `Optional[int]`, but the payload's `sub` could theoretically be a non-numeric string

More critically, if `sub` is ever `0` or falsy, `int(payload.get("sub")) if payload and payload.get("sub") else None` returns `None` even for a valid token with `sub=0`.

**Fix:** Use a direct conversion with better error handling:

```python
telegram_id = int(payload["sub"]) if payload and "sub" in payload else None
```

---

#### [H5] Folder parent path builds full folder map in memory

**File:** `backend/app/routers/tv.py` lines 182-204

**Issue:** To build the breadcrumb navigation, the code loads ALL of the user's folders into a dict:

```python
all_folders_result = await db.execute(
    select(Folder).where(Folder.user_id == current_user.id)
)
folder_map: dict[int, Folder] = {f.id: f for f in all_folders_result.scalars().all()}
```

For a user with thousands of folders, this loads everything into memory just for a breadcrumb chain. This is an N+1 query pattern where N = depth of folder hierarchy.

**Fix:** Use a recursive CTE to walk up the parent chain:

```python
from sqlalchemy import text
parent_cte = text("""
    WITH RECURSIVE ancestors AS (
        SELECT id, name, parent_id, user_id, created_at, updated_at, 1 as depth
        FROM folders WHERE id = :folder_id
        UNION ALL
        SELECT f.id, f.name, f.parent_id, f.user_id, f.created_at, f.updated_at, a.depth + 1
        FROM folders f
        INNER JOIN ancestors a ON f.id = a.parent_id
    )
    SELECT id, name, parent_id, user_id, created_at, updated_at
    FROM ancestors WHERE depth > 1
    ORDER BY depth DESC
""")
```

---

#### [H6] `web_base_url` hardcoded to a specific domain in config

**File:** `backend/app/config.py` line 101

**Issue:** The production domain `REDACTED_DOMAIN` is hardcoded as the default `web_base_url`. While this is a placeholder in the review, in the actual source it's a real domain name. This is also set in `gdrive_client_redirect_uri` at line 95.

**Fix:** Do not hardcode domains. Use an env var with no default, or `localhost` for development:

```python
web_base_url: str = Field("http://localhost:5173", alias="WEB_BASE_URL")
```

---

#### [H7] Admin delete user doesn't clean up Telegram storage channel

**File:** `backend/app/routers/admin.py` lines 110-124

**Issue:** When an admin deletes a user (`DELETE /api/admin/users/{user_id}`), the user's files are removed from the database via ORM cascade, but the corresponding messages in the Telegram storage channel are NOT deleted. This orphaned media accumulates in the channel forever.

```python
async def admin_delete_user(...):
    user = result.scalar_one_or_none()
    ...
    await db.delete(user)  # Cascade deletes files from DB
    await db.commit()  # But Telegram messages remain!
```

**Fix:** Fetch the user's files first, delete from Telegram, then delete from DB:

```python
files_result = await db.execute(select(File).where(File.user_id == user.id))
msg_ids = [f.channel_message_id for f in files_result.scalars().all()]
await db.delete(user)
await db.commit()
# Best-effort: clean up Telegram
for batch in chunked(msg_ids, 100):
    try:
        await delete_from_storage_channel(batch)
    except Exception:
        pass
```

---

### MEDIUM Issues

#### [M1] `_utcnow()` strips timezone info from datetime

**File:** `backend/app/models.py` lines 11-13

**Issue:** The `_utcnow()` function creates a timezone-aware datetime and then replaces tzinfo with None:

```python
def _utcnow():
    return datetime.now(timezone.utc).replace(tzinfo=None)
```

This creates naive (timezone-unaware) datetime objects in the database. If the database has a column with `TIMESTAMP WITH TIME ZONE` (PostgreSQL), SQLAlchemy may interpret these incorrectly.

**Fix:** Use timezone-aware datetimes or use `func.now()`:

```python
def _utcnow():
    return datetime.now(timezone.utc)
```

And set the column type to `DateTime(timezone=True)`:

```python
created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
```

---

#### [M2] WatchProgress upsert race condition

**File:** `backend/app/routers/files.py` lines 265-312

**Issue:** The upsert pattern is select-then-insert, which has a race window. The code acknowledges this:

```python
# ponytail: upsert -- SELECT first, INSERT on miss, catch race-condition IntegrityError on commit
```

If two concurrent requests do the SELECT simultaneously and both get None, both will try to INSERT, and one will fail with `IntegrityError`. The catch handles this, but it re-does the SELECT again in the except block (lines 297-310), which is a second select-then-update pattern. This can still race.

**Fix:** Use PostgreSQL's `ON CONFLICT` (upsert) natively:

```python
from sqlalchemy.dialects.postgresql import insert as pg_insert
stmt = pg_insert(WatchProgress).values(
    user_id=current_user.id, file_id=file_id, position=progress.position, ...
)
stmt = stmt.on_conflict_do_update(
    constraint="idx_watch_user_file",
    set_={"position": progress.position, ...}
)
await db.execute(stmt)
```

For SQLite compatibility, consider using `merge` or `INSERT OR REPLACE`.

---

#### [M3] Batch file delete silently loses Telegram-side consistency

**File:** `backend/app/routers/files.py` lines 214-247

**Issue:** The `batch-delete` endpoint deletes files from the database first, then tries to delete from Telegram. If the Telegram deletion fails (lines 243-245), the files are already gone from the database but remain in the Telegram channel. There's no retry, no logging, and no compensating action.

```python
for file in files:
    await db.delete(file)
await db.commit()  # DB deleted first!
...
for batch in chunked(msg_ids, 100):
    try:
        await delete_from_storage_channel(batch)
    except Exception:
        pass  # Silently ignored!
```

**Fix:** Consider reversing the order (Telegram first, then DB), or at minimum log the failure:

```python
for batch in chunked(msg_ids, 100):
    try:
        await delete_from_storage_channel(batch)
    except Exception as e:
        logger.error("Failed to delete messages %s from TG: %s", batch, e)
```

---

#### [M4] `tg_client` accessed at module level before initialization

**File:** `backend/app/telegram.py` lines 43-91, referenced by `bot.py` line 18

**Issue:** The `clients` list and `tg_client` are built at **module level** in `telegram.py` (lines 43-91). When `bot.py` is imported (line 24 of `main.py`: `from . import bot`), all this module-level code executes immediately, including creating Pyrogram Client instances. If the `.env` file is missing required settings (like `TELEGRAM_API_ID`), this crashes the import.

Additionally, `tg_client` is accessed in `routers/auth.py` at line 39 and `routers/diagnostic.py` at line 89. If any of these modules are imported before `start_telegram_client()` completes, the client may not be connected yet.

**Fix:** Use a lazy initialization pattern — build clients after `lifespan` starts:

```python
_clients: list[Client] | None = None

def get_clients() -> list[Client]:
    global _clients
    if _clients is None:
        _clients = _build_clients()
    return _clients
```

---

#### [M5] HTTP Range header parsing may return invalid negative start

**File:** `backend/app/routers/streaming.py` lines 27-46

**Issue:** The `parse_range_header` function handles suffix ranges (`bytes=-500`) correctly, but doesn't guard against edge cases like:
- `bytes=100-50` (start > end)
- `bytes=-0` (suffix of 0)
- `bytes=--100` (malformed)

While the caller at line 163 validates `from_bytes > until_bytes`, the check comes AFTER parsing. A malformed range could theoretically produce unexpected values.

**Fix:** Add validation inside the parser:

```python
if start < 0 or end < 0 or start > end:
    raise HTTPException(status_code=416, detail="Invalid range")
```

---

#### [M6] `os.posix_fadvise` is Linux-only — no fallback for other platforms

**File:** `backend/app/gdrive.py` line 298

**Issue:** The call `os.posix_fadvise(fd, offset, len(chunk), os.POSIX_FADV_DONTNEED)` is Linux-specific. If this code runs on macOS or FreeBSD, it will raise `AttributeError: module 'os' has no attribute 'posix_fadvise'`.

```python
os.posix_fadvise(fd, offset, len(chunk), os.POSIX_FADV_DONTNEED)
```

**Fix:** Make it conditional:

```python
if hasattr(os, 'posix_fadvise'):
    os.posix_fadvise(fd, offset, len(chunk), os.POSIX_FADV_DONTNEED)
```

---

### LOW Issues

#### [L1] Module-level `_client_pool` double-checked locking is broken in Python

**File:** `backend/app/streaming.py` lines 377-383

**Issue:** The `get_client_pool()` function uses double-checked locking without a lock:

```python
_client_pool: ClientPool | None = None

def get_client_pool() -> ClientPool:
    global _client_pool
    if _client_pool is None:  # First check — no lock!
        _client_pool = ClientPool(clients)  # Race condition
    return _client_pool
```

In CPython, the GIL makes this safe for simple assignment, but if `ClientPool.__init__` acquires a lock internally (which it does: `self._lock = asyncio.Lock()`), two threads could theoretically create two instances.

**Fix:** Since this is read-mostly after first access, initialize eagerly at module level:

```python
_client_pool = ClientPool(clients)

def get_client_pool() -> ClientPool:
    return _client_pool
```

---

#### [L2] `MAX_CDN_FAILURES = 0` makes CDN path dead code

**File:** `backend/app/streaming.py` line 600

**Issue:** `MAX_CDN_FAILURES = 0` means the CDN session path always returns `None` immediately (because `_cdn_failures >= MAX_CDN_FAILURES` is `0 >= 0 = True`). The entire CDN code path (lines 596-718) is effectively dead code.

```python
MAX_CDN_FAILURES = 0  # CDN never works here
```

**Fix:** Either remove the CDN code entirely (simplifying the codebase) or keep it but set `MAX_CDN_FAILURES` to a tunable config value. The code comment says "CDN never works here" — so delete it:

```python
# Remove _cdn_session, _ensure_cdn_session, _rotate_cdn_bot, _fetch_batch_cdn entirely
```

---

#### [L3] `_parse_mem_env` silently returns int on unparseable input

**File:** `backend/app/status.py` lines 106-111

**Issue:** If `MEMORY` env var is set to an unparseable value like `"auto"` or is empty, `_parse_mem_env` falls through to `return int(val)` which will raise `ValueError`. But `val.strip().upper()` could also match nothing:

```python
def _parse_mem_env(val: str) -> int:
    val = val.strip().upper()
    for suffix in ["GIB", "GI", "GB", "G"]:
        if val.endswith(suffix):
            return int(float(val[: -len(suffix)]) * 1024**3)
    return int(val)  # ValueError if val is "auto" or ""
```

**Fix:** Add a try/except with a sensible default:

```python
try:
    return int(val)
except ValueError:
    return 16 * 1024**3  # 16 GiB default
```

---

#### [L4] `/diag/ping` may block if Telegram is unreachable

**File:** `backend/app/routers/diagnostic.py` lines 69-75

**Issue:** The diagnostic ping endpoint calls `_check_auth(request)` which verifies against `debug_password` but doesn't include any Telegram connectivity check. However, `_check_auth` uses string comparison (`auth != f"Bearer {settings.debug_password}"`) which means if `debug_password` is empty (default), ANY token passes. Worse, this endpoint has no timeout.

```python
@router.get("/ping")
async def diag_ping(request: Request):
    _check_auth(request)
    return {"server_time": time.time(), "status": "ok"}
```

**Fix:** Add a quick check and timeout:

```python
@router.get("/ping")
async def diag_ping(request: Request):
    _check_auth(request)
    try:
        is_connected = await asyncio.wait_for(
            tg_client.is_connected, timeout=5
        )
    except asyncio.TimeoutError:
        is_connected = False
    return {"server_time": time.time(), "status": "ok", "tg_connected": is_connected}
```

---

#### [L5] Debugging artifacts committed to source tree

**Files:** `debug_prompt.txt`, `doubt.txt` at repo root

**Issue:** These files appear to contain debugging notes or prompts. They should not be in version control:

- `/home/thirupathi/Desktop/Aruvi/debug_prompt.txt`
- `/home/thirupathi/Desktop/Aruvi/doubt.txt`

**Fix:** Add to `.gitignore` and remove from tracking:

```bash
git rm --cached debug_prompt.txt doubt.txt
echo "debug_prompt.txt" >> .gitignore
echo "doubt.txt" >> .gitignore
```

---

## Performance Review

### Streaming Architecture (Good)
- Multi-client parallel chunk fetching with weighted-least-loaded scheduler — **excellent design**
- CDN session with lazy init and bot rotation — **good**, though currently disabled
- Yield smoothing with prebuffer — **good for TTFB**
- Backpressure semaphore — **good OOM prevention**, but leak-prone (see C2)
- `stream_file` global semaphore (LIMIT=5) — **good** for controlling concurrent streams

### Cache Design
- **RAM-only ChunkCache** per video: 2GB max with FIFO eviction — **good**
- **CacheManager** with `exclude_keys` for active streams in OOM guard — **good**
- **Msg cache** TTL of 1 hour with max 5000 entries — **good**
- **Missing**: No cache prefetch during idle time

### Database Queries
- **N+1 in TV parent path**: Loads ALL folders to build breadcrumbs — **fix with CTE** (see H5)
- **Admin users query**: Outer joins and counts in one query — **good**
- **Files list**: Separate count + data queries — **good**, avoids expensive window queries
- **Folder trees**: Single query with outerjoin + group by, tree built in memory — **good** for typical folder counts

### Bottlenecks
1. **SQLite WAL mode**: Good for single-server, but `pool_pre_ping=True` + `check_same_thread=False` means concurrent async requests may still collide on SQLite's single-writer lock
2. **`async_session` per request**: Creating a new session per request is correct but means no prepared statement caching across requests
3. **Streaming CDN code is dead** (see L2) — remove it to reduce complexity
4. **Bot 0 always handles CDN refresh** — the other 13 bots are underutilized for cache/CND operations

### Recommendations
1. Remove dead CDN code (saves ~120 lines of complex error-prone code)
2. Replace N+1 folder path with recursive CTE
3. Add timeout to all `await` on futures in the yield loop
4. Use PostgreSQL in production — SQLite WAL has write-contention limits for concurrent streaming

---

## Security Audit

### Dependencies (from requirements.txt)

| Package | Version | Notes |
|---------|---------|-------|
| `kurigram[fast]` | ≥2.2.23 | Pyrogram fork — review for known vulns |
| `fastapi` | ≥0.109.0 | Modern, well-audited |
| `python-jose[cryptography]` | ≥3.3.0 | JWT library — has had past CVEs |
| `google-api-python-client` | ≥2.120.0 | Google client — requires `GOOGLE_API_KEY` scoping |

### Secrets Management
- ✅ API keys loaded from `.env` via pydantic-settings
- ✅ `.env` in `.gitignore` (root-level; verify subdirectory)
- ✅ JWT auto-generated if not set
- ✅ Session strings stored in-memory, not on disk

### OWASP Coverage
- ✅ **A01: Broken Access Control** — Admin check on `get_current_admin`, user-scoped queries
- ✅ **A03: Injection** — SQLAlchemy ORM (parameterized), `escape_like` for ILIKE
- ✅ **A05: Security Misconfiguration** — Security headers middleware (HSTS, X-Frame, etc.)
- ✅ **A07: XSS** — No `dangerouslySetInnerHTML` equivalents
- ⚠️ **A02: Cryptographic Failures** — JWT `sub` type confusion (H4), hardcoded admin ID (C3)
- ⚠️ **A04: Insecure Design** — Rate limiting on auth endpoints but not on streaming

### Findings
1. **Hardcoded admin ID** — C3 (Critical)
2. **JWT sub type mismatch** — H4 (High)
3. **Debug password empty default** — if `DEBUG_PASSWORD` is not set, `/diag/*` endpoints are unprotected
4. **`REDACTED_DOMAIN` hardcoded** — domain leak in source
5. **No CORS for production** — allowed origins include `*` fallback patterns. Verify the allowed origins list in production.

---

## Sources

1. `backend/app/main.py` — Application entrypoint, lifespan, middleware, SPA serving
2. `backend/app/config.py` — Pydantic settings with env overrides
3. `backend/app/database.py` — Async SQLAlchemy engine with SQLite/PostgreSQL support
4. `backend/app/models.py` — SQLAlchemy ORM models for User, File, Folder, WatchProgress, LoginCode
5. `backend/app/schemas.py` — Pydantic request/response schemas
6. `backend/app/auth.py` — JWT authentication utilities
7. `backend/app/telegram.py` — Telegram client pool, lifecycle, message cache
8. `backend/app/streaming.py` — Multi-client parallel streaming engine (1004 lines)
9. `backend/app/patch.py` — Patched Pyrogram client with wait_for_message support
10. `backend/app/rate_limit.py` — SlowAPI rate limiter configuration
11. `backend/app/status.py` — Cgroup-aware CPU/RAM/network monitoring + OOM guard
12. `backend/app/bot.py` — Telegram bot command and callback handlers
13. `backend/app/services.py` — Shared business logic and DB queries
14. `backend/app/utils.py` — Filename sanitization
15. `backend/app/gdrive.py` — Google Drive OAuth and two-phase upload
16. `backend/app/routers/__init__.py` — Router exports
17. `backend/app/routers/streaming.py` — Stream/file/thumbnail endpoints
18. `backend/app/routers/files.py` — File CRUD and watch progress
19. `backend/app/routers/folders.py` — Folder CRUD with recursive CTEs
20. `backend/app/routers/auth.py` — Auth endpoints (login, refresh, verify-code)
21. `backend/app/routers/tv.py` — TV-optimized browse/search endpoints
22. `backend/app/routers/admin.py` — Admin stats/user management
23. `backend/app/routers/gdrive.py` — GDrive OAuth callback handler
24. `backend/app/routers/diagnostic.py` — Debug/diagnostic endpoints
25. `backend/app/routers/legal.py` — TOS/privacy policy routes
26. `backend/requirements.txt` — Python dependencies
27. `env.example` — Environment variable template
28. `AGENTS.md` — Deployment documentation for HidenCloud

---

## Verdict: **REQUEST CHANGES**

### Issue Count by Severity
| Severity | Count |
|----------|-------|
| CRITICAL | 4 |
| HIGH | 7 |
| MEDIUM | 6 |
| LOW | 5 |
| **Total** | **22** |

### Top 5 Things to Fix Before Merge
1. **C1 + H1**: Fix file descriptor handling in GDrive download (fd leak can crash on concurrent GDrive uploads)
2. **C2**: Fix `_backpressure` semaphore leak in CDN failure path (causes total stream blockage after 2000 leaks)
3. **C3**: Remove hardcoded admin Telegram ID (security exposure)
4. **C4**: Ensure all futures are resolved on error paths (prevents stream hangs)
5. **H2**: Add timeout to `await results[chunk_idx]` in yield loop (prevents stream deadlock on missing futures)
