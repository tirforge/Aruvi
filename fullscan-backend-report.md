# Full-scan backend report — `backend/` audit

- **Scope:** `backend/app` (34 .py), `backend/tests` (5 .py), `backend/run.py`, `backend/run_nouvloop.py` — **41 Python files, ~16.9k LOC**. Vendored/build output untouched (`app/static/vendor/`, `app/static/assets/`).
- **Method:** full read of all 41 files (parallel subagent sweep + line-by-line verification of every candidate finding against the code before editing).
- **Verdict: NOT CLEAN — 32 issues fixed** (branch `opencode/fullscan-backend-12`). A further set of candidates was reviewed and deliberately left unchanged (listed at the bottom with reasons).

## Verification

- `python3 -m compileall -q app tests run.py run_nouvloop.py` → OK.
- Stdlib-only runtime checks (no backend deps installed in this runner): `build_static_allowlist` dotfile/`.gz` exclusion OK; `DiskChunkCache.chunk_indices` skips bad names OK; `sweep()` OK.
- Full `pytest` / ruff / mypy could not run here (fastapi, slowapi, sqlalchemy, etc. not installed); CI on the PR runs them. `backend/tests/test_fixes.py` was updated for the one signature change (`POST /auth/refresh`).

## Fixed (file:line = location of the fix)

### High severity
1. `backend/run_nouvloop.py:38` — housekeeping `active` set built as `(info["chat_id"], mid)` where `mid` is already the `(chat_id, message_id)` key → never matched → live streams' RAM caches evicted mid-stream. Now `set(_forward_streams.keys())` (matches `run.py` + `diagnostic.py`).
2. `backend/app/streaming.py:1801` — prebuffer disk path checked `results[cidx].done()` then awaited disk I/O, then unguarded `set_result` → `InvalidStateError` aborts stream on worker race. Re-checks `done()` after the await.
3. `backend/app/streaming.py:1636/1668/1710` — three fallback single-chunk fetches ran `stream_media` with no timeout and raw `async with semaphore` (unlike `_fetch_one`) → stuck media session wedges the worker forever. Wrapped in `asyncio.timeout(STREAM_CHUNK_TIMEOUT_S)`.
4. `backend/app/routers/streaming.py:781` — cast ffprobe `proc.communicate()` with no timeout → hung ffprobe hangs the request + full-file Telegram pull. Bounded at 60s with kill + feed-task cleanup.
5. `backend/app/routers/streaming.py:1084` — remux loop read only `stdout` while `stderr=PIPE` → ffmpeg blocks on a full stderr pipe (deadlock). Added concurrent stderr drain; `finally` now awaits cancelled feed/stderr tasks and `proc.wait()` (was: un-awaited cancel + `terminate()` → zombie ffmpeg).
6. `backend/app/database.py:228` — boot migration loaded the entire `files` table with `.all()` (OOM on large libraries). Batched `LIMIT/OFFSET` walk.
7. `backend/app/database.py:246` — `INSERT app_meta` without `ON CONFLICT` → dual-boot unique-violation crash. `ON CONFLICT (key) DO NOTHING` (valid on SQLite + Postgres).
8. `backend/app/gdrive.py:286` — temp path `{msg.id}_{int(time())}.tmp` collides for concurrent same-message uploads → cross-corruption. Added pid + `secrets.token_hex(4)`.

### Medium severity
9. `backend/app/routers/streaming.py:101` — unparseable `Range` fell through to serving the full file (200) instead of 416; both callers already handle `None` → 416. Return type fixed to `tuple[int,int] | None`.
10. `backend/app/streaming.py:1451` — `_fetch_one` returned `b""` when Telegram yielded nothing; callers test `is not None`, so empty chunks resolved/yielded as valid data. Now returns `None` (retry path).
11. `backend/app/streaming.py:1047` — `_fetch_message(force=True)` captured `now` before the coalescing lock; queued waiters over-throttled on a stale timestamp and could return a dead cached Message. Clock re-read inside the lock.
12. `backend/app/streaming.py:1001` — `_prune_msg_state` only ran when `_msg_cache` exceeded cap, so `_msg_last_force`/`_msg_refresh_locks`/poison keys grew unbounded; orphan keys now purged too.
13. `backend/app/streaming.py:631` — prefetch `finally` guarded only `_prefetch_tasks` with `is this_task` but unconditionally wiped hwm/cursor/activity of a newly installed task. All pops guarded.
14. `backend/app/streaming.py:1938` — disk TTL touched once at stream start; >30min movies went stale mid-stream and got swept while reading. Touch every 100 chunks in the yield loop.
15. `backend/app/streaming.py:245` — `_do_restart` cleared prefetch maps but left `_prefetch_tasks` running against cleared state. Cancels tasks + clears activity map.
16. `backend/app/disk_cache.py:83` — one non-numeric `*.bin` name discarded the whole chunk index (`return frozenset()`) → full Telegram refetch. Bad names skipped per-entry.
17. `backend/app/disk_cache.py:253` — unguarded `p.stat()` sort key in `sweep` → concurrent `put` aborts the whole sweep. `_safe_mtime`/`_safe_size` helpers.
18. `backend/app/telegram.py:164` — non-"already connected" `ConnectionError` re-raised immediately, skipping the remaining backoff attempts every other transient gets. Retries with backoff.
19. `backend/app/routers/auth.py:82` — `POST /refresh` had no rate limit while `/generate-code`/`/verify-code` do. Added `@limiter.limit("30/minute")` (+ `Request` param per repo convention).
20. `backend/app/auth.py:118`, `backend/app/routers/auth.py:94` — forged JWT with non-numeric `sub` raised 500 via unguarded `int()`. Fail closed (`None` → 401).
21. `backend/app/routers/auth.py:131/305` — naive-vs-aware `expires_at` comparison raises `TypeError` (500) on Postgres `timestamptz` round-trips (live uses asyncpg). New tz-normalizing `_is_expired()` helper.
22. `backend/app/routers/streaming.py:462` — thumbnail retry matched only literal `AUTH_BYTES_INVALID`; `FileReference*`/`AuthKeyUnregistered` siblings 500'd instead of one fresh-message retry. Marker set widened.
23. `backend/app/config.py:35` — JWT secret file created 644-by-umask then `chmod 600` (readable window). Atomic `os.open(..., 0o600)` creation.
24. `backend/app/routers/subtitles.py:258` — provider subtitle body buffered uncapped via `.content` (OOM). Capped (5 MB) streaming read → 502 past the cap.
25. `backend/app/routers/folders.py:186` — concurrent same-name create raced check-then-insert → 500. `IntegrityError` → 400.
26. `backend/app/schemas.py:212` — `BatchMoveRequest.ids` unbounded (100k-id `IN` clause). `max_length=500`.
27. `backend/app/routers/files.py:287` — `batch-delete` body list unbounded. Cap 500 → 400.

