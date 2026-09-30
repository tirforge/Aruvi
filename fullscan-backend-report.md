# Fullscan Backend Report — `backend/` only

- **Branch:** `opencode/fullscan-backend-10`
- **Scope (strict):** only files under `backend/`. No changes to other top-level dirs, `.github/`, or vendored/build output (`backend/app/static/vendor/`, `backend/app/static/assets/`).
- **Dirs scanned:**
  - `backend/app/`
  - `backend/app/routers/`
  - `backend/sql/`
  - `backend/tests/`
  - `backend/` root (`run.py`, `run_nouvloop.py`, `pyproject.toml`, `requirements.txt`, `pytest.ini`, `Dockerfile`)
- **File count:** 76 total files under `backend/` (40 `*.py` source files; remainder static assets, SQL, config). Excluded from edits: `backend/app/static/vendor/*`, `backend/app/static/assets/*`.
- **Verdict:** NOT CLEAN — 18 minimal fixes applied across 16 files (see below). All fixes are safe/minimal, no refactors, no dependency changes.

## Verification

- `python3 -m compileall -q backend/app backend/tests` → OK
- `python3 -m py_compile` on all 16 touched files → OK
- `pytest` / `ruff` not available in runner (no `pytest` module, no `ruff` binary) — could not run suite/lint. No test files touched.
- Manual review of every `backend/app/*.py` + `backend/app/routers/*.py` + `run*.py` + `services.py` + `patch.py` + `media_types.py` + `models.py` + `schemas.py` + `config.py` + `database.py`.

## Findings FIXED (file:line = post-fix location)

1. `backend/app/auth.py:108` (high) — `verify_token()` raised unhandled `ValueError` on non-numeric JWT `sub`, turning a bad token into a 500. Fixed with `try/except (TypeError, ValueError) → None`.
2. `backend/app/auth.py:86` (medium) — `refresh_token()` router did `int(payload.get("sub"))` without guard (same 500-on-forged-sub). Fixed with `try/except → None` (`backend/app/routers/auth.py:90`).
3. `backend/app/auth.py:29,210` (medium) — `_last_active_touch` dict grew unbounded (one entry per user id, never evicted). Fixed with LRU-style prune at >5000 entries.
4. `backend/app/auth.py:233` (low) — swallowed `last_active` DB error with bare `except: rollback`. Fixed to log `logger.warning`.
5. `backend/app/routers/streaming.py:89,97` (medium) — Range regex unanchored (`re.match` without `$` accepted `bytes=0-10XYZ` prefix). Fixed to `r"bytes=-(\d+)\s*$"` and `r"bytes=(\d+)-(\d*)\s*$"`.
6. `backend/app/routers/streaming.py:382,647` (medium) — off-by-one range guard `until_bytes > file_size` allowed `until == file_size` (1 byte past EOF, wrong `Content-Length`/`Content-Range`). Fixed to `>= file_size` in both authed + public stream paths.
7. `backend/app/gzip_middleware.py:51` (low) — case-sensitive `b"gzip" not in accept` violates RFC 7231 (token is case-insensitive). Fixed to `accept.lower()`.
8. `backend/app/main.py:407` (medium) — SPA static serve used `f"app/static/{full_path}"` with only a `".." in full_path` substring block (bypassable via normalization/encoding). Fixed with `os.path.realpath` containment check against static root.
9. `backend/app/main.py:426` (low) — `accept-encoding` check case-sensitive. Fixed with `.lower()`.
10. `backend/app/routers/grab.py:86` (high) — `SelectRequest.depth` had `ge=0` with no upper bound; `grabber.py` walked `page_idx <= depth` (each page ~8s+RPC) → page-walk DoS. Fixed to `le=10` (= `MAX_PAGES`) + `max_length` caps on `group_username`/`file_name`.
11. `backend/app/grabber.py:1481` (high, defense-in-depth) — `walk_limit = max(depth,0)` with no cap even if API validation bypassed. Fixed to `min(max(depth,0), MAX_PAGES)`.
12. `backend/app/routers/subtitles.py:392` (medium) — `provider: str = Query(...)` flowed unchecked into `subliminal.list_subtitles(providers=[provider])` (provider-loader input). Fixed with allowlist `set(_subliminal_providers()) | {"opensubtitlescom"}` → 400 otherwise.
13. `backend/app/gdrive.py:288` (medium) — predictable tmp path `f"{msg.id}_{int(time.time())}.tmp"` collides when same file uploads twice in one second (second truncates first). Fixed with `secrets.token_hex(8)` suffix (`secrets` already imported).
14. `backend/app/disk_cache.py:186,249,282` (medium) — unguarded `cache_dir.iterdir()` / `_remove_dir().iterdir()` crashes sweep if dir vanishes mid-sweep (`FileNotFoundError`). Fixed with `list()` snapshot + `try/except OSError` in both sweep passes and `_remove_dir`.
15. `backend/app/routers/setup.py:32,45,60` (medium) — `_cleanup_expired()` used deprecated `asyncio.get_event_loop().create_task` (breaks under uvicorn loop policy) and had no cap (one live Pyrogram `Client` per `send-code` → OOM). Fixed with `get_running_loop().create_task` + fallback + cap at 20 pending + docstring corrected (no `DEBUG_PASSWORD` fallback).
16. `backend/app/schemas.py:184` (low) — `TokenPayload.sub: int` wrong type (JWT `sub` is always `str`). Fixed to `str`.
17. `backend/app/schemas.py:138` (low) — `WatchProgressUpdate.position/duration` accepted negatives/floats silently truncated. Fixed to `Field(ge=0)` + validator rejects negatives.
18. `backend/app/schemas.py:219` (low) — `BatchMoveRequest.ids` unbounded (DoS via huge `IN` list). Fixed to `Field(max_length=500)`.
19. `backend/app/routers/files.py:284` / `backend/app/routers/folders.py:386` (medium) — `batch-delete` accepted unbounded + empty lists (`IN ()` edge). Fixed with `>500 → 400` + early return on empty.
20. `backend/app/bot.py:1503,1560` (medium) — `delfolder` count + `confirmdelfolder` file-move used unscoped `File.folder_id == folder_id` (relies solely on folder-ownership check). Fixed with `File.user_id == folder.user_id` scoping.
21. `backend/app/routers/diagnostic.py:57,99,221,231` (medium) — heavy debug endpoints (`/bandwidth` up to 2GB, `/clear-cache`, `/stream`) had no rate limit. Fixed with `@limiter.limit("10/minute")` / `"30/minute"` + reduced `/bandwidth` max from `le=2000` to `le=500`.
22. `backend/app/routers/auth.py:72` (medium) — `/auth/refresh` had no rate limit (credential-stuffing/replay probing). Fixed with `@limiter.limit("30/minute")` + added `raw_request: Request` for slowapi.

