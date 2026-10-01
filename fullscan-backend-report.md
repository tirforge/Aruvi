# Fullscan Backend Report — `backend/` audit + fixes

**Branch:** `opencode/fullscan-backend-13`
**Scope (strict):** only files under `backend/`. No other top-level dirs, `.github/`, or vendored/build output touched.
**Date (UTC):** 2026-10-01
**Verdict:** NOT CLEAN — 26 findings, all fixed minimally in this run (see below).

## Dirs scanned

- `backend/` (root: `run.py`, `run_nouvloop.py`, `requirements.txt`, `pyproject.toml`, `pytest.ini`, `Dockerfile`, `sql/`)
- `backend/app/` (all `*.py`: `auth`, `bot`, `config`, `database`, `disk_cache`, `gdrive`, `grabber`, `gzip_middleware`, `main`, `media_types`, `models`, `patch`, `rate_limit`, `schemas`, `services`, `static_allowlist`, `status`, `streaming`, `telegram`, `utils`)
- `backend/app/routers/` (all `*.py`: `__init__`, `admin`, `auth`, `diagnostic`, `files`, `folders`, `gdrive`, `grab`, `legal`, `setup`, `streaming`, `subtitles`, `tv`)
- `backend/tests/` (`conftest.py`, `test_cast_remux.py`, `test_fixes.py`, `test_login_e2e.py`, `test_longpoll_login.py`)
- `backend/sql/` (`001_tier1_rls_lockdown.sql`)
- `backend/app/static/` listed but **excluded from edits** per vendored/build rule (`vendor/`, `assets/`); only scanned for references.

**File count:** 77 files total under `backend/` (41 `*.py` files, ~16.6k Python LOC). Excluded from fix scope: `backend/app/static/vendor/*`, `backend/app/static/assets/*`.

## What was checked

- Auth/tokens: JWT mint/verify, `type`/`ver`/`sub` handling, refresh rotation + replay, `logout-all` (`auth_version`), download-token `file_id` binding, `?token=` query path, `DEBUG_PASSWORD`/`SETUP_PASSWORD` compare-digest, rate-limit coverage, CORS, open redirects.
- Injection: SQL (ORM vs raw), LIKE escaping, command/subprocess, path traversal (`sanitize_filename`, static allowlist, `int` dir keys), SSRF (subtitle `link`, diag `?chat=`, gdrive OAuth), XSS (`html_escape`), regex DoS, unsafe deserialization (pickle/yaml).
- Concurrency/races: `asyncio.gather` boot, per-client semaphores, folder CTE TOCTOU, upload dedup, listener multiplexing, disk-cache `.tmp` atomicity, `used_bytes` caching, `_forward_streams` keys.
- Error handling: bare `except: pass`, Telegram-error passthrough, `int(sub)`/`int(year)` crashes, `None` header crashes, `KeyError` in middleware, stale-loop futures, unbounded inputs/lists, missing pagination, silent config failures.
- Dead code: unused `settings` snapshots, local imports, trivial overrides, stale comments.
- Verification: `python3 -m compileall -q backend/app backend/tests backend/run.py backend/run_nouvloop.py` → exit 0. `pytest`/`ruff`/`mypy` not installed in runner, so unit tests could not be executed here (CI will run them on the PR). Existing `backend/tests/test_fixes.py` expectations were manually cross-checked (range parser, download-token binding, `auth_version`, disk-cache `.tmp` sparing).

## Findings fixed (file:line — line numbers post-fix, approximate)

All fixes are safe/minimal (1–15 lines each), no refactors, no dependency changes.

