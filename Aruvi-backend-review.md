# Aruvi Backend Code Review — Streaming & Database

## Summary

Reviewed the Aruvi-backend Python/FastAPI codebase focusing on streaming logic (`streaming.py`), database layer (`database.py`, `models.py`), and the bot/patch layer. Found **one CRITICAL** bug (NameError in listener cleanup), **two HIGH** bugs (semaphore deadlock risk, missing ownership check), and several MEDIUM issues in streaming reliability and DB migration safety.

---

## Key Findings

- **CRITICAL**: `patch.py` — `wait_for_message`, `wait_for_inline_query`, `wait_for_inline_result` use undefined variable `key` in `finally` block → `NameError` on timeout/cancel
- **HIGH**: `streaming.py` — backpressure semaphore acquired inside per-client semaphore → worker deadlock if yield loop stalls
- **HIGH**: `bot.py` — `movehere` callback does not verify file ownership before moving
- **MEDIUM**: `streaming.py` — `_fetch_batch` timeout break leaves partial batch chunks unresolved but some backpressure permits acquired
- **MEDIUM**: `database.py` — auto-migration has no exception handling → startup fails on migration error
- **MEDIUM**: `streaming.py` — prefetch uses arbitrary connected client whose file reference may differ from the serving client
- **MEDIUM**: `patch.py` — `load_session()` calls `super().load_session()` which doesn't exist on Pyrogram's Client

---

## Detailed Analysis

### CRITICAL: Patch listener cleanup uses undefined variable

**Files:** `patch.py` lines 97, 110, 122

**Issue:** Three methods (`wait_for_message`, `wait_for_inline_query`, `wait_for_inline_result`) define a `finally` block that references `key`, but `key` is never assigned in any of them:

```python
async def wait_for_message(self, chat_id, ...):
    ...
    self.listeners.update({str(chat_id): ...})
    try:
        return await asyncio.wait_for(future, timeout)
    finally:
        if not future.done():
            future.cancel()
        self.remove_listener(key, future)  # NameError! key is undefined
```

`wait_for_callback_query` (line 78) correctly uses `key`, but the other three copy-pasted methods forgot to assign `key = str(chat_id)` / `key = str(user_id)`.

**Impact:** When a listener times out or is cancelled (60s timeout expired, or `/cancel` command), the `finally` block throws `NameError`, which:
1. Silently fails to clean up the listener from `self.listeners`
2. Leaks the future (never removed from dict)
3. Over time, `self.listeners` accumulates dead entries → memory leak

**Suggestion:** Fix each method:

```python
# In wait_for_message:
key = str(chat_id)
# In wait_for_inline_query / wait_for_inline_result:
key = str(user_id)
```

---

### HIGH: Backpressure semaphore acquired inside per-client semaphore (deadlock risk)

**File:** `streaming.py` lines 553-580

**Issue:** `_fetch_batch` calls `_backpressure.acquire()` **inside** the `async with sem:` block (per-client concurrency semaphore):

```python
async def _fetch_batch(batch_start, batch_end, cl, msg, sem, timeout=30):
    ...
    async with sem:                         # ↑ per-client semaphore held
        async for part in cl.stream_media(...):
            ...
            await _backpressure.acquire()   # ↓ blocks waiting for yield loop
            ...
```

If the yield loop is slow (e.g., HTTP response to client is throttled, client on slow connection, or 2000 chunks already in-flight), `_backpressure` fills up, and `_backpressure.acquire()` blocks. While blocked, the worker **holds the per-client semaphore** (`sem`). Other workers assigned to the same bot cannot dispatch any work because the semaphore is stuck. This effectively freezes that client.

**Impact:** A single slow consumer can block all other streams using that bot. With 14 bots but only 5 per-client concurrency, one stuck worker consumes 20% of that bot's capacity.

**Suggestion:** Move backpressure acquire **outside** the per-client semaphore:

```python
async def _fetch_batch(batch_start, batch_end, cl, msg, sem, timeout=30):
    ...
    async with sem:
        async for part in cl.stream_media(...):
            data = bytes(part)
            video_cache.put(current, data)
            if not results[current].done():
                results[current].set_result(data)
            current += 1
    # Backpressure is now applied after releasing the per-client semaphore
    for _ in range(current - batch_start):
        await _backpressure.acquire()
```

Or redesign so backpressure is applied in the yield loop only (which already happens at line 771 — `_backpressure.release()`). The acquire in the worker was meant to prevent workers from getting too far ahead — but it creates this deadlock risk.