## Reviewed and INTENTIONALLY NOT changed (with rationale)

- `backend/app/config.py:116` 7-day `jwt_expiry_minutes=10080` — design choice; shortening would log out all users. Not a safe minimal fix.
- `backend/app/models.py:40` `gdrive_token` plaintext — encrypting requires migration + key management; out of minimal-fix scope.
- `backend/app/routers/auth.py:104` refresh rotation TOCTOU — needs `SELECT … FOR UPDATE` / atomic consume; risky without DB concurrency tests. Left for follow-up.
- `backend/app/auth.py:135,191` tokens without `ver` bypass `logout-all` — all minted tokens include `ver`; rejecting `None` would invalidate legacy sessions. Needs migration plan.
- `backend/app/bot.py:160` `check_auth` no-op ("All users can use the bot") — intentional product behavior per docstring.
- `backend/app/streaming.py` semaphore/CappedSemaphore/`_disk_write_pending` races, `telegram.py` `gather()` abort, `patch.py` `self.loop.create_future()` — deep concurrency, needs load testing; no safe one-liner.
- `backend/app/routers/folders.py` recursive CTEs — verified all live endpoints scope by `Folder.user_id == current_user.id`; old unscoped helper already removed (comment at top of file).
- `backend/app/routers/streaming.py:72` `token_version is None` download-token path — all minted download tokens carry `ver`; tightening would break legacy links.
- `backend/app/grabber.py` auto-join, `backend/app/bot.py` `int(callback)` parsing (covered by `_log_exceptions`), markdown interpolation, `backend/tests/test_fixes.py` placeholder — low severity or needs UX/product decision.

## Files touched (16)

`backend/app/auth.py`, `backend/app/bot.py`, `backend/app/disk_cache.py`, `backend/app/gdrive.py`, `backend/app/grabber.py`, `backend/app/gzip_middleware.py`, `backend/app/main.py`, `backend/app/routers/auth.py`, `backend/app/routers/diagnostic.py`, `backend/app/routers/files.py`, `backend/app/routers/folders.py`, `backend/app/routers/grab.py`, `backend/app/routers/setup.py`, `backend/app/routers/streaming.py`, `backend/app/routers/subtitles.py`, `backend/app/schemas.py`
