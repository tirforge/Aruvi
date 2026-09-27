# Fullscan backend report — 2026-09-27

Scope: strict `backend/` only. No other top-level dirs, `.github/`, or
vendored/build output (`backend/app/static/vendor/`, `backend/app/static/assets/`)
touched.

## Dirs scanned

- `backend/app/` (incl. `backend/app/routers/`)
- `backend/tests/`
- `backend/*.py`, `backend/sql/`, `backend/requirements.txt`,
  `backend/pyproject.toml`, `backend/pytest.ini`

## File count

- 76 files total under `backend/`
- 43 Python files audited (`app/*.py`, `app/routers/*.py`, `run.py`,
  `run_nouvloop.py`, `tests/*.py`) ≈ 16.4k LOC
- Excluded from audit/fixes (vendored/build output): everything under
  `backend/app/static/vendor/` and `backend/app/static/assets/`
  (precompressed `.gz` siblings + bundled JS/CSS/fonts/images)

## Verdict: NOT CLEAN — 24 findings fixed (see PR), rest triaged below

Verification available in this runner: `python3 -m compileall` — PASS on
`backend/app`, `backend/tests`, `backend/run.py`, `backend/run_nouvloop.py`.
`pytest`/`ruff`/`slowapi` are NOT installed in this runner, so the test suite
could not be executed here (CI on the PR runs it). `test_fixes.py` was updated
to match the new `/refresh` signature (real starlette `Request`, same pattern
the suite already uses for `/verify-code`).

## Fixed (in PR `opencode fullscan: backend fixes`)

1. `backend/app/routers/auth.py:71` — `POST /auth/refresh` had no rate limit
   (every attempt = DB lookup + SHA256). Added `@limiter.limit("30/minute")`
   with `request: Request`; renamed body param to `refresh_request`.
2. `backend/app/routers/auth.py:359` — legacy `POST /auth/code` relied on
   incidental coverage via delegation. Added explicit `@limiter.limit("80/minute")`.
3. `backend/tests/test_fixes.py:141` — updated direct `refresh_token(...)`
   calls to pass a real starlette `Request` (required by the new limiter).
4. `backend/app/auth.py:105` — `verify_token`: `int(sub)` raised
   `ValueError` → 500 on non-numeric `sub`. Now returns `None`.
5. `backend/app/routers/setup.py:86` — session-binding token truncated to 64
   bits (`uuid4().hex[:16]`). Now full 128-bit hex.
6. `backend/app/routers/setup.py:101,131,134` — raw Telegram exception text
   returned to caller (phone/api details, flood-wait state, 2FA oracle).
   Now generic messages + server-side `_log.warning`.
7. `backend/app/routers/setup.py:132` — outer `except Exception` swallowed the
   intentional `401 need_password` / `403` into `400`. Added
   `except HTTPException: raise` re-raise guard.
8. `backend/app/rate_limit.py:24` — loopback check missed
   `::ffff:127.0.0.1` (IPv4-mapped loopback). Added.
9. `backend/app/routers/streaming.py:89,97` — Range/suffix regexes unanchored:
   trailing garbage (`bytes=0-10xxx`) silently accepted. Anchored with `\s*$`.
10. `backend/app/routers/streaming.py:382` — off-by-one: `until_bytes > file_size`
    can never fire (`until` is inclusive, max valid is `file_size - 1`).
    Now `>= file_size`.
11. `backend/app/routers/streaming.py:194` — admin/debug 500 leaked
    `str(e)` internals. Now generic detail (still `logger.exception` server-side).
12. `backend/app/routers/streaming.py:991` — cast path `ZeroDivisionError` on
    0-byte file (`start_byte / file.file_size`). Guarded with `file.file_size`.
13. `backend/app/routers/streaming.py:1068` — ffmpeg child left zombie on
    disconnect (`terminate()` without `wait()`). Now
    `await asyncio.wait_for(proc.wait(), timeout=5)`.