---

### HIGH: `movehere` callback missing file ownership check

**File:** `bot.py` lines 1192-1219

**Issue:** The `movehere:` callback data handler fetches the file by ID **without verifying the file belongs to the calling user**:

```python
elif data.startswith("movehere:"):
    parts = data.split(":")
    file_id = int(parts[1])
    folder_id = int(parts[2]) if parts[2] != "0" else None

    async with async_session() as db:
        result = await db.execute(select(File).where(File.id == file_id))  # ← no user filter!
        file = result.scalar_one_or_none()
```

While the callback data is generated server-side and contains file_ids that were previously validated as owned by the user (in the `move:` handler), the `movehere:` handler itself does not re-validate. If an attacker crafts a callback with `movehere:{other_user_file_id}:{folder_id}`, they could move another user's file.

**Impact:** Low in practice (callback data is opaque to users), but a defense-in-depth violation.

**Suggestion:** Add user ownership query:

```python
result = await db.execute(
    select(File).where(File.id == file_id, File.user_id == user.id)
)
```

---

### MEDIUM: `_fetch_batch` timeout break leaves backpressure imbalance

**File:** `streaming.py` lines 553-580

**Issue:** When the per-batch timeout fires mid-stream:

```python
if time.perf_counter() - t0 > timeout:
    logger.warning("Batch %d-%d timeout after %.0fs ...", ...)
    break  # exits the async for loop
```

For chunks that were successfully fetched before the break, `_backpressure.acquire()` was called. But the `results[current]` was `set_result(data)`. In the yield loop, `_backpressure.release()` is called only for non-cached chunks (line 770-771). Since these chunks are uncached, each will get a release. **But** the fallback in the worker (line 665-713) calls `_fetch_one` for each remaining chunk, which also calls `_backpressure.acquire()`. For chunks already set by the partial batch, the fallback skips (`results[chunk_offset].done() → continue`), so no double-acquire. The count should balance.