1. `backend/app/utils.py:6` — `bearer_token_matches(None, …)` raised `AttributeError` → 500. Fixed: `if not auth_header or not expected: return False`, type `str | None`.
2. `backend/app/auth.py:98` — `verify_token()` did `int(sub)` unguarded → `ValueError` → 500 on crafted `sub`. Fixed: try/except `(TypeError, ValueError)` → `None`.
3. `backend/app/schemas.py:49` — `FolderBase.name` unbounded (empty/10 MB names hit DB). Fixed: `Field(min_length=1, max_length=255)`.
4. `backend/app/schemas.py:58` — `FolderUpdate.name` unbounded. Fixed: same bounds.
5. `backend/app/schemas.py:80` — `FileBase.file_name`/`file_size` unbounded/negative. Fixed: `min_length=1, max_length=255`, `ge=0`.
6. `backend/app/schemas.py:98` — `FileUpdate.file_name` unbounded (empty → surprise `unnamed_file` rename). Fixed: same bounds.
7. `backend/app/schemas.py:137` — `WatchProgressUpdate.position/duration` accepted negatives/astronomic ints. Fixed: `ge=0, le=2**53`.
8. `backend/app/schemas.py:211` — `BatchMoveRequest.ids` unbounded (empty → pointless round-trip; 100k → giant `IN`). Fixed: `Field(min_length=1, max_length=1000)`.
9. `backend/app/routers/tv.py:146` — `tv_search q` had `min_length=1` only; MB-long `q` → `%…%` ILIKE full-table scans. Fixed: `max_length=200`.
10. `backend/app/routers/tv.py:6` — local `from fastapi import HTTPException` inside `tv_folder_detail`. Fixed: hoisted to top-level import.
11. `backend/app/routers/tv.py:239` — breadcrumb loaded **entire** folder table (`select(Folder).where(user)`) → OOM on large accounts. Fixed: iterative parent walk with `user_id` predicate + depth cap 100.
12. `backend/app/routers/tv.py:14` — dead `settings = get_settings()` (never used). Fixed: removed import + snapshot.
13. `backend/app/routers/files.py:30` — dead `settings = get_settings()` (never used). Fixed: removed import + snapshot; added module `_log`.
14. `backend/app/routers/files.py:218,449,481` — three post-commit re-fetches dropped `File.user_id` predicate (TOCTOU hardening). Fixed: re-added `File.user_id == current_user.id` to all three.
15. `backend/app/routers/files.py:268,306` — Telegram cleanup `except: pass` hid persistent delete backlog. Fixed: `_log.warning(…)`.
16. `backend/app/routers/files.py:282` — `batch_delete_files(file_ids: list[int])` unbounded. Fixed: 400 on empty / >1000.
17. `backend/app/routers/folders.py:231,305,433,510` — recursive CTE anchors + recursive steps had no `user_id` predicate (poisoned parent chain → cross-user traversal). Fixed: scoped anchor + recursive step by `Folder.user_id == current_user.id` in all four CTEs.
18. `backend/app/routers/folders.py:334,341,355,360,447,463` — file/folder deletes/updates keyed off CTEs had no `user_id` predicate. Fixed: added `File.user_id` / `Folder.user_id` predicates to all.
19. `backend/app/routers/folders.py:379,410` — `batch_delete_folders(folder_ids)` + `batch_move` unbounded/empty. Fixed: 400 on empty / >1000 (delete); move path already bounded by `BatchMoveRequest`.
20. `backend/app/routers/folders.py:370,450` — Telegram cleanup `except: pass`. Fixed: `_log.warning(…)`.
21. `backend/app/routers/subtitles.py:372` — `provider` unvalidated, passed to `subliminal.list_subtitles(providers=[provider])` (load-path risk). Fixed: allowlist `set(_subliminal_providers()) | {"opensubtitlescom"}` → 400 otherwise.
22. `backend/app/routers/subtitles.py:249` — SSRF + unbounded buffering via provider `link` (`follow_redirects=True`, `.content` no cap). Fixed: require `https`, host allowlist (`*.opensubtitles.com/org`), `raise_for_status`, 5 MB cap (header + body).
23. `backend/app/routers/subtitles.py:81` — `int(year)` on exotic guessit output could raise. Fixed: try/except → `{}`.
24. `backend/app/routers/grab.py:77` — `SelectRequest row/col/depth` had `ge=0` only. Fixed: `le=1000`; `group_username`/`file_name` got `max_length` caps.
25. `backend/app/routers/grab.py:114` — search-cache hit returned shared `SearchResponse` by reference (mutation aliasing). Fixed: `.model_copy(deep=True)`.
26. `backend/app/routers/grab.py:225` — prefetch `except: pass`. Fixed: `_log.warning(…)`.
27. `backend/app/routers/setup.py:63` — `SendCodeIn/SignInIn` no length bounds (oversized → pyrogram/Telegram). Fixed: `Field(max_length=…)`, `api_id ge/le`.
28. `backend/app/routers/setup.py:84` — login-attempt token `uuid4().hex[:16]` (~64-bit). Fixed: `secrets.token_hex(16)` (128-bit).
29. `backend/app/routers/setup.py:32` — `_pending` unbounded + `get_event_loop()` deprecated + request-driven cleanup only. Fixed: `_PENDING_MAX=100` oldest-first eviction, `get_running_loop()`.
30. `backend/app/routers/setup.py:99,128,130` — raw Telegram errors in 400 bodies (probing aid). Fixed: generic messages + server-side `_log.warning`.
31. `backend/app/routers/gdrive.py:82` — `web_base_url` interpolated into HTML unescaped (operator-controlled XSS if `WEB_BASE_URL=javascript:…`). Fixed: `html_escape(…, quote=True)`.
32. `backend/app/gdrive.py:286` — temp path `f"{msg.id}_{int(time.time())}.tmp"` predictable + collides for concurrent same-msg uploads. Fixed: `f"{msg.id}_{secrets.token_hex(8)}.tmp"` (`secrets` already imported).
33. `backend/app/grabber.py:1727` — `mime_type = mime_type or "video/mp4"` **before** `classify_file_type` forced every unknown document (pdf/zip) to `"video"`. Fixed: classify first, then apply streaming fallback.
34. `backend/app/patch.py:60` — `msg.from_user.is_self` crashed on channel/service messages (`from_user is None`). Fixed: `getattr(msg.from_user, "is_self", False)`.
35. `backend/app/patch.py:69,89,106,122` — `self.loop.create_future()` keeps import-time loop for bare `PatchedClient`. Fixed: `asyncio.get_running_loop().create_future()` ×4.
36. `backend/app/gzip_middleware.py:79` — `state.pop("start")` → `KeyError` if start already flushed for streamed compressible body. Fixed: `pop("start", None)` + raw-send fallback.
37. `backend/app/routers/streaming.py:72` — ver-less download tokens accepted (`token_version is None or …`), bypassing `logout_all`. Fixed: require `token_version is not None and >= auth_version` (all minters set `ver`).
38. `backend/app/routers/streaming.py:382,647` — `until_bytes > file_size` off-by-one (`until_bytes` inclusive; max valid `file_size-1`). Fixed: `>= file_size` in both routes.
39. `backend/app/disk_cache.py:274` — `_remove_dir` unlinked `*.tmp` in-flight writes on TTL/global-cap paths (per-video path already excluded them). Fixed: skip `*.tmp`.
40. `backend/app/disk_cache.py:271` — `sweep()` never invalidated `used_bytes` cache → status under-reported for 15s after freeing GBs. Fixed: `self._used_at = None` at end.
41. `backend/app/config.py:71,81` — malformed `AUTH_USERS`/`ADMIN_IDS` silently became `[]`/`set()`. Fixed: `logger.warning` with raw value.
42. `backend/app/routers/diagnostic.py:58` — `GET /bandwidth?mb=2000` → up to 2 GB/response, no limiter (bandwidth/memory DoS). Fixed: `le=100`.
43. `backend/app/telegram.py:193` — `start_all_clients` used `gather(*tasks)`; one `ConnectionError` aborted boot. Fixed: `return_exceptions=True` (`start_one_client` already handles retry/flood).