### Low severity
28. `backend/app/auth.py:27` — `_last_active_touch` throttle map never evicted. Hourly prune of >1h-idle entries.
29. `backend/app/telegram.py:245` — reconnect cooldown only checked pre-lock; re-checked post-lock.
30. `backend/app/disk_cache.py:208/293` — `sweep()` reported only global-cap evictions; TTL + per-video evictions now counted in `freed`.
31. `backend/app/status.py:121` — bad `$MEMORY` value 500'd `/api/status`. Falls back to 16 Gi default.
32. `backend/app/gzip_middleware.py:83`, `backend/app/static_allowlist.py:31`, `backend/app/rate_limit.py:10/24`, `backend/app/routers/folders.py:345+`, `backend/app/routers/files.py:214/449/484`, `backend/app/bot.py:1500/1555`, `backend/app/routers/setup.py:39/60`, `backend/app/schemas.py:55/61/138`, `backend/app/routers/tv.py:148`, `backend/app/routers/grab.py:83` — stale-ETag-on-gzip strip; dotfile exclusion; `_is_ip` TypeError guard + `::ffff:127.0.0.1` loopback; user-scoped bulk folder/file updates + race-safe re-fetch (`one_or_none` → 404); setup TTL + `get_running_loop`; input-only schema bounds (folder names 1–200, progress `ge=0`, tv `q`/`file_name` length caps).

## Reviewed and deliberately NOT changed

- Query-param auth tokens (`auth.py:117/153`, `bot.py` web URLs): required by media players/TV clients that can't set headers; download tokens are file-bound + short/long-lived by design.
- `ver`-less tokens bypassing `auth_version` (`auth.py:135/191`, `routers/auth.py:97`, `routers/gdrive.py:121`): forcing `ver` would log out every legacy session — needs a migration, not a drive-by.
- Token lifetimes (7d access / 28d refresh / 30d download), plaintext `gdrive_token`, 6-char login codes @ 80/min: product trade-offs; rate limits + rotation already mitigate. Changing lifetimes/entropy breaks clients.
- Refresh double-submit race (`routers/auth.py:103`): fixing needs `SELECT … FOR UPDATE`, which SQLite (test/dev) doesn't support — dialect-sensitive, out of scope for a safe sweep.
- `diag_bot_send`, `diag/stream` arbitrary chat/msg, 2 GB `diag/gen` (`main.py:328`, `diagnostic.py:56/124`): gated by `DEBUG_PASSWORD` operator secret — debug tools by design.
- `setup.py` SMS-via-server-IP (`setup.py:85/93`): router is off unless operator sets `SETUP_PASSWORD` (fail-closed, documented).
- Grabber flood-sleep holding pool slots, global `_search_lock`, auto-join/channel-click logic (`grabber.py`): core bot behavior; sleeps honor Telegram flood-waits, pool has 11 bots.
- `bot.py` `int(callback.split)` sites: contained by `@_log_exceptions` (logged, no crash/hang); per-site guards = churn.
- `md_safe` backtick-only escaping (`utils.py:45`): documented intentional rendering trade-off.
- Remux `Content-Range` on synthetic fMP4 (`routers/streaming.py:1009`): best-effort Cast-seek hack; "fixing" breaks Cast seeking.
- Stall-detector first-chunk blind spot, worker-drain 5s abandon (`streaming.py:1365/1931`): deliberate bounded trade-offs, already logged.
- `admin/users` full-table dump, `tv.py` folder breadth, `gdrive` mid-upload 401, `database.py` ssl string, `_warmup_messages` helper RPCs: by design / env-specific / already documented in code comments.