However, if the batch **partially** fetches chunk N (e.g., timeout fires in the middle of `stream_media` yielding chunk N's data), the chunk might have been set with partial data. The `data = bytes(part)` should yield full chunks, but if stream_media's internal batching was interrupted mid-chunk, `data` could be smaller than 1MB. The yield loop then yields a truncated chunk, and the client interprets it as end-of-stream or corrupt data.

---

### MEDIUM: Auto-migration has no error handling

**File:** `database.py` lines 83-118

**Issue:** The `_migrate` function runs arbitrary ALTER TABLE statements without exception handling:

```python
async with engine.begin() as conn:
    def _migrate(sync_conn):
        inspector = sa_inspect(sync_conn)
        for table_name, table in Base.metadata.tables.items():
            existing = {c["name"] for c in inspector.get_columns(table_name)}
            for col in table.columns:
                if col.name not in existing:
                    ...
                    sync_conn.exec_driver_sql(sql)  # could raise!
    await conn.run_sync(_migrate)
```

If any ALTER TABLE fails (e.g., type mismatch, existing data violates NOT NULL, concurrent schema change), the entire startup fails.

**Impact:** A failed migration blocks the entire app from starting.

**Suggestion:** Wrap each individual ALTER in a try/except, log and continue:

```python
for col in table.columns:
    if col.name not in existing:
        try:
            sync_conn.exec_driver_sql(sql)
        except Exception as e:
            logger.warning("Migration failed for %s.%s: %s", table_name, col.name, e)
```

---

### MEDIUM: Prefetch uses arbitrary client, may cause FileReferenceInvalid

**File:** `streaming.py` lines 460-463

**Issue:** `prefetch_first_batch` picks the first connected client (or the provided one):

```python
prefetch_client = next((c for c in clients if c.is_connected), None)
if not prefetch_client:
    prefetch_client = client
```

The prefetch client may not be the same as the client(s) used later by the workers. While the chunk data (bytes) is shared via `video_cache`, the file reference used by the prefetch client might differ from what workers have. If a worker later gets `FileReferenceInvalid` on its own reference, it retries with its own message fetch — which is fine. But if the worker finds the chunk in `video_cache` (prefetched), it serves data without verifying its own file reference.

No actual problem here — the bytes are valid regardless of which client fetched them. FileReferenceInvalid only affects RPC calls, not cached byte data.

---

### MEDIUM: `patch.py` `load_session` calls nonexistent super method

**File:** `patch.py` lines 22-28

**Issue:**

```python
async def load_session(self):
    ...
    await super().load_session()
```

Pyrogram's `Client` class does not have a `load_session` method. The `Client.__init__` creates a `storage` object, but there's no async `load_session()` on `Client`. This would call the next in the MRO — likely `object` which has no `load_session` either → `AttributeError`.

**Impact:** Calling `load_session()` on a `PatchedClient` would crash. Examining usage: this method is never called in the codebase (seems like leftover scaffolding). But adding it to the class with a broken super call is a ticking bomb if anyone calls it.

**Suggestion:** Either implement the method properly or remove it.

---

### MEDIUM: `_byte_accurate_file_stream` unused in production path

**File:** `streaming.py` lines 357-440

This function implements CDN-avoiding byte-accurate streaming by directly calling `upload.GetFile` with precise offsets. It handles `FileReferenceExpired`, `AuthKeyUnregistered`, and `FileCdnRedirect`. 

**Issue:** This function is only used by the GDrive upload path and diagnostic streaming, not the main streaming flow (`parallel_stream_generator` → `stream_file`). The main flow uses Pyrogram's `stream_media` which routes through Telegram CDN. This means:

- The main streaming path uses Telegram CDN (faster, higher latency variance)
- The byte-accurate path is only for GDrive uploads (where CDN tokens expire)

No bug per se, but worth noting that the production streaming path doesn't benefit from this robust byte-accurate handling.

---

### LOW: Docstring/code mismatch — `BATCH_SIZE` value

**File:** `streaming.py` line 14

```python
BATCH_SIZE = 10
```

`AGENTS.md` documents `BATCH_SIZE=15`. Code says 10. Not a bug but a documentation drift.

---

### LOW: Redundant `from sqlalchemy import update` imports in `bot.py`

Multiple places in `bot.py` import `update` inside the callback handler (lines 1040) and in `files.py` at the top level. Not harmful, just inconsistent.

---

## Summary

| Severity | Count | Key Issues |
|----------|-------|------------|
| CRITICAL | 1 | `patch.py` NameError on listener timeout (affects all interactive bot features: rename, move, create folder) |
| HIGH | 2 | Backpressure deadlock in streaming; Missing ownership check in move handler |
| MEDIUM | 5 | Partial batch data truncation; Migration error handling; Prefetch client mismatch; Nonexistent super method; Unused byte-accurate path |
| LOW | 2 | Docstring mismatch; Redundant imports |

### Top 3 to fix before next deploy

1. **`patch.py` listener cleanup** — fix `key` variable in all three `finally` blocks. This breaks rename/move/create-folder when they time out or the user sends `/cancel`.
2. **`streaming.py` backpressure ordering** — move `_backpressure.acquire()` outside the per-client semaphore to prevent worker deadlock.
3. **`bot.py` movehere ownership check** — add `File.user_id == user.id` filter to prevent unauthorized file moves.

---

## Sources

1. `/home/thirupathi/Desktop/Aruvi/Aruvi-backend/backend/app/streaming.py` — Main streaming logic (841 lines)
2. `/home/thirupathi/Desktop/Aruvi/Aruvi-backend/backend/app/database.py` — DB setup and auto-migration
3. `/home/thirupathi/Desktop/Aruvi/Aruvi-backend/backend/app/models.py` — SQLAlchemy models
4. `/home/thirupathi/Desktop/Aruvi/Aruvi-backend/backend/app/patch.py` — PatchedClient with listener support
5. `/home/thirupathi/Desktop/Aruvi/Aruvi-backend/backend/app/bot.py` — Telegram bot handlers
6. `/home/thirupathi/Desktop/Aruvi/Aruvi-backend/backend/app/routers/streaming.py` — Streaming HTTP endpoints
7. `/home/thirupathi/Desktop/Aruvi/Aruvi-backend/backend/app/routers/files.py` — File management endpoints
8. `/home/thirupathi/Desktop/Aruvi/Aruvi-backend/backend/app/services.py` — Business logic
9. `/home/thirupathi/Desktop/Aruvi/Aruvi-backend/backend/app/telegram.py` — Telegram client pool
10. `/home/thirupathi/Desktop/Aruvi/Aruvi-backend/backend/app/auth.py` — JWT auth
11. `/home/thirupathi/Desktop/Aruvi/Aruvi-backend/backend/app/status.py` — OOM guard and monitoring
12. `/home/thirupathi/Desktop/Aruvi/Aruvi-backend/backend/app/config.py` — Settings