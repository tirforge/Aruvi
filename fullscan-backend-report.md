# fullscan-backend report — backend audit (opencode/fullscan-backend-4)

Scope: `backend/` only. Vendored/build output excluded (`app/static/vendor/`,
`app/static/assets/`). No other top-level dirs touched.

## Dirs scanned

- `backend/app/` (incl. `app/routers/`)
- `backend/tests/`
- `backend/run.py`, `backend/run_nouvloop.py`, `backend/requirements.txt`,
  `backend/pyproject.toml`, `backend/pytest.ini`

## File count

- 33 Python files scanned (`app/*.py`: 20, `app/routers/*.py`: 13 scoped —
  12 router modules + `__init__`, `tests/*.py`: 5, `run.py`,
  `run_nouvloop.py`), ~16.4k LOC total.
- Method: full read of every file (4 parallel audit passes + targeted
  re-reads of every edit site to verify each claim against the actual code
  before fixing).

## Verdict: NOT CLEAN — 38 findings, all fixed (see PR `opencode fullscan: backend fixes`)

Findings below are `file:line` (line = location of the defect in `main` at
scan time). Each has a minimal fix in the PR branch.

### Crashers / availability (fixed)

1. `backend/app/main.py:12` — `ctypes.CDLL("libc.so.6")` at import kills
   startup on musl/Alpine/macOS. Fixed: try/except `OSError`, `_libc=None`,
   guard `malloc_trim` call site (`main.py:122`).
2. `backend/app/streaming.py:18,1948` — same hard glibc dependency at import
   + unguarded `malloc_trim` in stream cleanup. Fixed the same way.
3. `backend/run.py:17` — same in the prod entrypoint. Fixed the same way.
4. `backend/app/streaming.py:436` — `int(f.read().strip())` on
   `memory.max` raises `ValueError` on cgroup v2 `"max"` (only `OSError`
   caught) → prefetcher exception path. Fixed: catch `ValueError`, skip
   non-numeric (same for the `memory.current` loop).
5. `backend/app/auth.py:98` — `verify_token` does bare `int(sub)`; crafted
   `sub` → unhandled `ValueError` → 500. Fixed: try/except → `None`.
6. `backend/app/patch.py:60` — `msg.from_user.is_self` dereferences `None`
   for channel posts → `AttributeError`. Fixed: `getattr` chain, missing
   user treated as unverified (raises clean `ValueError`).
7. `backend/app/grabber.py:1106,1493` — `btn.text`/`page_btn.text` passed
   unguarded into `_is_nav_button` (`text.strip()`) → `AttributeError` on
   text-less buttons. Fixed: `or ""` at both call sites.
8. `backend/app/status.py:118` — `_parse_mem_env` raises `ValueError` on
   malformed `MEMORY` env → 500 on public `/api/status`. Fixed: never
   raises, falls back to 16 GiB.
9. `backend/app/status.py:240` — `os.listdir("/proc")` outside try →
   `FileNotFoundError` on non-Linux. Fixed: `OSError` guard.
10. `backend/run_nouvloop.py:38` — active-set built as
    `(info["chat_id"], mid)` over `(key, info)` items, but keys are already
    `(chat_id, message_id)` tuples → shape never matches `exclude_keys` →
    housekeeping evicts LIVE stream caches. Fixed: `set(_forward_streams.keys())`
    (matches `run.py`).
11. `backend/app/routers/files.py:219,447,479` — re-fetch after update/share/
    revoke uses `scalar_one()` with no ownership scope → 500 on concurrent
    delete. Fixed: user-scoped `scalar_one_or_none()` + 404.

### Security (fixed)

12. `backend/app/routers/streaming.py:72` — download-token check accepts
    `ver is None`, so pre-rotation tokens without `ver` bypass `logout-all`
    forever. Fixed: token must carry `ver` and equal `auth_version`.
13. `backend/app/auth.py:135,191`, `backend/app/routers/auth.py:97`,
    `backend/app/routers/gdrive.py:121` — version check uses `<` not `!=`;
    a version rollback/DB restore resurrects stale tokens. Fixed: `!=`.
14. `backend/app/routers/auth.py:356` — legacy `POST /auth/code` has no rate
    limit while the equivalent `/verify-code` has `80/minute` (inner
    decorator not enforced on direct delegation) → unlimited code guessing.
    Fixed: `@limiter.limit("10/minute")`.
15. `backend/app/main.py:399` — catch-all `serve_spa` builds
    `app/static/{full_path}` with only a `".." in full_path` check (no
    normalization, symlink escape possible). Fixed: `realpath` +
    `commonpath` containment check → 404 on escape.
16. `backend/app/gdrive.py:286` — Drive staging temp name
    `{msg.id}_{time.time()}.tmp` is predictable; concurrent uploads of the
    same message in the same second share one file → interleaved/corrupt
    upload. Fixed: append `secrets.token_hex(4)` (`secrets` already imported).
17. `backend/app/routers/subtitles.py:254` — provider-supplied subtitle body
    loaded unbounded into memory/JSON (`follow_redirects=True`, no size
    cap) → malicious provider response OOMs server+client. Fixed: 1 MB cap
    → 502 (normal subtitles are KBs).
18. `backend/app/routers/files.py:276`, `:484`,
    `backend/app/routers/folders.py:378`, `:458` — `batch-delete`/`batch-move`
    accept unbounded ID lists → giant `IN (...)` queries (DoS/memory).
    Fixed: cap 100 with 400 otherwise.
19. `backend/app/routers/setup.py:84` — `_pending` has no size cap; each
    `send-code` spawns a Pyrogram client → FD/memory DoS. Fixed: cap 20 →
    429 (with TTL cleanup already present).