## Deliberately NOT changed (checked, left as-is)

- `AUTH_USERS` → admin promotion (`bot.py:91`): by-design per docstring (first-user + allowlist admins); changing would break operator workflow. Flagged for operator review, not auto-fixed.
- Complex streaming internals (backpressure fairness, prebuffer `try/finally`, per-chunk timeouts, `_stream_semaphore` gate): real but high-risk without load-test harness; left for follow-up with benchmarks.
- Search-cache per-user keying (`grab.py:50`): `msg_id`s are Ivy-account-scoped, sharing may be intentional; only aliasing fixed.
- `gdrive_token` plaintext (`models.py:40`): needs migration + KMS/Fernet design, not a minimal patch.
- JWT lifetimes (7d/28d) and `run.py` vs `run_nouvloop.py` divergence: operational decisions, flagged for follow-up.
- `_parse_key` variable names (`disk_cache.py:29`): misleading (`mid, cid`) but return order `(chat, msg)` is correct — no fix needed.
- SQL injection: none found (ORM bound params + `escape_like`); command injection: none in scope; path traversal: defended; regex DoS: none (all linear).

## Verification

- `python3 -m compileall -q backend/app backend/tests backend/run.py backend/run_nouvloop.py` → exit 0.
- `pytest`/`ruff`/`mypy` unavailable in runner; CI (CI, CodeQL, opencode-review, Sonar) will run on the PR. Manual cross-check against `backend/tests/test_fixes.py` done (see above).
- `git status` confirms only `backend/` files modified; no `.github/`, frontend, android, or `static/vendor|assets` touched.