14. `backend/app/disk_cache.py:66` — `os.scandir()` iterator never closed (fd
    leak until GC). Now `with os.scandir(d) as it:`.
15. `backend/app/telegram.py:375` — logged 8-char bot-token prefix to diag log.
    Removed (also removes a latent `NameError` on `me` when `get_me()` fails).
16. `backend/app/gdrive.py:293,308` — temp upload predictable
    (`{msg.id}_{time()}.tmp`, no `O_EXCL`) and world-readable (`0o644`).
    Now `+ secrets.token_hex(8)` suffix, `O_EXCL`, `0o600`.
17. `backend/app/gdrive.py:51` — OAuth nonce store prune-only-expired, no max.
    Added 5000-entry hard cap (oldest evicted first).
18. `backend/app/main.py:406` — SPA catch-all traversal guard checked literal
    `..` only (encoded `..`, absolute paths, backslashes bypass). Now also
    checks `unquote()`d path + realpath containment inside `app/static`.
19. `backend/app/routers/files.py:283`, `backend/app/routers/folders.py:385` —
    batch-delete accepted unbounded id lists (DoS). Capped at 500 with 400.
20. `backend/app/routers/tv.py:148` — TV search `q` had no `max_length`. Now
    `max_length=200`.
21. `backend/app/status.py:413` — forward streams merged by `message_id` only;
    same-id movies in different chats collided. Now keyed by
    `(chat_id, message_id)`.
22. `backend/app/status.py:118` — malformed `MEMORY` env (`int()`/`float()`
    `ValueError`) 500'd `/status`. Now falls back to 16 GiB.
23. `backend/run_nouvloop.py:39` — housekeeping built the active-set with the
    wrong key shape (`(info["chat_id"], mid)` over `.items()`), so active
    streams' caches could be evicted. Aligned with `run.py`:
    `set(_forward_streams.keys())`.
24. `backend/run.py:74` — `int(os.environ.get("SERVER_PORT", ...))` crashed on
    garbage. Now `_server_port()` with 7680 fallback.
25. `backend/app/streaming.py:18`, `backend/app/main.py:12`,
    `backend/run.py:17`, `backend/run_nouvloop.py:13` — bare
    `ctypes.CDLL("libc.so.6")` killed the whole backend at import on
    non-glibc (Alpine/macOS). Now `try/except OSError → None` with guarded
    `malloc_trim` call sites.
26. `backend/app/streaming.py:45` — all `STREAM_*` env-int knobs
    (`BATCH_SIZE`, `STREAM_RAM_PER_VIDEO_MB`, `STREAM_INFLIGHT_MB`,
    `STREAM_MAX_CONCURRENT`, `STREAM_PREFETCH_*`, `STREAM_BATCH_*`,
    `STREAM_SEM_WAIT_TIMEOUT_S`, `STREAM_CHUNK_TIMEOUT_S`,
    `STREAM_MEM_PRESSURE_RATIO`) crashed the import on garbage and accepted
    `0`/negative (deadlocks `Semaphore(0)`). Now `_env_int()` with defaults.
27. `backend/app/grabber.py:205` — `_collect_sessions` swallowed config
    errors with bare `pass`. Now `_log.warning`.
28. `backend/app/routers/subtitles.py:267` — provider-fetched subtitle body had
    no size cap. Now 5 MiB cap → 502.
29. `backend/app/gzip_middleware.py:51` — substring `gzip` match compressed for
    `Accept-Encoding: nogzip` and ignored `q=0`. Now proper token parse
    (`_accepts_gzip`, incl. `x-gzip`).

## Reviewed, intentionally NOT changed (documented risk acceptance)

- `backend/app/auth.py:117,153`, `backend/app/routers/gdrive.py:105` —
  JWT via URL query param (logs/history/Referer exposure). Client-compat
  feature for players; removing breaks clients. Not touched.