20. `backend/app/routers/folders.py:333,341,355,416,432` — file
    move/select/delete statements in `delete_folder`/`batch_delete_folders`
    filter by folder subtree only, no `File.user_id` predicate
    (defense-in-depth). Fixed: added user predicate (no behavior change —
    subtrees are already ownership-anchored).
21. `backend/app/routers/tv.py:148`, `backend/app/routers/subtitles.py:278`,
    `backend/app/routers/subtitles.py:375` — unbounded `q`/`language`/
    `provider`/`subtitle_id` query strings flow into `ilike`/provider libs
    (slow-query/CPU DoS). Fixed: `max_length` caps (100/32/64/128).
22. `backend/app/routers/grab.py:83` — `SelectRequest.file_name` unbounded.
    Fixed: `max_length=500`.
23. `backend/app/routers/folders.py:149` — `create_folder` duplicate
    check-then-insert TOCTOU → duplicates under concurrency, raw 500.
    Fixed: catch `IntegrityError` → 400 (matches existing duplicate path).
24. `backend/app/gzip_middleware.py:51` — `b"gzip" in accept` is
    case-sensitive and substring-matches `x-gzip` (a different coding).
    Fixed: tokenized, case-insensitive comparison.

### Error handling / observability (fixed)

25. `backend/app/main.py:113,133,149` — three background loops swallow all
    exceptions with bare `except Exception: pass`. Fixed: `logger.warning(
    ..., exc_info=True)`.
26. `backend/app/auth.py:127,170` — `except Exception: return None` swallows
    everything incl. programming errors. Fixed: narrow to
    `(JWTError, ValueError, AttributeError, TypeError)`.
27. `backend/app/utils.py:20` — `spawn_background` discards task exceptions
    silently. Fixed: done-callback logs failures (cancelled tasks ignored).
28. `backend/app/grabber.py:205,517,997` — bare `except Exception: pass`
    hides config/auth/polling failures. Fixed: `_log.warning/debug`.
29. `backend/app/config.py:77,87` — malformed `AUTH_USERS`/`ADMIN_IDS` env
    silently yields `[]`. Fixed: `logger.warning` on `ValueError`.
30. `backend/app/bot.py:42` — `_log_exceptions` wrapper swallows handler
    errors; all 14 `int(data.split(":")[1])` callback sites
    (`bot.py:1083…1881`) then leave the user with a hanging spinner.
    Fixed (single point): wrapper answers the originating callback query
    with a generic retry message on failure.
31. `backend/app/patch.py:250` — `future.set_result(update)` after a
    `done()` check → `InvalidStateError` race aborts dispatcher. Fixed:
    try/except → forget listener + `continue_propagation`.
32. `backend/app/routers/setup.py:39` — deprecated
    `asyncio.get_event_loop().create_task` in `_cleanup_expired` (wrong-loop
    under uvicorn → leaked clients). Fixed: `get_running_loop()` with
    `RuntimeError` fallback.
33. `backend/app/status.py:347` — `get_net` reports negative Mbps on counter
    reset. Fixed: `max(0.0, ...)` clamp.

### Hygiene / correctness (fixed)

34. `backend/app/main.py:450` — `uvicorn.run(..., reload=True)` under
    `__main__` enables the reloader in production. Fixed: `reload=False`.
35. `backend/app/main.py:377,395` — `/status` and `/download` `FileResponse`
    with no existence check → 500 if the asset is missing. Fixed: 404 JSON.
36. `backend/run.py:91`, `backend/run_nouvloop.py:71` — `asyncio.run(run())`
    executes on import. Fixed: `if __name__ == "__main__":` guard.
37. `backend/run_nouvloop.py:13,61` — missing `load_dotenv()` and hardcoded
    `port=7680` (ignores `SERVER_PORT`), unlike `run.py`. Fixed: both.
38. `backend/run_nouvloop.py:43` — `gc.collect()` + `malloc_trim` run
    directly on the event loop every 60 s (stalls streams). Fixed: mirror
    `run.py` via `await asyncio.to_thread(...)`.

## Evaluated and deliberately NOT changed

- `config.py:163` `debug_password=""` — NOT a bypass: every debug/diag
  gate goes through `utils.bearer_token_matches`, which returns `False`
  when `expected` is empty (`utils.py:10`). Verified by read.
- `disk_cache.py` torn-write claim — `put()` already uses per-writer
  `mkstemp` + atomic `os.replace` (`disk_cache.py:161-165`); no change needed.
- `status.py:405,433` "live reference mutation" — `_cache_manager.info` /
  `.per_video` build fresh dicts/lists per call (`streaming.py:130,172,191`);
  `get_forward_snapshot` already copies via `list(...)` (`streaming.py:296,
  300`); single-threaded asyncio dict ops between awaits cannot hit
  "dictionary changed size". No change needed.
- `telegram.py:103` empty-pool `IndexError` — `Settings.telegram_bot_token`
  is required (no default), so `all_bot_tokens` is never empty if settings
  load; a missing token already fails fast at config validation. No change.
- `routers/auth.py:71` no rate limit on `/refresh` — adding
  `@limiter.limit` would break `tests/test_fixes.py:142` (`refresh_token`
  called directly without a `Request`); replay risk is already mitigated by
  single-use rotation (replay → 401). Not changed.
- `main.py:354` public `/api/status` — intentional public dashboard mode
  with logs/per-video stripped for unauthenticated viewers
  (`main.py:357-364`). Not changed.
- Subtitle provider SSRF/allowlist, OAuth `state` store, refresh-session
  `SELECT…FOR UPDATE`, `gdrive_token` encryption-at-rest, sliding refresh
  lifetime, `verify-code` brute-force counters — real hardening ideas but
  each needs design/migration decisions beyond "safe minimal fix"; left for
  follow-ups, not silently fixed.