- `backend/app/routers/auth.py:122` — refresh rotation is SELECT-then-UPDATE
  (concurrent reuse can double-succeed). Atomic consume needs a migration-safe
  rework; flagged for follow-up, not a minimal fix.
- `backend/app/auth.py:135`, `routers/auth.py:97`, `routers/gdrive.py:121`,
  `routers/streaming.py:72` — `ver`-less legacy tokens bypass `auth_version`
  checks. Only pre-`ver` tokens affected; tightening invalidates live clients.
- `backend/app/config.py:116` + `auth.py:31,36` — 7-day access / 28-day
  refresh / 30-day download lifetimes are generous but configured, not bugs.
- `backend/app/streaming.py:147` — per-video `CacheManager` unbounded by
  movie count (OOM under many distinct movies). Needs eviction policy rework.
- `backend/app/streaming.py:1989`, `:1609` — unbounded semaphore admission +
  untimed fallback semaphore waits (slowloris). Needs backpressure redesign.
- `backend/app/routers/streaming.py:750` — cast probe downloads the entire
  file for the `ffprobe` header check. Bandwidth/CPU amplifier by design;
  needs ranged-probe rework.
- `backend/app/grabber.py:44,75,84` — several unbounded dict caches
  (`_GROUP_CHAT_ID_CACHE`, `_GROUP_COOLDOWN`, `_last_click_at`,
  `_bot_flood_until`, `_rewind_tasks`). Needs TTL/locking rework.
- `backend/app/database.py:228` — startup full-table `SELECT` + per-row
  `UPDATE` (slow boot on huge libraries). Migration concern, not minimal.
- `backend/app/routers/tv.py:192` — `le=1000` folder listing + unbounded
  offset; `folders.py:42` unbounded admin list; `tv.py:242` full folder-table
  load. Pagination rework, out of scope.
- `backend/app/routers/diagnostic.py:58` — `/diag/bandwidth` up to 2 GB/req,
  whole diag router un-limited; gated by `DEBUG_PASSWORD` (deny-by-default
  when unset — verified in `utils.py:10`). Needs limiter pass.
- `backend/app/routers/auth.py:241,258` — 10 s long-poll × 80/min/IP allows
  connection holding; distributed-DoS mitigation needs infra limits.
- `backend/app/bot.py:1083+` (14 sites) — `int(data.split(":")[1])`
  `ValueError` on crafted `callback_data`; contained by `_log_exceptions`
  (no crash, callback just dies). Needs a parse helper + user feedback pass.
- `backend/app/bot.py:837,1033,1833`, `bot.py:1499` (folder count w/o
  `user_id` filter), `telegram.py:227` (cooldown check-then-act),
  `telegram.py:169` (flood-wait first-number parse), `gzip_middleware.py:77`
  (sync `gzip.compress` on loop), `streaming.py:638` (`_prefetch_size` leak),
  `run_nouvloop.py:33` (blocking GC on loop), `setup.py` per-endpoint limits
  only — all low-severity; fixes risk behavior churn, deferred.
- `backend/app/patch.py:37` — `check_cbd` looks dead (only commented call)
  but is a public `PatchedClient` method; kept intentionally.
- `backend/app/models.py:40` — `gdrive_token` stored plaintext; needs
  at-rest encryption design, not a minimal fix.
- `backend/app/database.py:105-196` f-string SQL — verified internal
  identifiers only (`Base.metadata` tables, hardcoded roles); no SQLi.
- JWT `alg` pinning (`HS256`), `exp` verification, SHA256-only refresh
  storage, login-code atomic consume (`DELETE…WHERE` + rowcount), slowapi
  `Cf-Connecting-Ip`-from-loopback-only, CORS allowlist, `escape_like`
  usage, no `shell=True`/`pickle`/`yaml.load`/XXE/user-URL SSRF — all verified
  clean.
